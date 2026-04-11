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
# 🔐 SIGNATURE
# =========================

def generate_signature(method, path, body=""):
    timestamp = str(int(time.time()))
    message = timestamp + method + path + body
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature, timestamp


# =========================
# 📊 MARKET DATA
# =========================

def get_btc_price():
    return float(requests.get(f"{BASE_URL}/v2/tickers/BTCUSD").json()['result']['last_price'])


def get_products():
    return requests.get(f"{BASE_URL}/v2/products").json()['result']


def get_premium(symbol):
    return float(requests.get(f"{BASE_URL}/v2/tickers/{symbol}").json()['result']['last_price'])


# =========================
# 🎯 TODAY EXPIRY FILTER
# =========================

def get_today_options():
    products = get_products()
    today = datetime.datetime.utcnow().date()

    return [
        p for p in products
        if p['contract_type'] == 'option'
        and 'BTC' in p['symbol']
        and datetime.datetime.strptime(p['expiry_date'], "%Y-%m-%d").date() == today
    ]


# =========================
# 🎯 STRIKE LOGIC
# =========================

def find_strikes(spot):

    options = get_today_options()

    ce_list = [o for o in options if o['option_type'] == 'call']
    pe_list = [o for o in options if o['option_type'] == 'put']

    ce_target = spot * 1.02
    pe_target = spot * 0.98

    ce = min(ce_list, key=lambda x: abs(float(x['strike_price']) - ce_target))
    pe = min(pe_list, key=lambda x: abs(float(x['strike_price']) - pe_target))

    ce_symbol = ce['symbol']
    pe_symbol = pe['symbol']

    ce_price = get_premium(ce_symbol)
    pe_price = get_premium(pe_symbol)

    # 🔥 Premium balance
    attempts = 0
    while abs(ce_price - pe_price) > 8 and attempts < 5:

        if ce_price > pe_price:
            ce_target *= 1.01
        else:
            pe_target *= 0.99

        ce = min(ce_list, key=lambda x: abs(float(x['strike_price']) - ce_target))
        pe = min(pe_list, key=lambda x: abs(float(x['strike_price']) - pe_target))

        ce_symbol = ce['symbol']
        pe_symbol = pe['symbol']

        ce_price = get_premium(ce_symbol)
        pe_price = get_premium(pe_symbol)

        attempts += 1

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
    send_telegram("Bot started successfully ✅")
    global TRADE_DONE_DATE

    while True:
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
        today = now.date()

        if now.hour == 8 and now.minute == 15 and TRADE_DONE_DATE != today:

            try:
                spot = get_btc_price()

                ce, pe, ce_prem, pe_prem = find_strikes(spot)

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
                send_telegram(f"ERROR: {e}")

        time.sleep(10)


run_bot()
