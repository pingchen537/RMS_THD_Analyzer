# RMS / THD Analyzer for Audio Precision CSV

將 Audio Precision（AP）匯出的多區塊 CSV，整理成可直接分析的 RMS Level、THD 或 THD+N 數值表，並輸出個別 DUT 曲線與多台 DUT 疊圖。

本工具適合麥克風、喇叭與 IPCam 聲學量測資料整理。程式只解析 AP 已計算完成的數值，不會從 waveform 重新計算 RMS、THD 或 THD+N。

## 主要功能

- 解析 AP 重複區塊格式的 `RMS Level`、`THD Ratio` 與 `THD+N`。
- 量測標題比對不區分大小寫。
- RMS 單位會從輸入檔讀取，例如 `dBSPL` 或 `dBFS`。
- THD／THD+N 必須使用 `%`；若為 dB，程式會停止並提示，不會錯誤標示成百分比。
- 同一個輸入檔不可混用 THD 與 THD+N。
- 支援不同頻點數量，沒有寫死 81 點。
- 輸出寬表、整合長表、各 DUT CSV、個別圖與比較圖。
- 可用 DUT 編號或完整名稱選擇比較曲線。
- 支援 `--compare-only` 與連續比較的 `--interactive`。
- 每次執行都建立全新輸出資料夾，避免覆蓋舊結果。
- 中文或特殊字元 DUT 名稱會產生安全且不重複的檔名。
- 可設定 USL／LSL、頻率範圍、Y 軸、格線、字體與線寬。
- AP 若將部分曲線命名為 `Ch1`，可依 RMS／失真區塊順序自動配對 DUT 名稱。

## Repository 結構

```text
RMS_THD_Analyzer/
├─ RMS_THD_Analyzer.py
├─ README.md
├─ requirements.txt
├─ .gitignore
├─ sample_data/
│  └─ RMS_THD_sample.csv
└─ tests/
   └─ test_rms_thd_analyzer.py
```

## 執行環境

- Python 3.10 或以上版本
- matplotlib 3.7 或以上版本
- Windows、macOS 或 Linux

安裝套件：

```bash
python -m pip install -r requirements.txt
```

## 快速開始

Clone 或下載 repository 後，在專案根目錄執行 Demo：

```bash
python RMS_THD_Analyzer.py "sample_data/RMS_THD_sample.csv" -o rms_thd_output
```

程式會建立新的時間標籤資料夾，例如：

```text
rms_thd_output_2608251747010
```

時間格式為 `YYMMDDHHMMSS + 1 位小數秒`。執行時會顯示實際輸出位置與偵測到的量測格式：

```text
全新輸出資料夾：D:\Project\rms_thd_output_2608251747010
量測格式：RMS (dBSPL) / THD (%)
```

Windows 路徑含空格時，請用雙引號包住完整路徑：

```powershell
python "D:\Tools\RMS_THD_Analyzer.py" `
  "D:\Project\Acoustic Test\RMS_THD.csv" `
  -o "D:\Project\Acoustic Test\rms_thd_output"
```

查看全部參數：

```bash
python RMS_THD_Analyzer.py --help
```

## 常用指令

### 查看 DUT 編號

不建立輸出資料夾：

```bash
python RMS_THD_Analyzer.py "sample_data/RMS_THD_sample.csv" --list-duts
```

### 指定比較圖 DUT

DUT 編號可用空格、逗號或分號分隔：

```bash
python RMS_THD_Analyzer.py "sample_data/RMS_THD_sample.csv" \
  --rms-compare-duts 1 2 3 \
  --thd-compare-duts 1,3
```

也可輸入完整 DUT 名稱：

```bash
python RMS_THD_Analyzer.py "sample_data/RMS_THD_sample.csv" \
  --rms-compare-duts DUT_WA001 DUT_WA002 \
  --thd-compare-duts DUT_WA001 DUT_WA002
```

`--thd-compare-duts` 也用於 THD+N，保留此名稱是為了相容舊版指令。

### 只建立比較圖

```bash
python RMS_THD_Analyzer.py "sample_data/RMS_THD_sample.csv" \
  -o rms_thd_compare \
  --compare-only \
  --rms-compare-duts 1,2,3 \
  --thd-compare-duts 1,2,3
```

`--compare-only` 仍會建立全新資料夾，不會修改先前的比較圖。

### 互動模式

```bash
python RMS_THD_Analyzer.py "sample_data/RMS_THD_sample.csv" \
  -o rms_thd_output --interactive
```

互動命令：

```text
compare> rms 1 2 3
compare> thd 1,3
compare> both 2 3
compare> rms all
compare> list
compare> help
compare> quit
```

產生的比較圖會自動使用 `_001`、`_002`……流水號。

### 關閉時間標籤

```bash
python RMS_THD_Analyzer.py "sample_data/RMS_THD_sample.csv" \
  -o rms_thd_output --no-timestamp
```

如果 `rms_thd_output` 已存在，程式會建立 `rms_thd_output_001`，仍不會覆蓋原資料夾。

## 可調整設定

常用設定集中在 `RMS_THD_Analyzer.py` 最上方的「1. 使用者設定」。

