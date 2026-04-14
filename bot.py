import requests
import time
import datetime
import hashlib
import hmac
import json
import os

# =========================
# 🔐 CONFIG
# =========================

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

BASE_URL = "https://api.delta.exchange"

LOT_SIZE = 10
TRADE_DONE_DATE = None
ENTRY_TRIGGERED = False


# =========================
# 📲 TELEGRAM
# =========================

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass


# =========================
# 🌐 GET SERVER IP (IMPORTANT)
# =========================

def get_server_ip():
    try:
        ip = requests.get("https://api.ipify.org").text
        send_telegram(f"🌐 SERVER IP: {ip}")
    except:
        send_telegram("❌ Unable to fetch server IP")


# =========================
# 🔐 SIGNATURE
# =========================

def generate_signature(method, path, body=""):
    timestamp = str(int(time.time()))
    message = timestamp + method + path + body
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature, timestamp


# =========================
# 📊 BTC PRICE
# =========================

def get_btc_price():
    try:
        res = requests.get(f"{BASE_URL}/v2/tickers/BTCUSD").json()

        if res and res.get("result"):
            return float(res["result"]["last_price"])

    except Exception as e:
        send_telegram(f"BTC fetch error: {e}")

    return None


# =========================
# 📊 PRODUCTS
# =========================

def get_products():
    try:
        res = requests.get(f"{BASE_URL}/v2/products").json()
        return res.get("result", [])
    except:
        return []


def get_premium(symbol):
    try:
        res = requests.get(f"{BASE_URL}/v2/tickers/{symbol}").json()
        if res and res.get("result"):
            return float(res["result"]["last_price"])
    except:
        pass
    return None


# =========================
# 🎯 STRIKE SELECTION
# =========================

def find_strikes(spot):

    options = get_products()

    ce_list = [o for o in options if o.get('option_type') == 'call' and 'BTC' in o.get('symbol', '')]
    pe_list = [o for o in options if o.get('option_type') == 'put' and 'BTC' in o.get('symbol', '')]

    if not ce_list or not pe_list:
        return None, None, None, None

    ce = min(ce_list, key=lambda x: abs(float(x['strike_price']) - spot))
    pe = min(pe_list, key=lambda x: abs(float(x['strike_price']) - spot))

    ce_symbol = ce['symbol']
    pe_symbol = pe['symbol']

    ce_price = get_premium(ce_symbol)
    pe_price = get_premium(pe_symbol)

    return ce_symbol, pe_symbol, ce_price, pe_price


# =========================
# 📤 ORDER
# =========================

def place_order(symbol, side):

    path = "/v2/orders"
    url = BASE_URL + path

    payload = {
        "product_id": symbol,
        "size": LOT_SIZE,
        "side": side,
        "order_type": "market"
    }

    body = json.dumps(payload)

    signature, timestamp = generate_signature("POST", path, body)

    headers = {
        "api-key": API_KEY,
        "timestamp": timestamp,
        "signature": signature,
        "Content-Type": "application/json"
    }

    res = requests.post(url, headers=headers, data=body)

    send_telegram(f"{side.upper()} {symbol}")

    return res.json()


# =========================
# 📡 MONITOR
# =========================

def monitor(ce, pe, ce_sl, pe_sl):

    while True:

        ce_price = get_premium(ce)
        pe_price = get_premium(pe)

        now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)

        if ce_price is None or pe_price is None:
            time.sleep(5)
            continue

        # SL
        if ce_price >= ce_sl or pe_price >= pe_sl:
            send_telegram("❌ SL HIT → EXIT")
            place_order(ce, "buy")
            place_order(pe, "buy")
            break

        # TIME EXIT
        if now.hour == 17 and now.minute >= 15:
            send_telegram("⏰ TIME EXIT")
            place_order(ce, "buy")
            place_order(pe, "buy")
            break

        time.sleep(5)


# =========================
# 🤖 MAIN BOT
# =========================

def run_bot():

    global TRADE_DONE_DATE, ENTRY_TRIGGERED

    while True:

        now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
        today = now.date()

        # Reset daily
        if TRADE_DONE_DATE != today:
            ENTRY_TRIGGERED = False

        # ENTRY TIME
        if now.hour == 8 and now.minute == 15 and not ENTRY_TRIGGERED:

            ENTRY_TRIGGERED = True

            send_telegram("⏰ Entry condition triggered")

            spot = get_btc_price()

            if spot is None:
                send_telegram("❌ BTC price fetch failed")
                time.sleep(60)
                continue

            ce, pe, ce_prem, pe_prem = find_strikes(spot)

            if not ce or not pe or not ce_prem or not pe_prem:
                send_telegram("❌ Strike selection failed")
                time.sleep(60)
                continue

            ce_sl = ce_prem * 5
            pe_sl = pe_prem * 5

            send_telegram(
                f"ENTRY\nSPOT:{spot}\nCE:{ce}@{ce_prem}\nPE:{pe}@{pe_prem}"
            )

            place_order(ce, "sell")
            place_order(pe, "sell")

            TRADE_DONE_DATE = today

            monitor(ce, pe, ce_sl, pe_sl)

        time.sleep(5)


# =========================
# 🚀 START
# =========================

if __name__ == "__main__":
    send_telegram("🤖 Bot Started")

    # 🔥 IMPORTANT → get Railway IP
    get_server_ip()

    run_bot()
