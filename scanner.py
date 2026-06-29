import os
import time
import asyncio
import logging
import pytz
import pandas as pd
import ta
import requests
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

FALLBACK_SYMBOLS = [
            'VIC','VHM','VNM','VCB','BID','CTG','MBB','TCB','VPB','ACB',
            'HPG','HSG','NKG','MSN','VRE','MWG','FPT','SSI','VND','HCM',
            'VCI','SHS','BSI','CTS','AGR','GAS','PLX','PVD','PVS','PVC',
            'VJC','HVN','ACV','SGN','NCT','DHG','IMP','DMC','TRA','DBD',
            'REE','PPC','POW','NT2','VSH','TBC','DGC','DPM','DCM','CSV',
            'VOS','GMD','HAH','VSC','PVT','STB','EIB','TPB','OCB','LPB',
            'NAB','VIB','SSB','VHC','ANV','IDI','KDH','NLG','DXG','PDR',
            'DIG','NTL','HBC','CTD','FCN','C4G','LCG','HHV','CII','DPG',
            'IJC','SZC','PHR','GVR','BCM','SAB','MSB','HAG','HNG','BAF',
            'SBT','QNS','DRC','CSM','DGW','TCD','SRC','VHG','BSR',
            'PLC','PGT','HUT','SHB','NVB','KLF','IDC','VGS','PAN','NSC',
            'VFG','HNA','BCC','NTP','CEO','HHS','SCI','TNG',
            'VGC','BVS','MBS','VDS','APS','APG','PGI','VIF','HLD',
            'NHH','BTS','SDT','HEM','VNR','BKG','AAM','S55','VC3',
]


def get_symbols_hose_hnx():
            return FALLBACK_SYMBOLS


def fetch_ohlcv_1h(symbol):
            try:
                            now_ts = int(datetime.now(VN_TZ).timestamp())
                            start_ts = now_ts - 90 * 24 * 3600
                            url = (
                                "https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/bars-long-term"
                                "?ticker=" + symbol + "&type=stock&resolution=60"
                                "&from=" + str(start_ts) + "&to=" + str(now_ts)
                            )
                            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                            if r.status_code != 200:
                                                logger.warning('[SKIP] ' + symbol + ': HTTP ' + str(r.status_code))
                                                return None
                                            bars = r.json().get('data', [])
                            if not bars or len(bars) < 60:
                                                logger.warning('[SKIP] ' + symbol + ': chi co ' + str(len(bars)) + ' nen')
                                                return None
                                            df = pd.DataFrame(bars)
                            df.columns = [c.lower() for c in df.columns]
                            rename = {'tradingdate': 'time', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}
                            df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
                            for col in ['open', 'high', 'low', 'close', 'volume']:
                                                if col not in df.columns:
                                                                        logger.warning('[SKIP] ' + symbol + ': thieu cot ' + col)
                                                                        return None
                                                                if 'time' not in df.columns:
                                                                                    df['time'] = range(len(df))
                                                                                df['close'] = pd.to_numeric(df['close'], errors='coerce')
                                            df = df.dropna(subset=['close']).reset_index(drop=True)
                            if len(df) < 60:
                                                return None
                                            return df
except Exception as e:
        logger.warning('[ERROR] ' + symbol + ': ' + str(e))
        return None


def compute_indicators(df):
            df = df.copy()
            close = df['close']
            df['rsi'] = ta.momentum.RSIIndicator(close=close, window=14).rsi()
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
    if not (curr['rsi'] > curr['rsi_ema9'] and curr['rsi'] > curr['rsi_wma45']):
                    return None
                for lookback in [2, 3, 4]:
                                prev = df.iloc[-lookback]
                                if prev['rsi'] <= prev['rsi_ema9'] or prev['rsi'] <= prev['rsi_wma45']:
                                                    return {
                                                                            'rsi': round(float(curr['rsi']), 2),
                                                                            'rsi_ema9': round(float(curr['rsi_ema9']), 2),
                                                                            'rsi_wma45': round(float(curr['rsi_wma45']), 2),
                                                                            'close': round(float(curr.get('close', 0)), 2),
                                                                            'volume': int(curr.get('volume', 0)),
                                                                            'candle_time': str(curr.get('time', '')),
                                                    }
                                            return None


def scan_market():
            symbols = get_symbols_hose_hnx()
    results = []
    total = len(symbols)
    delay = float(os.getenv('SCAN_DELAY_SECONDS', '0.35'))
    logger.info('Bat dau scan ' + str(total) + ' ma HOSE+HNX...')
    for i, symbol in enumerate(symbols, 1):
                    try:
                                        df = fetch_ohlcv_1h(symbol)
                                        if df is not None:
                                                                df = compute_indicators(df)
                                                                sig = detect_signal(df)
                                                                if sig:
                                                                                            sig['symbol'] = symbol
                                                                                            results.append(sig)
                                                                                            logger.info('[TIN HIEU] ' + symbol + ' RSI=' + str(sig['rsi']))
                    except Exception as e:
            logger.warning('[OUTER ERROR] ' + symbol + ': ' + str(e))
        if i % 25 == 0:
                            logger.info('Tien do: ' + str(i) + '/' + str(total))
        time.sleep(delay)
    logger.info('Ket qua: ' + str(len(results)) + ' tin hieu')
    return results


async def send_telegram(signals):
            try:
                            token = os.getenv('TELEGRAM_BOT_TOKEN', '')
                            chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
                            if not token or not chat_id:
                                                logger.warning('Thieu TELEGRAM credentials')
                                                return
                                            from telegram import Bot
                            bot = Bot(token=token)
                            now = datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y')
                            if not signals:
                                                msg = 'RSI Scan xong ' + now + ' (HOSE+HNX). Khong co tin hieu.'
            else:
            lines = ['RSI Cat len EMA9+WMA45 - Khung 1H', 'HOSE+HNX | ' + now + ' | ' + str(len(signals)) + ' ma', '']
                                for s in signals[:25]:
                                                        lines.append(s['symbol'] + ' RSI=' + str(s['rsi']) + ' EMA9=' + str(s['rsi_ema9']) + ' WMA45=' + str(s['rsi_wma45']) + ' Gia=' + str(s['close']))
                                                    if len(signals) > 25:
                                                                            lines.append('...va ' + str(len(signals) - 25) + ' ma khac')
                                                                        msg = '\n'.join(lines)
                            await bot.send_message(chat_id=chat_id, text=msg)
                            logger.info('Telegram sent OK')
            except Exception as e:
                            logger.error('Telegram error: ' + str(e))


                    def main():
                                logger.info('=' * 55)
                                logger.info('RSI Signal Scanner - HOSE + HNX')
                                logger.info('Thoi gian: ' + datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y'))
                                logger.info('=' * 55)
                                signals = scan_market()
                                if signals:
                                                logger.info('KET QUA: ' + str(len(signals)) + ' TIN HIEU')
                                                for s in signals:
                                                                    logger.info(s['symbol'] + ' RSI=' + str(s['rsi']) + ' Gia=' + str(s['close']))
                                else:
                                                logger.info('Khong co tin hieu nao.')
                                            asyncio.run(send_telegram(signals))
                                logger.info('Hoan tat.')


                    if __name__ == '__main__':
                                main()
                            