| 設定 | 單位／選項 | 用途 |
|---|---|---|
| `RMS_USL`、`RMS_LSL` | 與輸入 RMS 相同或 `None` | RMS 固定上下限 |
| `THD_USL`、`THD_LSL` | % 或 `None` | THD／THD+N 固定上下限 |
| `FREQUENCY_RANGE_HZ` | Hz | 圖形與 CSV 輸出頻率範圍 |
| `RMS_Y_RANGE` | 與輸入 RMS 相同或 `None` | RMS 圖 Y 軸範圍 |
| `RMS_Y_GRID_INTERVAL` | RMS 單位或 `None` | RMS 水平格線間距 |
| `THD_Y_RANGE` | % 或 `None` | THD／THD+N 圖 Y 軸範圍 |
| `THD_Y_SCALE` | `"log"`／`"linear"` | 失真圖使用對數軸或線性軸 |
| `FONT_SIZE` | pt | 圖中文字大小 |
| `LINE_WIDTH` | pt | DUT 曲線粗細 |
| `LIMIT_LINE_WIDTH` | pt | USL／LSL 線條粗細 |
| `FIGURE_SIZE` | inch | 圖片尺寸 |
| `IMAGE_DPI` | dpi | 圖片解析度 |
| `RMS_COMPARE_DUTS` | 編號、名稱或 `None` | RMS 預設比較曲線 |
| `THD_COMPARE_DUTS` | 編號、名稱或 `None` | THD／THD+N 預設比較曲線 |
| `ADD_OUTPUT_TIMESTAMP` | `True`／`False` | 是否加入輸出時間標籤 |

例如 RMS 圖顯示 50～60，且每 2 單位一條水平格線：

```python
RMS_Y_RANGE = (50.0, 60.0)
RMS_Y_GRID_INTERVAL = 2.0
```

## 輸入 CSV 規則

程式預期輸入為 AP 匯出的重複量測區塊。每個區塊需包含：

1. `RMS Level`、`THD Ratio` 或 `THD+N` 標題。
2. DUT 名稱。
3. 頻率及單位列，例如 `Hz,dBSPL` 或 `Hz,%`。
4. 連續的數值資料列。

簡化範例：

```csv
THD Ratio -> Specify Data Points
DUT_A
Hz,%
100,1.20
1000,0.45

RMS Level -> Specify Data Points
DUT_A
Hz,dBSPL
100,52.4
1000,58.1
```

限制：

- 同一份 CSV 的所有 RMS 區塊必須使用相同單位。
- 失真區塊必須全部是 THD，或全部是 THD+N，不可混用。
- THD／THD+N 目前只接受 `%`，不會自動把 dB 轉成百分比。
- `FREQUENCY_RANGE_HZ` 內若沒有資料，程式會停止並顯示 DUT 名稱。

## 輸出內容

THD 輸入會產生 `thd_values.csv` 與 `THD_Comparison.png`；THD+N 輸入則會產生 `thd_n_values.csv` 與 `THD_N_Comparison.png`。

```text
rms_thd_output_<timestamp>/
├─ rms_level_values.csv
├─ thd_values.csv              # THD+N 時為 thd_n_values.csv
├─ rms_thd_all_values.csv
├─ run_notes.txt
├─ data_by_dut/
│  └─ <DUT>.csv
└─ plots/
   ├─ individual/
   │  ├─ <DUT>_RMS_Level.png
   │  └─ <DUT>_THD.png
   └─ comparison/
      ├─ RMS_Level_Comparison.png
      └─ THD_Comparison.png
```

CSV 使用 UTF-8 with BOM，方便 Microsoft Excel 直接開啟中文內容。

目前預設 USL／LSL 都是 `None`，因此 Demo 的結果欄會顯示 `NOT_SET`：

```csv
Frequency_Hz,DUT_WA001_RMS_Level_dBSPL,DUT_WA001_THD_Percent,RMS_Result,THD_Result
100,66.65530625,35.60145315,NOT_SET,NOT_SET
```

設定至少一個上下限後，結果才會顯示 `PASS`、`FAIL_LSL` 或 `FAIL_USL`。

## DUT 名稱與檔名

輸出檔名會保留可用的中文與 Unicode 字元，並替換 Windows 不允許的符號。若不同 DUT 經清理後得到相同檔名，程式會自動追加 `_002`、`_003`……，避免同一輪輸出內互相覆蓋。

AP 若將 RMS 曲線命名為 `Ch1`，程式可以在 RMS 與失真區塊數量相同時，依順序配對 DUT 名稱。此功能假設兩種量測順序一致；請查看 `run_notes.txt` 的配對紀錄。若順序不一致，可將：

```python
AUTO_MATCH_GENERIC_CHANNEL_NAMES = False
```

## 規格判定

- 低於 LSL：`FAIL_LSL`
- 高於 USL：`FAIL_USL`
- 有設定規格且數值在範圍內：`PASS`
- USL 與 LSL 都未設定：`NOT_SET`
- 該頻點沒有對應數值：`NO_DATA`

目前規格是套用於整個頻率範圍的固定水平線，不支援隨頻率變化的 limit mask。

## 執行測試

```bash
python -m unittest discover -s tests -v
```

## 公開資料注意事項

`sample_data/RMS_THD_sample.csv` 為合成示範資料。公開其他檔案前，仍請確認程式、圖片、輸出報告及 commit history 不包含：

- 客戶名稱或專案名稱
- 產品料號或真實 DUT 序號
- 公司內部資料夾路徑
- 尚未公開的量測結果或規格

本 repository 尚未指定軟體授權。公開瀏覽不等同允許他人複製、修改或散布；若希望他人可使用或協作，請再選擇合適的 `LICENSE`。
