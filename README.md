# RMS / THD Analyzer for Audio Precision CSV

將 Audio Precision（AP）匯出的多區塊 CSV 轉成容易分析的 RMS Level／THD 數值表，並輸出個別 DUT 曲線與多台 DUT 疊圖。

本工具適合麥克風、喇叭與 IPCam 聲學量測資料整理。它會讀取 AP 已計算完成的 RMS Level（dBSPL）與 THD Ratio（%）；不會從原始音訊重新計算 RMS 或 THD。

## 主要功能

- 解析 AP 重複區塊格式的 RMS Level／THD Ratio CSV。
- 輸出 RMS、THD 寬表及含規格判定的整合長表。
- 輸出每個 DUT 的個別 CSV 與曲線圖。
- 使用 DUT 編號或完整名稱選擇疊圖曲線。
- 支援 `--compare-only`，只更新比較圖，不重寫數值 CSV 與個別圖。
- 支援 `--interactive`，同一次執行可連續建立多組比較圖。
- 每次執行都建立全新輸出資料夾，預設加入 13 碼執行時間。
- 若資料夾名稱碰巧重複，自動追加 `_001`、`_002`……，絕不沿用舊資料夾。
- 可設定 USL／LSL、頻率範圍、Y 軸、格線、字體與線寬。
- AP 若將部分曲線命名為 `Ch1`，可依 RMS／THD 量測順序自動配對 DUT 名稱。

## 執行環境

- Python 3.10 或以上版本
- matplotlib 3.7 或以上版本
- Windows、macOS 或 Linux

安裝相依套件：

```bash
python -m pip install "matplotlib>=3.7"
```

## 快速開始

下載 [RMS_THD_Analyzer.py](./RMS_THD_Analyzer.py)，在終端機執行：

```bash
python RMS_THD_Analyzer.py RMS_THD.csv -o rms_thd_output
```

實際建立的資料夾會自動加入執行時間，例如：

```text
rms_thd_output_2608121147010
```

時間格式為 `YYMMDDHHMMSS + 1 位小數秒`。若不需要時間標籤，可加上
`--no-timestamp`；但防覆蓋機制仍會啟用，若指定名稱已存在，程式會建立
`rms_thd_output_001`、`rms_thd_output_002`……。

程式開始輸出前，終端機會先顯示實際建立的位置：

```text
全新輸出資料夾：D:\Project\rms_thd_output_2608121147010
```

Windows 路徑含空格時，請用雙引號包住完整路徑：

```powershell
python "D:\Tools\RMS_THD_Analyzer.py" `
  "D:\Project\Acoustic Test\RMS_THD.csv" `
  -o "D:\Project\Acoustic Test\rms_thd_output"
```

查看所有參數：

```bash
python RMS_THD_Analyzer.py --help
```

## 常用指令

### 1. 查看 DUT 編號

不建立任何輸出檔案：

```bash
python RMS_THD_Analyzer.py RMS_THD.csv --list-duts
```

終端機會列出：

```text
可選擇的 RMS DUT：
  1: DUT_A
  2: DUT_B
  3: DUT_C
```

### 2. 指定 RMS／THD 比較圖的 DUT

DUT 編號可用空格或逗號分隔：

```bash
python RMS_THD_Analyzer.py RMS_THD.csv -o rms_thd_output \
  --rms-compare-duts 1 2 3 \
  --thd-compare-duts 1,3
```

也可輸入 AP CSV 中的完整 DUT 名稱：

```bash
python RMS_THD_Analyzer.py RMS_THD.csv \
  --rms-compare-duts DUT_A DUT_B \
  --thd-compare-duts DUT_A DUT_B
```

### 3. 只更新比較圖

CSV 仍會被讀取與解析，但不會重寫彙整 CSV、個別 DUT CSV、個別圖或 `run_notes.txt`：

```bash
python RMS_THD_Analyzer.py RMS_THD.csv -o rms_thd_output \
  --compare-only \
  --rms-compare-duts 1,2,3 \
  --thd-compare-duts 1,2,3
```

