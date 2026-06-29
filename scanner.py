import os, time, asyncio, logging, pytz, ta, requests
import pandas as pd
from datetime import datetime
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
SYMS = ['VIC','VHM','VNM','VCB','BID','CTG','MBB','TCB','VPB','ACB','HPG','HSG','MSN','VRE','MWG','FPT','SSI','VND','HCM','VCI','SHS','AGR','GAS','PLX','PVD','STB','EIB','TPB','OCB','LPB','VIB','SSB','VHC','KDH','NLG','DXG','PDR','DIG','HBC','CTD','IJC','SZC','PHR','GVR','BCM','SAB','MSB','HAG','BAF','QNS','DRC','DGW','SHB','NVB','IDC','PAN','NSC','VFG','BCC','NTP','CEO','TNG','VGC','BVS','MBS','VDS','NHH','BTS','SDT','VNR','BKG','S55','VC3','REE','PPC','POW','NT2','VSH','DGC','DPM','DCM','VOS','GMD','HAH','VSC','PVT']

def fetch_1h(sym):
        try:
                    ts = int(datetime.now(VN_TZ).timestamp())
                    url = 'https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/bars-long-term?ticker=' + sym + '&type=stock&resolution=60&from=' + str(ts - 90*86400) + '&to=' + str(ts)
                    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                    if r.status_code != 200:
                                    return None
                                data = r.json().get('data', [])
                    if len(data) < 60:
                                    return None
                                df = pd.DataFrame(data)
                    df.columns = [c.lower() for c in df.columns]
                    ren = {'o':'open','h':'high','l':'low','c':'close','v':'volume','t':'time','tradingdate':'time'}
                    df = df.rename(columns={k: v for k,v in ren.items() if k in df.columns})
                    if 'close' not in df.columns:
                                    return None
                                df['close'] = pd.to_numeric(df['close'], errors='coerce')
                    df = df.dropna(subset=['close']).reset_index(drop=True)
                    return df if len(df) >= 60 else None
except Exception as ex:
        logger.warning(sym + ': ' + str(ex))
        return None

def indicators(df):
        df = df.copy()
        c = df['close']
        df['rsi'] = ta.momentum.RSIIndicator(close=c, window=14).rsi()
        df['ema9'] = ta.trend.EMAIndicator(close=df['rsi'], window=9).ema_indicator()
        w = list(range(1, 46))
        ws = sum(w)
        df['wma45'] = df['rsi'].rolling(45).apply(lambda x: sum(a*b for a,b in zip(w,x))/ws, raw=True)
        return df.dropna()

def signal(df):
        if len(df) < 4:
                    return None
                c = df.iloc[-1]
    if not (c['rsi'] > c['ema9'] and c['rsi'] > c['wma45']):
                return None
            for lb in [2,3,4]:
                        p = df.iloc[-lb]
                        if p['rsi'] <= p['ema9'] or p['rsi'] <= p['wma45']:
                                        return {'rsi': round(float(c['rsi']),2), 'ema9': round(float(c['ema9']),2), 'wma45': round(float(c['wma45']),2), 'close': round(float(c.get('close',0)),2)}
                                return None

def scan():
        results = []
    delay = float(os.getenv('SCAN_DELAY_SECONDS','0.35'))
    logger.info('Scan ' + str(len(SYMS)) + ' ma...')
    for i, sym in enumerate(SYMS, 1):
                try:
                                df = fetch_1h(sym)
                                if df is not None:
                                                    df = indicators(df)
                                                    sig = signal(df)
                                                    if sig:
                                                                            sig['symbol'] = sym
                                                                            results.append(sig)
                                                                            logger.info('[HIT] ' + sym + ' RSI=' + str(sig['rsi']))
                except Exception as ex:
            logger.warning(sym + ': ' + str(ex))
        if i % 20 == 0:
                        logger.info(str(i) + '/' + str(len(SYMS)))
        time.sleep(delay)
    logger.info('Done: ' + str(len(results)) + ' signals')
    return results

async def tg(sigs):
        try:
                    tok = os.getenv('TELEGRAM_BOT_TOKEN','')
                    cid = os.getenv('TELEGRAM_CHAT_ID','')
                    if not tok or not cid:
                                    return
                                from telegram import Bot
                    bot = Bot(tok)
                    now = datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y')
                    if not sigs:
                                    msg = 'RSI scan ' + now + ': khong co tin hieu'
        else:
            lines = ['RSI cat EMA9+WMA45 1H | ' + now + ' | ' + str(len(sigs)) + ' ma']
                        for s in sigs[:25]:
                                            lines.append(s['symbol'] + ' RSI=' + str(s['rsi']) + ' EMA9=' + str(s['ema9']) + ' WMA45=' + str(s['wma45']) + ' Gia=' + str(s['close']))
                                        msg = '\n'.join(lines)
                    await bot.send_message(chat_id=cid, text=msg)
                    logger.info('TG OK')
        except Exception as ex:
        logger.error('TG error: ' + str(ex))

def main():
        logger.info('=== RSI Scanner ' + datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y') + ' ===')
        sigs = scan()
        for s in sigs:
                    logger.info(s['symbol'] + ' ' + str(s['rsi']) + ' ' + str(s['close']))
                asyncio.run(tg(sigs))
    logger.info('Done')

if __name__ == '__main__':
        main()
