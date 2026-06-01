from flask import Flask, render_template, jsonify
import requests
import json
import threading
import time
from datetime import datetime

app = Flask(__name__)

# Cache structure to hold the latest WSJ quotes and historical data for charts
data_cache = {
    "quotes": {},
    "history": {
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

def get_open_prices():
    """Fetches the official today's open price from Yahoo Finance API as fallback."""
    yahoo_symbols = {"SPX": "^GSPC", "SPY": "SPY", "ES00": "ES=F"}
    open_prices = {}
    for ticker, symbol in yahoo_symbols.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
            response = requests.get(url, headers=HEADERS, timeout=4)
            if response.status_code == 200:
                data = response.json()
                result = data["chart"]["result"][0]
                indicators = result.get("indicators", {})
                quote = indicators.get("quote", [{}])[0]
                open_list = quote.get("open", [])
                if open_list and open_list[0] is not None:
                    open_prices[ticker] = float(open_list[0])
        except Exception as e:
            print(f"Error fetching open price for {ticker} from Yahoo: {e}")
    return open_prices

def fetch_wsj_data():
    """Fetches the latest quotes from WSJ MDC API and updates cache."""
    # Fetch open prices first
    open_prices = get_open_prices()
    
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
                    
                    # Append to history (keep max 100 data points for live charts)
                    history_list = data_cache["history"][ticker]
                    history_list.append({
                        "time": timestamp_str,
                        "price": last_price
                    })
                    if len(history_list) > 100:
                        history_list.pop(0)
                        
            return True
    except Exception as e:
        print(f"Error fetching WSJ data: {e}")
    return False

def background_poller():
    """Background thread to poll WSJ every 10 seconds."""
    # Run once at startup
    fetch_wsj_data()
    while True:
        time.sleep(10)
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
