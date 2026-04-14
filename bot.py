import requests
import time
import datetime
import hashlib
import hmac
import json
import os

# =========================
# 🔐 CONFIG FROM ENV
# =========================

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

BASE_URL = "https://api.delta.exchange"

LOT_SIZE = 10
TRADE_DONE_DATE = None

LAST_ERROR_TIME = 0  # prevent spam


# =========================
# 📲 TELEGRAM
# =========================

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass


def send_error(msg):
    global LAST_ERROR_TIME
    now = time.time()

    # send error only once every 60 sec
    if now - LAST_ERROR_TIME > 60:
        send_telegram(msg)
        LAST_ERROR_TIME = now


# =========================
# 🔐 SIGNATURE
# =========================

def generate_signature(method, path, body=""):
    timestamp = str(int(time.time()))
    message = timestamp + method + path + body
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature, timestamp


# =========================
# 📊 BTC PRICE (FIXED)
# =========================

def get_btc_price():
    try:
        res = requests.get(f"{BASE_URL}/v2/tickers/BTCUSD", timeout=5)

        if res.status_code != 200:
            send_error(f"❌ HTTP Error: {res.status_code}")
            return None

        data = res.json()

        # safe extraction
        if 'result' in data and data['result']:
            price = data['result'].get('last_price')
            if price:
                return float(price)

        send_error("❌ BTC price missing in response")
        return None

    except Exception as e:
        send_error(f"❌ BTC fetch error: {e}")
        return None


# =========================
# 📦 PRODUCTS
# =========================

def get_products():
    try:
        res = requests.get(f"{BASE_URL}/v2/products", timeout=5)
        return res.json().get('result', [])
    except:
        return []


def get_premium(symbol):
    try:
        res = requests.get(f"{BASE_URL}/v2/tickers/{symbol}", timeout=5).json()
        if res and res.get('result'):
            return float(res['result']['last_price'])
    except:
        return None
    return None


# =========================
# 🎯 TODAY OPTIONS
# =========================

def get_today_options():
    products = get_products()
    today = datetime.datetime.utcnow().date()

    return [
        p for p in products
        if p.get('contract_type') == 'option'
        and 'BTC' in p.get('symbol', '')
        and p.get('expiry_date')
        and datetime.datetime.strptime(p['expiry_date'], "%Y-%m-%d").date() == today
    ]


# =========================
# 🎯 STRIKE LOGIC
# =========================

def find_strikes(spot):

    options = get_today_options()

    if not options:
        send_error("❌ No options found")
        return None, None, None, None

    ce_list = [o for o in options if o.get('option_type') == 'call']
    pe_list = [o for o in options if o.get('option_type') == 'put']

    if not ce_list or not pe_list:
        send_error("❌ CE/PE not found")
        return None, None, None, None

    ce_target = spot * 1.02
    pe_target = spot * 0.98

    ce = min(ce_list, key=lambda x: abs(float(x['strike_price']) - ce_target))
    pe = min(pe_list, key=lambda x: abs(float(x['strike_price']) - pe_target))

    ce_symbol = ce['symbol']
    pe_symbol = pe['symbol']

    ce_price = get_premium(ce_symbol)
    pe_price = get_premium(pe_symbol)

    if ce_price is None or pe_price is None:
        send_error("❌ Premium fetch failed")
        return None, None, None, None

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
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)

        ce_price = get_premium(ce)
        pe_price = get_premium(pe)

        if ce_price is None or pe_price is None:
            time.sleep(5)
            continue

        # SL
        if ce_price >= ce_sl or pe_price >= pe_sl:
            send_telegram("SL HIT → EXIT BOTH")
            place_order(ce, "buy")
            place_order(pe, "buy")
            break

        # TIME EXIT
        if now.hour == 17 and now.minute == 15:
            send_telegram("TIME EXIT")
            place_order(ce, "buy")
            place_order(pe, "buy")
            break

        time.sleep(5)


# =========================
# 🤖 MAIN
# =========================

def run_bot():

    global TRADE_DONE_DATE

    while True:
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
        today = now.date()

        if True and TRADE_DONE_DATE != today:
    send_telegram("⏰ Entry condition triggered")

            spot = get_btc_price()

            if spot is None:
                time.sleep(10)
                continue

            ce, pe, ce_prem, pe_prem = find_strikes(spot)

            if not ce or not pe:
                time.sleep(10)
                continue

            try:
                ce_sl = ce_prem * 5
                pe_sl = pe_prem * 5

                send_telegram(
                    f"ENTRY\nSPOT:{spot}\nCE:{ce}@{ce_prem}\nPE:{pe}@{pe_prem}"
                )

                place_order(ce, "sell")
                place_order(pe, "sell")

                TRADE_DONE_DATE = today

                monitor(ce, pe, ce_sl, pe_sl)

            except Exception as e:
                send_error(f"ERROR: {e}")

        time.sleep(10)


# =========================
# 🚀 START
# =========================

run_bot()
