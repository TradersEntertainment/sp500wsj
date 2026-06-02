from flask import Flask, render_template, jsonify
import requests
import json
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

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
    "last_updated": None
}

cache_lock = threading.Lock()

WSJ_URL = "https://www.wsj.com/market-data/stocks"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

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
    
    # Return cached data if fetched less than 5 minutes ago
    if cached_daily_data["open_prices"] and (now - last_daily_fetch_time < 300):
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
                    if history_1s_list:
                        oldest_1s_time = history_1s_list[0]["time"]
                        filtered_base = [pt for pt in base_history if pt["time"] < oldest_1s_time]
                        data_cache["history"][ticker] = filtered_base + history_1s_list
                    else:
                        data_cache["history"][ticker] = base_history
                        
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
