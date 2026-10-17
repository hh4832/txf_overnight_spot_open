# TXF Overnight → Next-Day Spot Open v0.1.4

研究框架，沒有下單功能。`FRAMEWORK_COMPLETE` 為無憑證測試通過後的框架交付狀態，非真實研究完成。`LIVE_DATA_VALIDATION_PENDING`。

H1：TXF 日盤收盤至當晚夜盤收盤報酬是否預測下一個現貨日的 0050 gap。
H2：夜盤資訊在開盤後是否仍有增量預測力；不顯著不等於證明完全反映。
H3：continuation / reversal 僅作事後描述，不把開盤 gap 當成開盤前訊號。

X = night/day − 1；Gap = next open/previous close − 1；Intraday = next close/next open − 1。
Total 使用乘法分解。主要模型只有 05:00 前資訊，另列 08:45 次要模型。

## 第一次 Colab 執行

1. 開啟 [Notebook](https://colab.research.google.com/github/hh4832/txf_overnight_spot_open/blob/main/notebooks/run_txf_overnight_spot_open.ipynb)。Private repo 需授權 GitHub。
2. Colab Secrets 加入 `GITHUB_TOKEN`（唯讀 clone 權限即可）；首次保留 `MODE='smoke'`。
3. Run All，依提示授權 Drive。以 metadata 驗證指定 Folder ID；不建立同名替代資料夾。
4. smoke 不需行情憑證。所有結果標記 `SYNTHETIC_SMOKE_ONLY`，不能判讀市場。
5. 真實 pilot：在 Secrets 設 `FINLAB_API_TOKEN`、`FUBON_PERSONAL_ID`、`FUBON_API_KEY`、`FUBON_CERT_PASSWORD`、`FUBON_CERT_PATH`；先將憑證上傳 Colab 暫存位置。不得放入 repo。
6. Colab 在 Drive 授權後自動檢查富邦 SDK >=2.4.0；缺少時按已確認的私有 Drive File ID 下載固定 wheel，核對大小、SHA256、Linux/Python 標籤再安裝。一般不必上傳或設定 `FUBON_WHEEL`，它只是安全的手動 override。
7. 設 `MODE='pilot'`，指定最多 14 天小範圍起迄，確認事件時間、合約及 coverage。
8. pilot 完成核對後才使用 `MODE='full'` 並設 `CONFIRM_FULL=True`，調整起迄；不會預設下載多年。

Drive 目標 ID：`1E9VkK_NgePZUidKu6ZqB2gceLnKy9kYx`。
Notebook 透過 Drive metadata 驗證 ID、寫入權限與 mount 路徑；cache 位於該已驗證資料夾，runs 透過 parent ID 上傳。
不推測 MyDrive 資料夾名稱。Shared Drive/捷徑/重名路徑目前不支援 cache mount，會明確停止。
重跑使用相同 cache 分區；不同 run 用 timestamp+SHA+唯一 suffix，不覆蓋。

## 本機／CI

Python 3.11 專用環境：
```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m src.pipeline --mode smoke
```
Windows 使用 `.venv/Scripts/python.exe`。Notebook 使用 Colab 現有 Python（>=3.11），CI 使用 3.11。
設定檔 `configs/research.yaml`。CLI 真實資料失敗會寫 FAILED 診斷並停止。
Notebook 在失敗時仍嘗試上傳該次診斷，絕不把前次成功結果作為本次結果。

## 輸出與限制

`cache/{fubon_txf,finlab_0050}` 與 `runs/YYYYMMDD_HHMMSS_<SHA>_<suffix>/` 分離。
run 含 config、raw_manifest（來源／參數／hash）、processed/event_dataset.parquet、tables、figures、reports/summary.md、summary.xlsx、diagnostics、run_info.json。
主要推論 HAC；robustness p-value 做 BH FDR。條件分組 CI 為描述性 t/Wilson，非序列相關穩健推論。
OOS 每次只使用更早日期訓練，與 expanding historical mean baseline 比較。
不足初始 252 日時 OOS 輸出為空，不能宣稱有效。無事前 equivalence margin，固定 EQUIVALENCE_NOT_TESTED。
研究判定保守為 DATA_INSUFFICIENT 或 INCONCLUSIVE，需人工整體審查後才可能 SUPPORTIVE / NOT_SUPPORTIVE。

反對者觀點：15 分鐘起點差、假日消息、換月、價格調整、歷史覆蓋與資料修訂可能影響結論。
這是單一現存 ETF 的研究，有 selection/survivorship 外推限制；未檢驗交易成本、滑價或流動性，不宣稱可獲利。
下一步：修改後再測，先完成真實 API pilot。詳細輸入契約與官方來源見 [docs/data_contract.md](docs/data_contract.md)。

`requirements-lock.txt` 記錄開發測試環境的精確套件版本；一般 Colab 安裝 requirements.txt，所有正式執行另存實際版本。

## v0.1.1 corrective: Pilot QA 與邊界分鐘 K

- Regular 08:45–13:44 與夜盤 15:00–隔日 04:59 依已驗證的 start-labelled 分鐘棒語義處理；13:45、05:00 的提供者紀錄**尚未確認語義**，只做 QA quarantine，不作為有效收盤價。
- 若異常影響設定的 signal date，整個事件標記 EXCLUDED，保留原因；僅屬額外 overfetch 區段者記入 `diagnostics/session_anomalies.csv`，不阻止有效 Pilot。原始快取絕不改動。
- `pilot` 真實資料管線成功且樣本太少時標記 `DATA_PIPELINE_VALIDATED` + `DATA_INSUFFICIENT`，不是研究假說有效證據。
- Failed runs 記錄 `error_stage`, `error_code`, `error_type`, `safe_error_message`, `data_provider`, `current_partition`；不儲存原始第三方 exception 訊息。
- 官方 Linux SDK 檔案位於私人 Drive，File ID `1zlSiNYhvhs82Pt6wB4nfSNCTco0UMzim`；固定 SHA256 `065c636ea58e00db9fe67aa6ba0936b234ac131da0d4697e9c6f33dbe42bc1ba`。需有該檔案讀取權限；若 wheel 更新，需人工重新審核並更新固定 hash。
- 重跑 2026-09-01 至 2026-09-07 pilot 前，請確保 Colab secrets 及憑證檔路徑在**當次 Runtime** 可用。真實資料尚待再次驗證：`LIVE_PILOT_REVALIDATION_PENDING`。

## v0.1.2 — Extended Validation Mode (Phase A audit / Phase B QA)

**Validation does not test H1, H2, H3, trading performance, statistical significance,
HAC, FDR or OOS.** It only audits market-data provenance, contract identities,
event timestamps, and reconstruction of individual returns.

Colab: [runner](https://colab.research.google.com/github/hh4832/txf_overnight_spot_open/blob/main/notebooks/run_txf_overnight_spot_open.ipynb).

Set `MODE='validation'`, leave `CONFIRM_FULL=False`. Recommended sequence:

- Phase A replay: `START='2026-09-01'`, `END='2026-09-07'`; compare five
  candidate events to immutable source candles and 0050 adjusted prices.
- Phase B bounded QA: `START='2026-07-01'`, `END='2026-09-30'` (92 calendar
  dates inclusive); do not run this until Phase A reports no price mismatches.
- Full history: still requires `MODE='full'` and explicit `CONFIRM_FULL=True`.
  It is a distinct formal research operation.

Validation spans at most `validation_max_calendar_days+1` dates (default
101 inclusive, since the guard limits end-minus-start to 100 days). The existing
pilot guard remains 14 calendar-day difference. Download extends 14 calendar
days after the requested end for verified next-day outcomes; cache partitions
keep their original keys and SHA256. The original raw parquet files are not
rewritten; a fresh timestamped run folder is created each time.

Output artifacts:

- `processed/event_dataset.parquet` with candidate-level exclusion reasons;
- `tables/event_price_audit.csv`: independent close timestamp, contract month,
  source price and price/return agreement against preserved provider records;
- `tables/daily_coverage.csv`: session minute counts, zero-volume bars, timing
  anomalies, weekend/holiday flags, exclusion reasons;
- `tables/monthly_qa.csv`: grouped candidate, valid, excluded, rollover,
  anomalies and nominal bar coverage;
- `tables/exclusion_reasons.csv`;
- `diagnostics/session_anomalies.csv` with in-range/out-of-range classification;
- `reports/data_quality_audit.md`, `reports/summary.md`, `reports/summary.xlsx`;
- `raw_manifest/manifest.json`, `run_info.json`.

QA states: `PASS` means all valid events were recomputed and no in-range
anomaly/exclusion occurred; `REVIEW_REQUIRED` means excluded events,
anomalies or no events require examination; `BLOCKED` means a valid event's
raw price, time, contract or return differs from its reconstructed record.
Never treat a review or blocked result as research acceptance. Normal minute
counts 300 regular / 840 overnight are **descriptive** rather than blanket
exchange-hours guarantees. The source candle start-labeling at 13:45 and
05:00 remains an unconfirmed vendor semantic assumption, not official evidence.

Python module caching in Colab matters: restart the runtime before a new
Git checkout, then Run All. The runner refuses stale imports instead of
quietly mixing previously loaded functions with a newly checked-out Git SHA.

The validation phase can be re-run without downloading identical cached
partitions. Real-data access still requires the user's authorized private
Fubon and FinLab credentials. Successful CI synthetic tests do not verify
2026-07-01..2026-09-30 live market coverage.

## v0.1.3 — Strict expiry and boundary classification correction

**No market hypothesis or return formula changed.** All old cache partitions,
research run folders, secrets and raw data remain untouched. Validation mode
is bounded to at most 100 calendar-day difference; formal `full` still requires
explicit confirmation.

Exchange-verified TXF **expiring-month** contracts end the last regular
session at 13:30 and have NO afterhours on expiry day. Explicitly reviewed
monthly expiries for this QA: 2026-07-15 (202607), 2026-08-19 (202608),
2026-09-16 (202609). The next month's futures contract can trade its
normal 13:45 regular session on that same date. **Never divide two different
contract months to produce the overnight signal.** A 13:29 close of
the expiring contract is recorded but classified
`EXPIRY_CONTRACT_ROLLOVER_EXCLUSION`, not a generic missing 13:44.

13:45 regular and 05:00 afterhours records are preserved in raw cache
and `session_anomalies.csv`. By default, their timestamp semantics are
**UNVERIFIED** and affected events remain excluded. An individually inspected
event may only be restored with a reviewed HTTPS document specified in
`boundary_evidence_reference`, `boundary_semantics_verified: true`,
and a zero-volume flat OHLC marker **identical to the verified
same-contract closing bar**. Any positive volume, conflicting OHLC,
contract mismatch or missing bar excludes the event regardless of
configuration. This mechanism does not independently prove vendor
timestamp semantics; review the evidence before opt-in. Recovered events
remain visible as warnings and result in `REVIEW_REQUIRED` QA.

New validation tables:

- `boundary_audit.csv`: original marker OHLC, volume, selected closing
  bar and difference, whether independently documented evidence was provided;
- `missing_minute_intervals.csv`: consecutive unobserved minute timestamps,
  duration, session, contract context and minutes to close; no price filling;
- `classification_comparison.csv`: per-signal status and exclusion
  compared to the *inferred v0.1.2 rule*. This is NOT an archived
  historical run and must not be confused with a bitwise replay.
- Existing daily/monthly audit reports now distinguish 285 expected
  regular minutes for the expiring contract versus usual 300.
  Missing timestamps do not establish whether the exchange had no
  trades or the provider omitted candles.

Run Phase B using an updated Colab Runtime, set:

```python
MODE = "validation"
START = "2026-07-01"
END = "2026-09-30"
CONFIRM_FULL = False
```

Official exchange contract specification:
https://www.taifex.com.tw/cht/2/tX?menuid1=12

Official monthly final settlements:
https://www.taifex.com.tw/cht/5/futIndxFSP

CI synthetic tests validate code behavior only. They do not replace a real
Colab validation or independently verify vendor timestamps.

## v0.1.4 — Phase C personal trading reference

**Objective:** summarize how TXF overnight changes historically correspond to
0050 next adjusted open-to-prior-close gap and next-open-to-close intraday
return. This is a personal information reference, **NOT** an execution signal,
trade backtest, estimated profitability, or predictive paper.

Price sourcing is unchanged for 0050: FinLab `etl:adj_open` and
`etl:adj_close`; raw price is used only to audit adjusted-price alignment.

TXF primary predictor uses a *predeclared adaptive close convention*:
use a valid positive-volume 13:45 regular bar, otherwise the exact 13:44
bar; use a valid 05:00 afterhours bar, otherwise the exact 04:59 bar
on the following calendar day. If an extra bar is malformed or conflicts
with the selected base-bar contract month, **exclude**, do not fall back.
Missing exact close is excluded (no 5-minute stale substitute).
This is a research convention and is not presented as independent
proof of Fubon's minute label semantics. Keep `close_policy: strict` to
reproduce prior quarantine handling. Fixed-price comparisons are descriptive
only, with no significance tests.

Contract months must match at both selected closes. Scheduled third
Wednesday TXF expiry is recognized from 2018 onward, including dates beyond
the three explicitly checked in 2026. **Other scheduled dates are not
independently verified official dates.** Review unusual holidays and supply
`expiry_date_overrides` keyed by YYYYMM when the exchange reschedules a
settlement. Contract mismatch always excludes regardless of calendar.

### Phase C run in Google Colab

Open `notebooks/run_txf_overnight_spot_open.ipynb`. Select a deliberate
real historical start/end range, use `MODE='full'`, `CONFIRM_FULL=True`,
`CLOSE_POLICY='adaptive'`. The previously verified Google Drive target
and encrypted secrets are unchanged. Fubon is fetched in 7-day partitions
and partition checksums are preserved for cache hits and retries. Long
histories require time and may hit vendor-history limits; provider failure is
fatal, not substituted with synthetic data. Do not schedule unapproved
historical full downloads.

Primary outputs in `tables/`: `trading_reference.csv` (six **predeclared**
night-move buckets; n, gap mean/median, positive/negative probability,
intraday mean/median and direction probabilities),
`trading_reference_by_year.csv`, `trading_reference_holdout.csv` (only
when >252 valid earlier observations exist),
`close_policy_comparison.csv`. `reports/summary.md` introduces these
results before the existing H1/H2 diagnostics. Bin-specific sample size
below ten is `SMALL_SAMPLE`; OOS with inadequate history is clearly
`NOT_EVALUATED_INSUFFICIENT_HISTORY`. Prior HAC and expanding OOS remain
available but are not claimed to demonstrate real-world trading value.

`validation` is restricted to QA with **no regression/OOS**. Raw anomalies
remain in diagnostics, including adaptive boundary prices actually chosen.
No look-ahead, synthetic fallback, cross-contract return, credential commit,
minute-forward-fill or rewriting of previous run outputs is allowed.

### FinLab 0050 historical gaps (v0.1.4 data-quality hotfix)

Some FinLab dates can have all four fields missing for 0050
(`etl:adj_open`, `etl:adj_close`, `price:開盤價`, `price:收盤價`).
When **all four** fields are NaN on the same day, preserve the source
date in the normalized cache as `fully_missing_0050=True`, then omit that
day from the usable spot trading-session calendar. Write the exact date
and ambiguity to `diagnostics/finlab_missing_dates.csv` and
`run_info.json` (count and date list). The missing date is **not**
affirmatively interpreted as an exchange holiday; if TXF trades that
day, its event remains explicitly excluded for missing spot prices.
If any field is missing *without* the other three missing, or if any
observed price is invalid or the adjustment factors disagree, **fail
closed**. No substitution, forward-fill, adjusted/raw mixing, changed
factor tolerance, or fabricated trading sessions is permitted.
This affects data-quality classification, not a trading result.

## Historical full-closure partition hotfix (v0.1.4)

**Reviewed TAIFEX closed interval:** 2019-02-04 through 2019-02-10.
TAIFEX official 2019-01-02 letter documents 2019-02-04 through 2019-02-08
Lunar New Year futures closure; February 9-10 are Saturday/Sunday:
https://www.taifex.com.tw/file/taifex/CHINESE/11/attach/%E5%85%AC%E5%91%8A%E6%9C%AC%E5%85%AC%E5%8F%B8%E6%9C%9F%E8%B2%A8%E9%9B%86%E4%B8%AD%E4%BA%A4%E6%98%93%E5%B8%82%E5%A0%B4108%E5%B9%B4%E8%BE%B2%E6%9B%86%E6%98%A5%E7%AF%80%E4%BC%91%E5%B8%82%E6%9A%A8%E7%9B%B8%E9%97%9C%E4%BA%8B%E5%AE%9C.pdf

Only a *partition completely contained* in a separately reviewed closed
interval may skip the Fubon API. A skipped partition is recorded in
`diagnostics/fubon_closed_partitions.csv`, `run_info.json`, and the raw
manifest as `SKIPPED_REVIEWED_FULL_CLOSURE` with 0 records, no file and no
fabricated SHA256. If any historical cache or observed 0050 sessions conflict
with the reviewed closure, the run fails for manual review. An unlisted empty
or failing provider response is **never** inferred to be an exchange holiday.
More reviewed exceptions must be added explicitly to
`src/market_calendar_exceptions.py` using independent official sources.

**Reviewed 0050 split suspension:** 2025-06-11 through 2025-06-17. The
Taiwan Stock Exchange reported trading suspension for the 4-for-1 split,
with trading resuming on 2025-06-18:
https://www.twse.com.tw/zh/ETFortune/announcement?company=A00005&date=20250617&fund=0050&seq=1&type=other

Fully missing daily 0050 observations in this date interval are labelled
`ETF_0050_VERIFIED_SPLIT_TRADING_SUSPENSION` in the existing
`diagnostics/finlab_missing_dates.csv` and `run_info.json`. Missing-date
observations are preserved in the source cache and excluded from 0050
events, never forward-filled. Dates outside approved intervals remain
`UNKNOWN_HOLIDAY_OR_PROVIDER_OMISSION`. Partial source NaNs, adjustment
factor mismatches and normal API failures still abort. Historical cashflows,
TXF adaptive close, research outcomes, and statistical settings are unchanged.

**Rerun:** Restart Colab runtime and Run All from GitHub `main`.
Confirmed successful 7-day partitions already in Drive cache are reused
without network requests, and old result run folders are not overwritten.
Further fully closed weeks in the historical range are not assumed; a new
unrecognized empty week will fail and must be verified independently.

## v0.1.4 Fubon duplicate candle hotfix

Confirmed example (2019-09-30..2019-10-06, afterhours): 4,155
provider rows, 3,318 distinct timestamps, 837 duplicated timestamps.
All duplicates observed in that sample had identical contract month and
OHLCV; the figures are **diagnostic observations, not strategy performance**.

Only records with identical normalized Asia/Taipei timestamp, session,
actual contract month, open, high, low, close, AND volume can be consolidated.
The first exact copy is retained. Any same-timestamp disagreement in
session, contract month or OHLCV raises an error and ends the live run.
Never use arbitrary keep-first/keep-last conflict resolution.

`src/fetch_fubon.py` applies exact-only deduplication after timestamp and
OHLCV validation and **before** immutable weekly partition caching.
`src/pipeline.py` checks exact overlaps again while merging all
weekly partitions; vendor query boundaries can include other weeks'
session bars. No provider query dates are silently shifted and no raw
bar time labels are modified.

Audit/provenance outputs:
- `diagnostics/fubon_partition_duplicate_audit.csv`: start/end,
  cache status, stored rows, known raw rows, within-fetch removals and
  timestamp-group count.
- `diagnostics/fubon_cross_partition_duplicate_audit.csv`:
  deduplication applied after all cached partitions are concatenated.
- `run_info.json`: known provider duplicate totals, number of old
  partitions without original dedup metadata, and merged overlap total.
- `raw_manifest/manifest.json` and existing checksum-protected cache
  metadata: source partition and duplicate audit, with hashes for
  cleaned partition data.

Older cached partitions are read unchanged; they may have zero
duplicates *after previous normalization* but their original provider
row counts were not recorded. Their within-fetch duplicates are
therefore marked `NOT_RECORDED_LEGACY_CACHE`, not assumed zero.
This hotfix does NOT alter predeclared research features, calendar,
closing-price convention, OOS rules or statistics. Restart Colab
runtime to load the latest `main` modules before another Run All.
