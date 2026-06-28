import os
import time
import asyncio
import logging
import pytz
import pandas as pd
import ta
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

PRIORITY_SYMBOLS = [
    "VIC","VHM","VNM","VCB","BID","CTG","MBB","TCB","VPB","ACB",
    "HPG","HSG","NKG","MSN","VRE","MWG","FPT","SSI","VND","HCM",
    "VCI","SHS","BSI","CTS","AGR","VDS","GAS","PLX","PVD","PVS",
    "VJC","HVN","ACV","DHG","IMP","DMC","REE","PPC","POW","NT2",
    "DGC","DPM","DCM","VOS","GMD","HAH","VSC","PVT","STB","EIB",
    "TPB","OCB","LPB","NAB","VIB","SSB","VHC","ANV","KDH","NLG",
    "DXG","PDR","DIG","NTL","HBC","CTD","FCN","C4G","LCG","HHV",
    "CII","DPG","IJC","SZC","PLC","SHB","NVB","IDC","VGS","PAN",
    "HAG","HNG","BAF","MSB","PHR","GVR","BCM","SAB","VPG","SIP",
]

def get_all_symbols():
    use_priority = os.getenv("USE_PRIORITY_ONLY", "false").lower() == "true"
    if use_priority:
        logger.info(f"Priority mode: {len(PRIORITY_SYMBOLS)} symbols")
        return PRIORITY_SYMBOLS
    try:
        from vnstock3 import Vnstock
        listing = Vnstock().stock(source='VCI').listing
        df = listing.all_symbols()
        symbols = df['ticker'].dropna().unique().tolist()
        logger.info(f"Got {len(symbols)} symbols from VCI")
        return symbols
    except Exception as e:
        logger.warning(f"Fallback to priority list: {e}")
        return PRIORITY_SYMBOLS

def fetch_ohlcv_1h(symbol):
    try:
        from vnstock3 import Vnstock
        end_date = datetime.now(VN_TZ).strftime('%Y-%m-%d')
        start_date = (datetime.now(VN_TZ) - timedelta(days=90)).strftime('%Y-%m-%d')
        stock = Vnstock().stock(symbol=symbol, source='TCBS')
        df = stock.quote.history(start=start_date, end=end_date, interval='1H')
        if df is None or len(df) < 60:
            return None
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_values('time').reset_index(drop=True)
        return df
    except Exception as e:
        logger.debug(f"Error {symbol}: {e}")
        return None

def compute_indicators(df):
    df = df.copy()
    close = df['close']
    # RSI(14) dung thu vien ta
    df['rsi'] = ta.momentum.RSIIndicator(close=close, window=14).rsi()
    # EMA9 cua RSI
    df['rsi_ema9'] = ta.trend.EMAIndicator(close=df['rsi'], window=9).ema_indicator()
    # WMA45 cua RSI - tinh tay vi ta khong co WMA
    weights = list(range(1, 46))
    w_sum = sum(weights)
    df['rsi_wma45'] = df['rsi'].rolling(window=45).apply(
        lambda x: sum(w * v for w, v in zip(weights, x)) / w_sum, raw=True
    )
    return df.dropna()

def detect_signal(df):
    if len(df) < 3:
        return None
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    above_both = (curr['rsi'] > curr['rsi_ema9'] and curr['rsi'] > curr['rsi_wma45'])
    below_any_prev = (prev['rsi'] <= prev['rsi_ema9'] or prev['rsi'] <= prev['rsi_wma45'])
    if above_both and below_any_prev:
        return {
            'rsi': round(float(curr['rsi']), 2),
            'rsi_ema9': round(float(curr['rsi_ema9']), 2),
            'rsi_wma45': round(float(curr['rsi_wma45']), 2),
            'dist_ema9': round(float(curr['rsi'] - curr['rsi_ema9']), 2),
            'dist_wma45': round(float(curr['rsi'] - curr['rsi_wma45']), 2),
            'close': round(float(curr.get('close', 0)), 2),
            'volume': int(curr.get('volume', 0)),
            'candle_time': str(curr.get('time', '')),
        }
    return None

def scan_market():
    symbols = get_all_symbols()
    results = []
    total = len(symbols)
    delay = float(os.getenv("SCAN_DELAY_SECONDS", "0.35"))
    logger.info(f"Starting scan: {total} symbols...")
    for i, symbol in enumerate(symbols, 1):
        try:
            df = fetch_ohlcv_1h(symbol)
            if df is not None:
                df = compute_indicators(df)
                sig = detect_signal(df)
                if sig:
                    sig['symbol'] = symbol
                    sig['detected_at'] = datetime.now(VN_TZ).isoformat()
                    results.append(sig)
                    logger.info(f"  SIGNAL [{i}/{total}] {symbol} RSI={sig['rsi']}")
            if i % 20 == 0:
                logger.info(f"  Progress: {i}/{total} ({round(i/total*100)}%)")
            time.sleep(delay)
        except Exception as e:
            logger.error(f"Error {symbol}: {e}")
    logger.info(f"Scan done: {len(results)} signals / {total} symbols")
    return results

async def send_telegram(signals):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("Telegram not configured.")
        return
    try:
        import telegram
        bot = telegram.Bot(token=token)
        now = datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y')
        if not signals:
            msg = f"RSI Scan xong luc {now}. Khong co tin hieu moi."
        else:
            lines = [f"RSI Cat len EMA9+WMA45 khung 1H", f"Thoi gian: {now} | {len(signals)} ma", ""]
            for s in signals[:25]:
                lines.append(f"{s['symbol']} | RSI={s['rsi']} EMA9={s['rsi_ema9']} WMA45={s['rsi_wma45']}")
            if len(signals) > 25:
                lines.append(f"...va {len(signals)-25} ma khac")
            msg = "\n".join(lines)
        await bot.send_message(chat_id=chat_id, text=msg)
        logger.info("Telegram sent OK")
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def main():
    logger.info("=" * 50)
    logger.info("RSI Signal Scanner - TTCK Viet Nam")
    logger.info(f"Time: {datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y')}")
    logger.info("=" * 50)
    signals = scan_market()
    if signals:
        logger.info(f"RESULT - {len(signals)} SIGNALS:")
        for s in signals:
            logger.info(f"  {s['symbol']:6s} RSI={s['rsi']:5.1f} EMA9={s['rsi_ema9']:5.1f} WMA45={s['rsi_wma45']:5.1f} Price={s['close']:,.0f}")
    else:
        logger.info("No signals found.")
    asyncio.run(send_telegram(signals))
    logger.info("Done.")

if __name__ == "__main__":
    main()