為了防止誤蓋資料，`--compare-only` 也會建立新資料夾。如果指定的無時間標籤
名稱已存在，會自動建立流水號資料夾：

```bash
python RMS_THD_Analyzer.py RMS_THD.csv \
  -o rms_thd_compare \
  --no-timestamp --compare-only \
  --rms-compare-duts 1,2,3 \
  --thd-compare-duts 1,2,3
```

以上指令第一次會建立 `rms_thd_compare`；再次執行會建立
`rms_thd_compare_001`，因此不會覆蓋第一次的比較圖。

### 4. 互動模式

CSV 只解析一次，之後可在同一個終端機工作階段連續選擇 DUT：

```bash
python RMS_THD_Analyzer.py RMS_THD.csv -o rms_thd_output --interactive
```

互動命令範例：

```text
compare> rms 1 2 3
compare> thd 1,3
compare> both 2 3
compare> rms all
compare> list
compare> help
compare> quit
```

互動模式會將圖片依序另存為 `_001`、`_002`……，不會覆蓋先前建立的比較圖。

## 可調整設定

所有常用設定都集中在 `RMS_THD_Analyzer.py` 最上方的「1. 使用者設定」區。

| 設定 | 單位／選項 | 用途 |
|---|---|---|
| `RMS_USL`、`RMS_LSL` | dBSPL 或 `None` | RMS 固定上下限；`None` 表示關閉 |
| `THD_USL`、`THD_LSL` | % 或 `None` | THD 固定上下限；`None` 表示關閉 |
| `FREQUENCY_RANGE_HZ` | Hz | 圖形與 CSV 的輸出頻率範圍 |
| `RMS_Y_RANGE` | dBSPL 或 `None` | RMS 圖 Y 軸範圍 |
| `RMS_Y_GRID_INTERVAL` | dB 或 `None` | RMS 水平格線間距 |
| `THD_Y_RANGE` | % 或 `None` | THD 圖 Y 軸範圍 |
| `THD_Y_SCALE` | `"log"`／`"linear"` | THD 對數軸或線性軸 |
| `FONT_SIZE` | pt | 圖中文字大小 |
| `LINE_WIDTH` | pt | DUT 曲線粗細 |
| `LIMIT_LINE_WIDTH` | pt | USL／LSL 線條粗細 |
| `FIGURE_SIZE` | inch | 圖片尺寸 |
| `IMAGE_DPI` | dpi | 圖片解析度 |
| `RMS_COMPARE_DUTS` | 編號、名稱或 `None` | 未使用 command 時的 RMS 預設曲線 |
| `THD_COMPARE_DUTS` | 編號、名稱或 `None` | 未使用 command 時的 THD 預設曲線 |
| `ADD_OUTPUT_TIMESTAMP` | `True`／`False` | 是否自動在輸出資料夾名稱加入執行時間 |

例如，RMS 圖顯示 50～60 dBSPL，且每 2 dB 一條水平格線：

```python
RMS_Y_RANGE = (50.0, 60.0)
RMS_Y_GRID_INTERVAL = 2.0
```

Y 軸會標示 `50、52、54、56、58、60`。Command 指定的 DUT 會優先於程式內的 `RMS_COMPARE_DUTS`／`THD_COMPARE_DUTS`。

## 輸入 CSV 格式

程式預期輸入為 AP 匯出的重複量測區塊，區塊標題需包含：

- `RMS Level`
- `THD Ratio`

每個區塊需包含 DUT 名稱、頻率欄及數值欄。以下是簡化示意，實際 AP 匯出內容可以包含額外欄位或空白列：

```csv
THD Ratio
DUT_A
Hz,%
100,1.20
1000,0.45
10000,1.80

RMS Level
DUT_A
Hz,dBSPL
100,52.4
1000,58.1
10000,55.7
```

輸入檔至少要包含一個 RMS 區塊與一個 THD 區塊。建議 GitHub repository 只放合成或去識別化的示範 CSV，不要上傳客戶名稱、專案料號、真實序號或未公開量測結果。

