import os
import time
import asyncio
import logging
import pytz
import pandas as pdh
import ta
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# Danh sach du phong: chi HOSE va HNX, khong UPCOM
FALLBACK_SYMBOLS = [
    # HOSE blue-chips + mid-cap
    'VIC','VHM','VNM','VCB','BID','CTG','MBB','TCB','VPB','ACB',
    'HPG','HSG','NKG','MSN','VRE','MWG','FPT','SSI','VND','HCM',
    'VCI','SHS','BSI','CTS','AGR','GAS','PLX','PVD','PVS','PVC',
    'VJC','HVN','ACV','SGN','NCT','DHG','IMP','DMC','TRA','DBD',
    'REE','PPC','POW','NT2','VSH','TBC','DGC','DPM','DCM','CSV',
    'VOS','GMD','HAH','VSC','PVT','STB','EIB','TPB','OCB','LPB',
    'NAB','VIB','SSB','VHC','ANV','IDI','KDH','NLG','DXG','PDR',
    'DIG','NTL','HBC','CTD','FCN','C4G','LCG','HHV','CII','DPG',
    'IJC','SZC','PHR','GVR','BCM','SAB','MSB','HAG','HNG','BAF',
    'SBT','QNS','DRC','CSM','DGW','TCD','SRC','VHG','CSV','BSR',
    # HNX
    'PLC','PGT','HUT','SHB','NVB','KLF','IDC','VGS','PAN','NSC',
    'VFG','HNA','PIV','BCC','NTP','CEO','HHS','PVB','SCI','TNG',
    'VGC','HCD','BVS','MBS','VDS','APS','APG','PGI','VIF','HLD',
    'NHH','BTS','SDT','HEM','VNR','BKG','AAM','PLC','S55','VC3',
]

def get_symbols_hose_hnx():
    # Lay danh sach ma HOSE va HNX tu VCI API, bo UPCOM
    try:
        from vnstock3 import Vnstock
        listing = Vnstock().stock(source='VCI').listing
        df = listing.all_symbols()
        logger.info(f'Tong ma tu VCI: {len(df)}')
        if 'exchange' in df.columns:
            df_filtered = df[df['exchange'].str.upper().isin(['HOSE', 'HNX'])]
            symbols = df_filtered['ticker'].dropna().unique().tolist()
            hose_n = len(df[df['exchange'].str.upper() == 'HOSE'])
            hnx_n  = len(df[df['exchange'].str.upper() == 'HNX'])
            logger.info(f'HOSE: {hose_n} | HNX: {hnx_n} | Tong HOSE+HNX: {len(symbols)}')
        else:
            # Fallback: neu khong co cot exchange, lay het roi dung fallback list
            logger.warning('Khong co cot exchange, dung fallback list')
            return FALLBACK_SYMBOLS
        return symbols
    except Exception as e:
        logger.warning(f'Loi VCI API: {e} -> dung fallback list ({len(FALLBACK_SYMBOLS)} ma)')
        return FALLBACK_SYMBOLS

def fetch_ohlcv_1h(symbol):
    try:
        from vnstock3 import Vnstock
        end_date   = datetime.now(VN_TZ).strftime('%Y-%m-%d')
        start_date = (datetime.now(VN_TZ) - timedelta(days=90)).strftime('%Y-%m-%d')
        stock = Vnstock().stock(symbol=symbol, source='TCBS')
        df = stock.quote.history(start=start_date, end=end_date, interval='1H')
        if df is None or len(df) < 60:
            logger.warning(f'[SKIP] {symbol}: df=None hoac it hon 60 nen (co {len(df) if df is not None else 0} nen)')
            return None
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_values('time').reset_index(drop=True)
        return df
    except Exception as e:
        logger.warning(f'[ERROR] {symbol}: {e}')
        return None
def compute_indicators(df):
    df = df.copy()
    close = df['close']
    df['rsi']      = ta.momentum.RSIIndicator(close=close, window=14).rsi()
    df['rsi_ema9'] = ta.trend.EMAIndicator(close=df['rsi'], window=9).ema_indicator()
    weights = list(range(1, 46))
    w_sum = sum(weights)
    df['rsi_wma45'] = df['rsi'].rolling(window=45).apply(
        lambda x: sum(w * v for w, v in zip(weights, x)) / w_sum, raw=True
    )
    return df.dropna()

