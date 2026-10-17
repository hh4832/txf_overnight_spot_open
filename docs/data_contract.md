# Provider contracts / verification (2026-10-17)

Official Fubon source: https://www.fbs.com.tw/TradeAPI/docs/market-data-future/http-api/historical/candles/
Read-only reference: hh4832/fubon_futures_intraday_data_validation/main, files
src/fubon_auth.py, src/fubon_client.py, src/normalize.py, docs/official_sources.md.
No files in that repository were changed.

Historical SDK >=2.4.0: sdk.marketdata.rest_client.futopt.historical.candles,
product=TXF, contractMonth=1!, timeframe=1, from/to, sort=asc, session=regular/afterhours.
Request windows are weekly (<1 year); from/to are provider trading dates.
Night bars use ISO-aware start timestamps and actual per-bar contractMonth, never the
response-level 1! alias. Actual session start is reconstructed from timestamp, NOT query date.
Regular bar start in [08:45,13:45); night in [15:00, next 05:00).
13:30 control uses close of the bar starting 13:29, hence known at 13:30.
08:45 secondary feature uses open of 08:45 bar, never its later close.
Default close staleness <=5 minutes is a predeclared data-quality policy; no fill.
Expiration early closes fail this regular-close requirement and are excluded.
Contract equality is necessary; within-session changes are excluded by validation.
Friday night ends Saturday and pairs with next *observed validated* spot session.
Every missing 0050 adjusted price is fatal; prices are not dropna'd into a fake calendar.
Future spot dates supply outcome/session calendar only, never predictor thresholds.
Boundary data include 14 calendar days beyond end; missing next day remains excluded.
Weekday gaps flag known spot-session gaps, not specific unverified holiday/event causes.

FinLab data.get: etl:adj_open / etl:adj_close, plus price:開盤價 / price:收盤價
for adjustment-factor consistency. Strict finite positive 0050 prices and matching DatetimeIndex.
Cross-day changes in factors mark corporate-action boundaries, without invented event labels.
Provider runtime behavior, history completeness, raw/adjusted precision and live calendar
coverage require credentialed pilot validation. Official FinLab: https://doc.finlab.tw/

Failure: empty/schema/404/429/auth errors stop and produce sanitized failure artifacts;
no fallback to synthetic data, no arbitrary SDK exception content. Cache hits are hash checked.
Cache partition keys include date range, provider and parameter identity; successful cache
is immutable. To revalidate revised vendor history use a new cache root, preserve old cache.
Primary analysis rejects unknown contracts and adjustment factors; no back-adjusted futures.

## v0.1.1 boundary QA clarification

The source provider delivered a regular-session record labelled 2026-09-15
13:45 Asia/Taipei. Its start/end candle semantics remain unverified. The
primary 13:45 close therefore still uses the final verified 13:44 start-labelled
one-minute bar; 13:45 is quarantined and, if within the configured signal
window, the entire event is excluded. The same conservative policy applies to
05:00 boundary records. This is NOT confirmation of a new official session end.

Raw 14-day overfetch is retained without alteration; anomalies outside the
requested signal dates are recorded in session_anomalies.csv but do not block
unaffected events. Structural anomalies inside a signal event cause exclusion.
This correction is pending revalidation on real historical data.
