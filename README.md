# TXF Overnight → Next-Day Spot Open v0.1.1

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