def detect_signal(df):
    if len(df) < 4:
        return None
    curr = df.iloc[-1]
    above_both = (curr['rsi'] > curr['rsi_ema9'] and curr['rsi'] > curr['rsi_wma45'])
    if not above_both:
        return None
    # Nhin lai toi da 3 nen de bat tin hieu RSI vua cat len EMA9 va WMA45
    for lookback in [2, 3, 4]:
        prev = df.iloc[-lookback]
        below_any_prev = (prev['rsi'] <= prev['rsi_ema9'] or prev['rsi'] <= prev['rsi_wma45'])
        if below_any_prev:
            return {
                'rsi':        round(float(curr['rsi']), 2),
                'rsi_ema9':   round(float(curr['rsi_ema9']), 2),
                'rsi_wma45':  round(float(curr['rsi_wma45']), 2),
                'dist_ema9':  round(float(curr['rsi'] - curr['rsi_ema9']), 2),
                'dist_wma45': round(float(curr['rsi'] - curr['rsi_wma45']), 2),
                'close':  round(float(curr.get('close', 0)), 2),
                'volume': int(curr.get('volume', 0)),
                'candle_time': str(curr.get('time', '')),
            }
    return None
def scan_market():
    symbols = get_symbols_hose_hnx()
    results = []
    total = len(symbols)
    delay = float(os.getenv('SCAN_DELAY_SECONDS', '0.35'))
    logger.info(f'Bat dau scan {total} ma HOSE+HNX...')
    for i, symbol in enumerate(symbols, 1):
        try:
            df = fetch_ohlcv_1h(symbol)
            if df is not None:
                df  = compute_indicators(df)
                sig = detect_signal(df)
                if sig:
                    sig['symbol']      = symbol
                    sig['detected_at'] = datetime.now(VN_TZ).isoformat()
                    results.append(sig)
                    logger.info(f"  SIGNAL [{i}/{total}] {symbol} RSI={sig['rsi']} EMA9={sig['rsi_ema9']} WMA45={sig['rsi_wma45']}")
            if i % 50 == 0:
                logger.info(f'  Tien do: {i}/{total} ({round(i/total*100)}%)')
            time.sleep(delay)
        except Exception as e:
            logger.error(f'Loi {symbol}: {e}')
    logger.info(f'Scan xong: {len(results)} tin hieu / {total} ma HOSE+HNX')
    return results

async def send_telegram(signals):
    token   = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        logger.warning('Chua cau hinh Telegram.')
        return
    try:
        import telegram
        bot = telegram.Bot(token=token)
        now = datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y')
        if not signals:
            msg = f'RSI Scan xong {now} (HOSE+HNX). Khong co tin hieu.'
        else:
            lines = [
                'RSI Cat len EMA9+WMA45 - Khung 1H',
                f'HOSE+HNX | {now} | {len(signals)} ma',
                '',
            ]
            for s in signals[:25]:
                lines.append(
                    f"{s['symbol']} | RSI={s['rsi']} EMA9={s['rsi_ema9']} WMA45={s['rsi_wma45']} Gia={s['close']:,.0f}"
                )
            if len(signals) > 25:
                lines.append(f"...va {len(signals)-25} ma khac")
            msg = chr(10).join(lines)
        await bot.send_message(chat_id=chat_id, text=msg)
        logger.info('Telegram sent OK')
    except Exception as e:
        logger.error(f'Telegram error: {e}')

def main():
    logger.info('=' * 55)
    logger.info('RSI Signal Scanner - HOSE + HNX')
    logger.info(f"Thoi gian: {datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y')}")
    logger.info('=' * 55)
    signals = scan_market()
    if signals:
        logger.info(f'KET QUA: {len(signals)} TIN HIEU')
        for s in signals:
            logger.info(
                f"  {s['symbol']:6s} | RSI={s['rsi']:5.1f} "
                f"EMA9={s['rsi_ema9']:5.1f} WMA45={s['rsi_wma45']:5.1f} "
                f"Gia={s['close']:,.0f}"
            )
    else:
        logger.info('Khong co tin hieu nao.')
    asyncio.run(send_telegram(signals))
    logger.info('Hoan tat.')

if __name__ == '__main__':
    main()
