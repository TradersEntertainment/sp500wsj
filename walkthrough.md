# Walkthrough - Pyth Network Integration for SPY ETF

We have successfully transitioned the SPY ETF price data source from the Wall Street Journal (WSJ) to **Pyth Network** to align the application data with Polymarket's data and resolution rules.

## Changes Made

### Backend Updates

1. **New Pyth API Helpers in [app.py](file:///C:/Users/omery/.gemini/antigravity/brain/48b4514c-c66d-49d0-84b7-bf8fea6745b5/sp500wsj/app.py)**:
   - Added `get_pyth_prior_close()` to fetch the closing price of SPY from the previous trading day at 16:00:00 NY time using the Pyth Benchmarks API. Included a caching mechanism to avoid rate limits.
   - Added `fetch_pyth_live_spy()` to poll the latest SPY price from the Pyth Hermes API.

2. **WSJ Quote Override & Data Integration**:
   - Modified `fetch_wsj_data()` to poll Pyth for SPY live prices and prior close.
   - Overwrote SPY's `lastPrice`, `priorClose`, `priceChange`, and `percentChange` with Pyth values.
   - Adjusted `dailyHigh`, `dailyLow`, and `openPrice` using the Pyth-to-WSJ prior close offset to ensure consistency.
   - Formatted Pyth's Unix publish timestamp to match the WSJ ISO string format.
   - Applied the offset to Yahoo Finance 5-minute historical bars for SPY to ensure a seamless chart visual without gaps or sudden jumps.

## Verification & Testing Results

- Ran `test_pyth_integration.py` to confirm successful connections and calculations for both historical Benchmarks API and live Hermes API.
- Executed `test_app_poll.py` to simulate the background polling process. The cached SPY quote structure updated correctly:
  - **Live Price**: `759.47408` (from Pyth)
  - **Prior Close**: `759.53000` (from Pyth)
  - **Daily High, Low, and Open**: Offset correctly applied to keep everything relative.
  - **ISO Timestamp**: Correctly formatted as `2026-06-02T16:00:20-04:00`.
  - **Historical points**: Historical 5m bars shifted by the offset, seamlessly ending at the live ticking value.
