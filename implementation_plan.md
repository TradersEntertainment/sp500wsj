# Plan - Integrate Pyth Network API for SPY ETF Data

We will modify the Flask backend to fetch SPY ETF data (current price and prior close) directly from Pyth Network instead of Wall Street Journal (WSJ). This ensures our app's data aligns perfectly with Polymarket's resolution sources.

## Proposed Changes

### [app.py](file:///C:/Users/omery/.gemini/antigravity/brain/48b4514c-c66d-49d0-84b7-bf8fea6745b5/sp500wsj/app.py)

1. **Add Pyth configuration constants**:
   - `PYTH_HERMES_URL = "https://hermes.pyth.network/v2/updates/price/latest"`
   - `PYTH_BENCHMARKS_URL = "https://benchmarks.pyth.network/v1/updates/price"`
   - `SPY_PYTH_FEED_ID = "19e09bb805456ada3979a7d1cbb4b6d63babc3a0f8e8a9509f68afa5c4c11cd5"`

2. **Add a caching helper for Pyth Prior Close**:
   - A function `get_cached_pyth_prior_close()` that returns the cached prior close.
   - It will fetch the closing price of the previous trading day at 16:00:00 NY Time from `benchmarks.pyth.network`.
   - The result will be cached and updated only when the date shifts or at startup.

3. **Modify `fetch_wsj_data()`**:
   - Retrieve SPX and ES00 from WSJ as usual.
   - Query Pyth Hermes API for SPY's latest price.
   - Merge the Pyth SPY price into `data_cache["quotes"]["SPY"]`.
   - Use the cached Pyth prior close for SPY's `priorClose`.
   - Update SPY's `priceChange` and `percentChange` relative to this Pyth prior close.
   - Maintain the 1-second history buffers for SPY using the Pyth price updates.

## Verification Plan

### Automated Tests
- Run a verification script to query both Pyth Hermes (latest) and Pyth Benchmarks (historical prior close) and print results to confirm they match.

### Manual Verification
- Deploy/run the server locally.
- Check the console logs and `/api/data` JSON output to verify SPY data is fetched from Pyth, and the prior close matches the expected Pyth close price ($758.36 for June 1st).
