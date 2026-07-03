from flask import Flask, render_template, jsonify
import requests
import json
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Pyth API configuration for SPY ETF
PYTH_HERMES_URL = "https://hermes.pyth.network/v2/updates/price/latest"
SPY_PYTH_FEED_ID = "19e09bb805456ada3979a7d1cbb4b6d63babc3a0f8e8a9509f68afa5c4c11cd5"

pyth_prior_close_cache = {
    "target_timestamp": None,
    "price": None
}

def get_pyth_prior_close():
    global pyth_prior_close_cache
    ny_tz = ZoneInfo("America/New_York")
    now_ny = datetime.now(ny_tz)
    
    # Target date is today at 16:00:00 NY time
    target_dt = datetime(now_ny.year, now_ny.month, now_ny.day, 16, 0, 0, tzinfo=ny_tz)
    
    if now_ny.weekday() in (5, 6): # Saturday or Sunday
        # Target Friday's close
        days_back = 1 if now_ny.weekday() == 5 else 2
        target_dt = target_dt - timedelta(days=days_back)
    else:
        if now_ny < target_dt:
            # Before 4:00 PM, target previous trading day's close
            days_back = 3 if now_ny.weekday() == 0 else 1
            target_dt = target_dt - timedelta(days=days_back)
            
    target_ts = int(target_dt.timestamp())
    
    if pyth_prior_close_cache["target_timestamp"] == target_ts and pyth_prior_close_cache["price"] is not None:
        return pyth_prior_close_cache["price"]
        
    url = f"https://benchmarks.pyth.network/v1/updates/price/{target_ts}"
    try:
        response = requests.get(url, params={"ids": SPY_PYTH_FEED_ID}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            parsed = data.get("parsed", [])
            if parsed:
                price_info = parsed[0]["price"]
                price = int(price_info["price"]) * (10 ** int(price_info["expo"]))
                pyth_prior_close_cache["target_timestamp"] = target_ts
                pyth_prior_close_cache["price"] = float(price)
                return float(price)
    except Exception as e:
        print(f"Error fetching Pyth prior close: {e}")
        
    return pyth_prior_close_cache["price"]

def fetch_pyth_live_spy():
    try:
        response = requests.get(PYTH_HERMES_URL, params={"ids[]": SPY_PYTH_FEED_ID}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            parsed = data.get("parsed", [])
            if parsed:
                price_info = parsed[0]["price"]
                price = int(price_info["price"]) * (10 ** int(price_info["expo"]))
                publish_time = price_info["publish_time"]
                return float(price), publish_time
    except Exception as e:
        print(f"Error fetching Pyth live price: {e}")
    return None, None


import os

HISTORY_FILE = "/data/spx_history.json"
if not os.path.exists("/data"):
    HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spx_history.json")

def save_spx_history(history):
    try:
        dir_name = os.path.dirname(HISTORY_FILE)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error saving history file: {e}")

def fetch_spx_history_from_yahoo():
    # Fetch daily chart for ^GSPC (S&P 500 Index) for the last 1 month
    url = "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC?interval=1d&range=1mo"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            result = data["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            indicators = result.get("indicators", {})
            quote = indicators.get("quote", [{}])[0]
            opens = quote.get("open", [])
            closes = quote.get("close", [])
            
            ny_tz = ZoneInfo("America/New_York")
            history = []
            
            # We need at least 2 days to compare open with prior close
            for i in range(1, len(timestamps)):
                prev_close = closes[i-1]
                curr_open = opens[i]
                curr_close = closes[i]
                ts = timestamps[i]
                dt = datetime.fromtimestamp(ts, ny_tz)
                
                if prev_close is not None and curr_open is not None:
                    open_diff = curr_open - prev_close
                    open_pct = (open_diff / prev_close) * 100
                    open_dir = "UP" if curr_open > prev_close else "DOWN" if curr_open < prev_close else "EQUAL"
                    
                    close_pct = 0.0
                    close_dir = "EQUAL"
                    if curr_close is not None:
                        close_diff = curr_close - prev_close
                        close_pct = (close_diff / prev_close) * 100
                        close_dir = "UP" if curr_close > prev_close else "DOWN" if curr_close < prev_close else "EQUAL"
                        
                    history.append({
                        "date": dt.strftime("%Y-%m-%d"),
                        "prior_close": float(prev_close),
                        "open": float(curr_open),
                        "close": float(curr_close) if curr_close is not None else None,
                        "open_dir": open_dir,
                        "open_pct": float(open_pct),
                        "close_dir": close_dir,
                        "close_pct": float(close_pct)
                    })
            
            history.sort(key=lambda x: x["date"], reverse=True)
            if history:
                latest_entry = history[0]
                ny_tz = ZoneInfo("America/New_York")
                now_ny = datetime.now(ny_tz)
                today_str = now_ny.strftime("%Y-%m-%d")
                if latest_entry["date"] == today_str and now_ny.hour < 16:
                    latest_entry["close"] = None
                    latest_entry["close_dir"] = "EQUAL"
                    latest_entry["close_pct"] = 0.0
            return history
    except Exception as e:
        print(f"Error fetching history from Yahoo: {e}")
    return []

def load_or_init_spx_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
                if history:
                    history.sort(key=lambda x: x["date"], reverse=True)
                    return history
        except Exception as e:
            print(f"Error loading history file: {e}")
            
    history = fetch_spx_history_from_yahoo()
    save_spx_history(history)
    return history

def send_telegram_message(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        # Silently fail if environment variables are not set
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("Telegram message sent successfully.")
            return True
        else:
            print(f"Failed to send Telegram message: {response.text}")
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
    return False

def update_today_in_history():
    spx_quote = data_cache["quotes"].get("SPX")
    if not spx_quote:
        return
        
    ny_tz = ZoneInfo("America/New_York")
    now_ny = datetime.now(ny_tz)
    today_str = now_ny.strftime("%Y-%m-%d")
    
    if now_ny.weekday() in (5, 6): # Weekend
        return
        
    prior_close = spx_quote.get("priorClose")
    open_price = spx_quote.get("openPrice")
    last_price = spx_quote.get("lastPrice")
    
    if prior_close is None:
        return
        
    history = data_cache["spx_history"]
    
    today_entry = None
    for entry in history:
        if entry["date"] == today_str:
            today_entry = entry
            break
            
    open_dir = "EQUAL"
    open_pct = 0.0
    if open_price is not None:
        open_dir = "UP" if open_price > prior_close else "DOWN" if open_price < prior_close else "EQUAL"
        open_pct = ((open_price - prior_close) / prior_close) * 100
        
    close_dir = "EQUAL"
    close_pct = 0.0
    close_price_to_save = None
    
    # Close price is only final after 16:00 (4:00 PM) NY time (which is 23:00 Turkey time)
    is_market_closed = now_ny.hour >= 16
    if is_market_closed and last_price is not None:
        close_price_to_save = last_price
        close_dir = "UP" if close_price_to_save > prior_close else "DOWN" if close_price_to_save < prior_close else "EQUAL"
        close_pct = ((close_price_to_save - prior_close) / prior_close) * 100
        
    if today_entry is None:
        today_entry = {
            "date": today_str,
            "prior_close": float(prior_close),
            "open": float(open_price) if open_price is not None else None,
            "close": float(close_price_to_save) if close_price_to_save is not None else None,
            "open_dir": open_dir,
            "open_pct": float(open_pct) if open_price is not None else 0.0,
            "close_dir": close_dir,
            "close_pct": float(close_pct) if close_price_to_save is not None else 0.0,
            "open_notified": False,
            "close_notified": False
        }
        history.insert(0, today_entry)
    else:
        if open_price is not None:
            today_entry["open"] = float(open_price)
            today_entry["open_dir"] = open_dir
            today_entry["open_pct"] = float(open_pct)
        else:
            today_entry["open"] = None
            
        today_entry["close"] = float(close_price_to_save) if close_price_to_save is not None else None
        today_entry["close_dir"] = close_dir
        today_entry["close_pct"] = float(close_pct)

    # Check and trigger Telegram Open Notification
    if today_entry.get("open") is not None and not today_entry.get("open_notified", False):
        open_diff = today_entry["open"] - today_entry["prior_close"]
        sign = "+" if open_diff >= 0 else ""
        direction = "UP 🟢" if today_entry["open"] > today_entry["prior_close"] else "DOWN 🔴" if today_entry["open"] < today_entry["prior_close"] else "EQUAL ⚪"
        msg = (
            f"🔔 *S&P 500 (SPX) Açılış Bildirimi*\n\n"
            f"📅 *Tarih:* `{today_str}`\n"
            f"💵 *Açılış Fiyatı:* `{today_entry['open']:,.2f}`\n"
            f"🔙 *Dünkü Kapanış:* `{today_entry['prior_close']:,.2f}`\n"
            f"📊 *Değişim:* `{sign}{open_diff:,.2f} ({sign}{today_entry['open_pct']:.2f}%)`\n"
            f"🎯 *Polymarket Yönü:* *{direction}*"
        )
        if send_telegram_message(msg):
            today_entry["open_notified"] = True

    # Check and trigger Telegram Close Notification
    if today_entry.get("close") is not None and not today_entry.get("close_notified", False):
        close_diff = today_entry["close"] - today_entry["prior_close"]
        sign = "+" if close_diff >= 0 else ""
        direction = "UP 🟢" if today_entry["close"] > today_entry["prior_close"] else "DOWN 🔴" if today_entry["close"] < today_entry["prior_close"] else "EQUAL ⚪"
        msg = (
            f"🔔 *S&P 500 (SPX) Kapanış Bildirimi*\n\n"
            f"📅 *Tarih:* `{today_str}`\n"
            f"💵 *Kapanış Fiyatı:* `{today_entry['close']:,.2f}`\n"
            f"🔙 *Önceki Kapanış:* `{today_entry['prior_close']:,.2f}`\n"
            f"📊 *Değişim:* `{sign}{close_diff:,.2f} ({sign}{today_entry['close_pct']:.2f}%)`\n"
            f"🎯 *Günlük Yön:* *{direction}*"
        )
        if send_telegram_message(msg):
            today_entry["close_notified"] = True
            
    if len(history) > 30:
        history = history[:30]
        data_cache["spx_history"] = history
        
    save_spx_history(history)


app = Flask(__name__)

# Cache structure to hold the latest WSJ quotes and historical data for charts
data_cache = {
    "quotes": {},
    "history": {
        "SPX": [],
        "ES00": [],
        "SPY": []
    },
    "history_1s": {
        "SPX": [],
        "ES00": [],
        "SPY": []
    },
    "spx_history": [],
    "last_updated": None
}

cache_lock = threading.Lock()

WSJ_URL = "https://www.wsj.com/market-data/stocks"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

es_close_cache = {
    "target_timestamp": None,
    "close_value": None
}

def get_cached_es_close():
    global es_close_cache
    ny_tz = ZoneInfo("America/New_York")
    now_ny = datetime.now(ny_tz)
    
    # Target date is today at 16:00:00 NY time
    target_dt = datetime(now_ny.year, now_ny.month, now_ny.day, 16, 0, 0, tzinfo=ny_tz)
    
    if now_ny.weekday() in (5, 6): # Saturday or Sunday
        # Target Friday
        days_back = 1 if now_ny.weekday() == 5 else 2
        target_dt = target_dt - timedelta(days=days_back)
    else:
        if now_ny < target_dt:
            # Before 4:00 PM, target previous trading day's close
            days_back = 3 if now_ny.weekday() == 0 else 1
            target_dt = target_dt - timedelta(days=days_back)
            
    target_ts = int(target_dt.timestamp())
    
    if es_close_cache["target_timestamp"] == target_ts and es_close_cache["close_value"] is not None:
        return es_close_cache["close_value"]
        
    url = "https://query1.finance.yahoo.com/v8/finance/chart/ES=F?interval=5m&range=5d"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        if response.status_code == 200:
            data = response.json()
            result = data["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            indicators = result.get("indicators", {})
            close_list = indicators.get("quote", [{}])[0].get("close", [])
            
            target_date_str = target_dt.strftime("%Y-%m-%d")
            for ts, close in reversed(list(zip(timestamps, close_list))):
                dt = datetime.fromtimestamp(ts, ny_tz)
                if dt.strftime("%Y-%m-%d") == target_date_str:
                    if dt.hour == 16 and dt.minute == 0 and close is not None:
                        es_close_cache["target_timestamp"] = target_ts
                        es_close_cache["close_value"] = float(close)
                        return float(close)
                    if dt.hour == 15 and dt.minute == 55 and close is not None:
                        es_close_cache["target_timestamp"] = target_ts
                        es_close_cache["close_value"] = float(close)
                        return float(close)
    except Exception as e:
        print(f"Error fetching historical ES close: {e}")
        
    return es_close_cache["close_value"]


TICKERS = {
    "SPX": {"symbol": "INDEX/US//SPX", "name": "S&P 500 Index"},
    "ES00": {"symbol": "FUTURE/US//S&P 500 FUTURES", "name": "S&P 500 Futures"},
    "SPY": {"symbol": "FUND/US//SPY", "name": "S&P 500 ETF"}
}

# Cache for daily data (open prices and 5m history) to avoid spamming Yahoo Finance
cached_daily_data = {"open_prices": {}, "history": {"SPX": [], "ES00": [], "SPY": []}}
last_daily_fetch_time = 0

def get_daily_data():
    """Fetches official today's open price and 5m intraday history from Yahoo Finance."""
    global cached_daily_data, last_daily_fetch_time
    now = time.time()
    
    # Determine the cache duration:
    # During market open (9:29 AM - 9:35 AM NY time) and market close (3:59 PM - 4:05 PM NY time),
    # refresh every 2 seconds to get the official open/close prices immediately.
    # Otherwise, refresh every 5 minutes (300 seconds) to avoid spamming Yahoo Finance.
    ny_tz = ZoneInfo("America/New_York")
    now_ny = datetime.now(ny_tz)
    is_market_open_window = (now_ny.hour == 9 and 29 <= now_ny.minute <= 35)
    is_market_close_window = (now_ny.hour == 15 and now_ny.minute >= 59) or (now_ny.hour == 16 and now_ny.minute <= 5)
    
    cache_duration = 2 if (is_market_open_window or is_market_close_window) else 300
    
    # Return cached data if fetched less than cache_duration ago
    if cached_daily_data["open_prices"] and (now - last_daily_fetch_time < cache_duration):
        return cached_daily_data
        
    yahoo_symbols = {"SPX": "^GSPC", "SPY": "SPY", "ES00": "ES=F"}
    open_prices = {}
    history = {"SPX": [], "ES00": [], "SPY": []}
    
    for ticker, symbol in yahoo_symbols.items():
        # Fall back to previous cached value if the new fetch fails
        if ticker in cached_daily_data["open_prices"]:
            open_prices[ticker] = cached_daily_data["open_prices"][ticker]
        if ticker in cached_daily_data["history"]:
            history[ticker] = cached_daily_data["history"][ticker]
            
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=1d"
            response = requests.get(url, headers=HEADERS, timeout=4)
            if response.status_code == 200:
                data = response.json()
                result = data["chart"]["result"][0]
                
                ny_date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
                timestamp_list = result.get("timestamp", [])
                
                if timestamp_list:
                    data_date = datetime.fromtimestamp(timestamp_list[0], ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
                    indicators = result.get("indicators", {})
                    quote = indicators.get("quote", [{}])[0]
                    
                    # Only grab today's open price if the data is from today
                    if data_date == ny_date:
                        open_list = quote.get("open", [])
                        if open_list and open_list[0] is not None:
                            open_prices[ticker] = float(open_list[0])
                            
                    # Always grab the chart history (if closed, it will show yesterday's chart)
                    close_list = quote.get("close", [])
                    ticker_hist = []
                    for ts, c in zip(timestamp_list, close_list):
                        if c is not None:
                            time_str = datetime.fromtimestamp(ts, ZoneInfo("America/New_York")).strftime("%H:%M:%S")
                            ticker_hist.append({"time": time_str, "price": float(c)})
                    history[ticker] = ticker_hist
        except Exception as e:
            print(f"Error fetching daily data for {ticker} from Yahoo: {e}")
            
    cached_daily_data = {"open_prices": open_prices, "history": history}
    last_daily_fetch_time = now
    return cached_daily_data

def fetch_wsj_data():
    """Fetches the latest quotes from WSJ MDC API and updates cache."""
    # Fetch open prices and history first
    daily_data = get_daily_data()
    open_prices = daily_data["open_prices"]
    history_data = daily_data["history"]
    
    # Pre-fetch Pyth live data for SPY to override WSJ response
    pyth_spy_price, pyth_pub_time = fetch_pyth_live_spy()
    pyth_spy_prior_close = get_pyth_prior_close()
    
    instruments = [{"symbol": val["symbol"], "name": val["name"]} for val in TICKERS.values()]
    params = {
        "id": json.dumps({
            "application": "WSJ",
            "instruments": instruments
        }),
        "type": "mdc_quotes"
    }
    
    try:
        response = requests.get(WSJ_URL, params=params, headers=HEADERS, timeout=8)
        if response.status_code == 200:
            raw_data = response.json()
            instruments_data = raw_data.get("data", {}).get("instruments", [])
            
            with cache_lock:
                timestamp_str = datetime.now().strftime("%H:%M:%S")
                data_cache["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                for inst in instruments_data:
                    ticker = inst.get("ticker")
                    last_price = float(inst.get("lastPrice", 0))
                    price_change = float(inst.get("priceChange", 0))
                    pct_change = float(inst.get("percentChange", 0))
                    high = float(inst.get("dailyHigh", 0))
                    low = float(inst.get("dailyLow", 0))
                    wsj_timestamp = inst.get("timestamp", "")
                    
                    ny_date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
                    
                    # If the timestamp from WSJ does not start with today's NY date,
                    # it means the asset has NOT started trading today (e.g. SPX in premarket)
                    if wsj_timestamp and not wsj_timestamp.startswith(ny_date):
                        # The market hasn't opened. lastPrice is our prior close.
                        prior_close = last_price
                        price_change = 0.0
                        pct_change = 0.0
                        open_price = None  # No open price yet
                    else:
                        prior_close = last_price - price_change
                        open_price = open_prices.get(ticker)
                    
                    wsj_prior_close = prior_close
                    
                    # If ticker is SPY, override with Pyth data to match Polymarket feed
                    if ticker == "SPY":
                        if pyth_spy_price is not None and pyth_spy_prior_close is not None:
                            last_price = pyth_spy_price
                            prior_close = pyth_spy_prior_close
                            price_change = last_price - prior_close
                            pct_change = (price_change / prior_close) * 100.0
                            
                            # Shift high, low, open prices by the Pyth-to-WSJ prior close offset
                            offset = prior_close - wsj_prior_close
                            high = high + offset
                            low = low + offset
                            if open_price is not None:
                                open_price = open_price + offset
                                
                            # Convert Pyth Unix publish time to WSJ ISO timestamp format
                            if pyth_pub_time:
                                pyth_dt = datetime.fromtimestamp(pyth_pub_time, ZoneInfo("America/New_York"))
                                formatted_ts = pyth_dt.strftime("%Y-%m-%dT%H:%M:%S") + pyth_dt.strftime("%z")
                                if len(formatted_ts) > 6 and (formatted_ts[-5] in ('+', '-')):
                                    formatted_ts = formatted_ts[:-2] + ":" + formatted_ts[-2:]
                                wsj_timestamp = formatted_ts
                    
                    # Store latest quote
                    data_cache["quotes"][ticker] = {
                        "name": inst.get("formattedName", inst.get("name")),
                        "ticker": ticker,
                        "lastPrice": last_price,
                        "priceChange": price_change,
                        "percentChange": pct_change,
                        "priorClose": prior_close,
                        "openPrice": open_price,
                        "dailyHigh": high,
                        "dailyLow": low,
                        "wsj_timestamp": wsj_timestamp
                    }
                    
                    # Maintain 1s history for the last 5 minutes (300 points)
                    history_1s_list = data_cache["history_1s"].setdefault(ticker, [])
                    wsj_time_str = ""
                    if "T" in wsj_timestamp:
                        wsj_time_str = wsj_timestamp.split("T")[1][:8]
                        
                    if wsj_time_str:
                        if not history_1s_list or wsj_timestamp > history_1s_list[-1].get("full_time", ""):
                            history_1s_list.append({
                                "time": wsj_time_str, 
                                "price": last_price,
                                "full_time": wsj_timestamp
                            })
                        if len(history_1s_list) > 300:
                            history_1s_list.pop(0)
                            
                    base_history = history_data.get(ticker, [])
                    
                    # Shift Yahoo historical points by prior close offset for SPY to prevent a chart jump
                    if ticker == "SPY" and pyth_spy_prior_close is not None and wsj_prior_close is not None:
                        offset = pyth_spy_prior_close - wsj_prior_close
                        base_history = [{"time": pt["time"], "price": pt["price"] + offset} for pt in base_history]
                        
                    if history_1s_list:
                        oldest_1s_time = history_1s_list[0]["time"]
                        filtered_base = [pt for pt in base_history if pt["time"] < oldest_1s_time]
                        data_cache["history"][ticker] = filtered_base + history_1s_list
                    else:
                        data_cache["history"][ticker] = base_history
                
                # Calculate S&P 500 expected open from ES00 Futures percentage move
                spx_quote = data_cache["quotes"].get("SPX")
                es_quote = data_cache["quotes"].get("ES00")
                if spx_quote and es_quote:
                    if spx_quote.get("openPrice") is None:
                        prior_close = spx_quote.get("priorClose")
                        current_es = es_quote.get("lastPrice")
                        if prior_close and current_es:
                            es_close_val = get_cached_es_close()
                            if es_close_val:
                                pct_change = (current_es - es_close_val) / es_close_val
                                spx_quote["expectedOpenPrice"] = prior_close * (1 + pct_change)
                            else:
                                spx_quote["expectedOpenPrice"] = None
                        else:
                            spx_quote["expectedOpenPrice"] = None
                    else:
                        spx_quote["expectedOpenPrice"] = None
                
                # Update SPX history file in the persistent volume
                update_today_in_history()
                        
            return True
    except Exception as e:
        print(f"Error fetching WSJ data: {e}")
    return False

def background_poller():
    """Background thread to poll WSJ every 1 second."""
    # Run once at startup
    fetch_wsj_data()
    while True:
        time.sleep(1)
        fetch_wsj_data()

# Initialize persistent SPX history
data_cache["spx_history"] = load_or_init_spx_history()

# Start background poller thread
poller_thread = threading.Thread(target=background_poller, daemon=True)
poller_thread.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    with cache_lock:
        return jsonify(data_cache)

@app.route('/api/force_refresh')
def force_refresh():
    success = fetch_wsj_data()
    with cache_lock:
        return jsonify({"success": success, "data": data_cache})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
