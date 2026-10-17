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

## v0.1.2 validation-only data contract

`validation` is bounded to 100 days between configured start and end.
The default Phase B range is 2026-07-01 to 2026-09-30. Raw provider cache is
immutable, verified with SHA256 and reused by the existing cache adapter.
Signal dates are confined to the configured range; overfetch data are only
for constructing observed next-spot sessions and outcomes. Unknown 13:45
regular/05:00 afterhours labeling is still quarantined in raw QA.

For every VALID event, an independent QA pass recomputes the 13:45 day close
from its source start-labelled bar, the subsequent 05:00 night close from
its source start-labelled bar, checks the true YYYYMM futures contract, next
observed 0050 session and all three adjusted ETF prices, and recomputes all
four decomposition returns. Stored values must match within a fixed numerical
comparison tolerance (relative 1e-10, absolute 1e-12). Clock availability
checks do not infer additional market sessions. An excluded event must have
a documented reason; it is never a passed event. Coverage totals (nominal
300 regular, 840 afterhours) are *descriptive only*. Unsupported vendor
timestamp semantics continue to require explicit external validation.

Output artifacts include event price QA, daily coverage, monthly QA and
exclusion reason tables. QA status PASS/REVIEW_REQUIRED/BLOCKED is never
a finding about predictive ability, market impact or trading profitability.
No inferential statistics run in this mode. The original v0.1.1 pilot
and v0.1.0 formal hypotheses/returns remain unchanged.

## v0.1.3: expiry and boundary policy

The TXF monthly expiring contract's regular-session ending timestamp is 13:30,
represented by its 13:29 start-labelled one-minute bar; it has no
afterhours session. This is contract-dependent: non-expiring months trading
on the same date remain on the normal 13:45 clock. Explicit verified
2026 expiration pairs: 202607/2026-07-15, 202608/2026-08-19,
202609/2026-09-16. Unverified historical third-Wednesday dates are not
automatically assumed to be the official schedule.

For 13:45 regular / 05:00 afterhours boundary records, the default action
remains event exclusion with a detailed marker audit. Opt-in is permitted
only after independent documentation plus a strict zero-volume flat marker
equal to the last documented start-labelled closing candle of the same
YYYYMM contract. A different price/positive volume is never permitted.
Record warnings and source anomalies independently from signal validity.
All research formulas remain unchanged.

New tables: boundary_audit.csv, missing_minute_intervals.csv,
classification_comparison.csv. The latter reproduces the prior classification
rule INFERRED_FROM_V012_RULES_NOT_ARCHIVED_RUN; it is not the saved v0.1.2 output.
Nominal minute counts are 285 for verified expiring contracts' regular
session and 300 for other regular sessions, 840 for afterhours; nonobserved
labels are not proof of missing transactions. Never fill prices.