## 輸出內容

```text
rms_thd_output_2608121147010/
├─ rms_level_values.csv
├─ thd_values.csv
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

| 輸出 | 說明 |
|---|---|
| `rms_level_values.csv` | 頻率 × DUT 的 RMS Level 寬表 |
| `thd_values.csv` | 頻率 × DUT 的 THD 寬表 |
| `rms_thd_all_values.csv` | DUT、頻率、RMS、THD、規格值及 PASS／FAIL 長表 |
| `data_by_dut/` | 每台 DUT 各一份 RMS＋THD CSV；DUT 名稱會寫入 RMS／THD 欄名 |
| `plots/individual/` | 每台 DUT 的個別 RMS／THD 圖 |
| `plots/comparison/` | 指定 DUT 的 RMS／THD 疊圖 |
| `run_notes.txt` | 輸入路徑、DUT 清單及 `Ch1` 名稱配對紀錄 |

CSV 使用 UTF-8 with BOM，方便直接用 Microsoft Excel 開啟中文內容。

`data_by_dut/<DUT>.csv` 不再重複輸出 `DUT_ID` 欄；DUT 名稱會直接放進量測欄名。例如 `DUT_WA001.csv`：

```text
Frequency_Hz,DUT_WA001_RMS_Level_dBSPL,DUT_WA001_THD_Percent,RMS_Result,THD_Result
100,66.65530625,35.60145315,PASS,PASS
106,65.35239896,32.8938093,PASS,PASS
```

彙整檔 `rms_thd_all_values.csv` 仍保留 `DUT_ID` 欄，方便在同一張長表中區分不同 DUT。

## DUT 名稱自動配對

部分 AP 匯出檔會保留 THD 的 DUT 名稱，卻將對應 RMS 曲線統一命名為 `Ch1`。當 RMS 與 THD 區塊數量相同時，程式可依量測順序配對並補回名稱。

此功能假設 RMS 與 THD 的區塊順序一致。執行後請查看 `run_notes.txt` 的配對紀錄；若原始資料順序不同，應先修正 CSV 或將：

```python
AUTO_MATCH_GENERIC_CHANNEL_NAMES = False
```

## 規格判定方式

- RMS 與 THD 分別判定。
- 低於 LSL：`FAIL_LSL`
- 高於 USL：`FAIL_USL`
- 有設定規格且在範圍內：`PASS`
- 未設定 USL 與 LSL：`NOT_SET`
- 該頻點沒有資料：`NO_DATA`

目前 USL／LSL 是套用於整個頻率範圍的固定水平線，不支援隨頻率變化的 limit mask。

## 常見問題

### 顯示 `No module named 'matplotlib'`

```bash
python -m pip install matplotlib
```

### Windows 顯示找不到檔案

確認程式、輸入 CSV 與輸出資料夾皆使用正確完整路徑；路徑含空格時必須加雙引號。

### 找不到 RMS Level 或 THD Ratio 區塊

確認檔案是 AP 匯出的 CSV，且區塊標題仍包含 `RMS Level` 與 `THD Ratio`。若曾用 Excel 重新另存，請檢查表格結構是否被改寫。

### THD 曲線缺少部分資料點

當 `THD_Y_SCALE = "log"` 時，零或負數無法顯示在對數軸，因此程式會略過這些點。原始數值仍應先確認是否為有效量測結果。

## 建議的 repository 結構

```text
RMS-THD-Analyzer/
├─ RMS_THD_Analyzer.py
├─ README.md
├─ requirements.txt
├─ .gitignore
├─ sample_data/
│  └─ RMS_THD_sample.csv
└─ examples/
   ├─ rms_compare_example.png
   └─ thd_compare_example.png
```

`requirements.txt` 可寫成：

```text
matplotlib>=3.7
```

若 repository 要公開，請先確認程式、示範 CSV、圖片與 commit history 都不含公司或客戶機密，並依預計的分享方式選擇適當的 `LICENSE`。
