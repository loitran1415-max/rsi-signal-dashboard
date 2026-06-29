import os, time, asyncio, logging, pytz, ta, requests
import pandas as pd
from datetime import datetime
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
SYMS = ['VIC','VHM','VNM','VCB','BID','CTG','MBB','TCB','VPB','ACB','HPG','HSG','MSN','VRE','MWG','FPT','SSI','VND','HCM','VCI','SHS','AGR','GAS','PLX','PVD','STB','EIB','TPB','OCB','LPB','VIB','SSB','VHC','KDH','NLG','DXG','PDR','DIG','HBC','CTD','IJC','SZC','PHR','GVR','BCM','SAB','MSB','HAG','BAF','QNS','DRC','DGW','SHB','NVB','IDC','PAN','NSC','VFG','BCC','NTP','CEO','TNG','VGC','BVS','MBS','VDS','NHH','BTS','SDT','VNR','BKG','S55','VC3','REE','PPC','POW','NT2','VSH','DGC','DPM','DCM','VOS','GMD','HAH','VSC','PVT']

def fetch_1h(sym):
        df_out = None
        try:
                    ts = int(datetime.now(VN_TZ).timestamp())
                    url = 'https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/bars-long-term?ticker=' + sym + '&type=stock&resolution=60&from=' + str(ts - 90*86400) + '&to=' + str(ts)
                    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                    if r.status_code == 200:
                                    data = r.json().get('data', [])
                                    if len(data) >= 60:
                                                        df = pd.DataFrame(data)
                                                        df.columns = [c.lower() for c in df.columns]
                                                        ren = {'o':'open','h':'high','l':'low','c':'close','v':'volume','t':'time','tradingdate':'time'}
                                                        df = df.rename(columns={k: v for k,v in ren.items() if k in df.columns})
                                                        if 'close' in df.columns:
                                                                                df['close'] = pd.to_numeric(df['close'], errors='coerce')
                                                                                df = df.dropna(subset=['close']).reset_index(drop=True)
                                                                                if len(df) >= 60:
                                                                                                            df_out = df
        except Exception as ex:
                    logger.warning(sym + ': ' + str(ex))
                return df_out

def calc(df):
        df = df.copy()
    c = df['close']
    df['rsi'] = ta.momentum.RSIIndicator(close=c, window=14).rsi()
    df['ema9'] = ta.trend.EMAIndicator(close=df['rsi'], window=9).ema_indicator()
    w = list(range(1, 46))
    ws = sum(w)
    df['wma45'] = df['rsi'].rolling(45).apply(lambda x: sum(a*b for a,b in zip(w,x))/ws, raw=True)
    return df.dropna()

def sig(df):
        out = None
    if len(df) >= 4:
                c = df.iloc[-1]
                if c['rsi'] > c['ema9'] and c['rsi'] > c['wma45']:
                                for lb in [2,3,4]:
                                                    p = df.iloc[-lb]
                                                    if p['rsi'] <= p['ema9'] or p['rsi'] <= p['wma45']:
                                                                            out = {'rsi': round(float(c['rsi']),2), 'ema9': round(float(c['ema9']),2), 'wma45': round(float(c['wma45']),2), 'close': round(float(c.get('close',0)),2)}
                                                                            break
                                                            return out

def scan():
        results = []
    delay = float(os.getenv('SCAN_DELAY_SECONDS','0.35'))
    logger.info('Scan ' + str(len(SYMS)) + ' ma...')
    for i, sym in enumerate(SYMS, 1):
                try:
                                df = fetch_1h(sym)
                                if df is not None:
                                                    df = calc(df)
                                                    s = sig(df)
                                                    if s is not None:
                                                                            s['symbol'] = sym
                                                                            results.append(s)
                                                                            logger.info('[HIT] ' + sym + ' RSI=' + str(s['rsi']))
                except Exception as ex:
                                logger.warning(sym + ': ' + str(ex))
                            if i % 20 == 0:
                                            logger.info(str(i) + '/' + str(len(SYMS)))
                                        time.sleep(delay)
    logger.info('Done: ' + str(len(results)) + ' signals')
    return results

async def send_tg(sigs):
        try:
                    tok = os.getenv('TELEGRAM_BOT_TOKEN','')
                    cid = os.getenv('TELEGRAM_CHAT_ID','')
                    if tok and cid:
                                    from telegram import Bot
                                    bot = Bot(tok)
                                    now = datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y')
                                    if not sigs:
                                                        msg = 'RSI scan ' + now + ': khong co tin hieu'
                    else:
                                        lines = ['RSI cat EMA9+WMA45 1H | ' + now + ' | ' + str(len(sigs)) + ' ma']
                                        for s in sigs[:25]:
                                                                lines.append(s['symbol'] + ' RSI=' + str(s['rsi']) + ' E9=' + str(s['ema9']) + ' W45=' + str(s['wma45']) + ' ' + str(s['close']))
                                                            msg = '\n'.join(lines)
                                    await bot.send_message(chat_id=cid, text=msg)
            logger.info('TG OK')
except Exception as ex:
        logger.error('TG: ' + str(ex))

def main():
        logger.info('=== RSI Scanner ' + datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y') + ' ===')
    sigs = scan()
    for s in sigs:
                logger.info(s['symbol'] + ' ' + str(s['rsi']) + ' ' + str(s['close']))
    asyncio.run(send_tg(sigs))
    logger.info('Done')

if __name__ == '__main__':
        main()
