r"""Audio Precision RMS / THD / THD+N CSV 分析工具（單檔版）。

主要功能：
1. 解析 AP 匯出的多區塊 RMS Level / THD Ratio / THD+N CSV。
2. 輸出彙整 CSV、各 DUT CSV、個別曲線圖與疊圖比較。
3. 可用 DUT 編號或完整名稱選擇 RMS / THD 比較曲線。
4. 支援互動模式：CSV 只解析一次，可連續建立多組比較圖。
5. 支援 compare-only：只重畫比較圖，不重做 CSV 與個別圖。
6. 每次執行都先建立全新輸出資料夾，避免不同次量測互相覆蓋。

安裝套件（只需一次）：
    pip install matplotlib

常用指令：
    python RMS_THD_Analyzer.py "D:\Project\RMS_THD.csv" -o "D:\Project\rms_thd_output"
    python RMS_THD_Analyzer.py "D:\Project\RMS_THD.csv" --list-duts
    python RMS_THD_Analyzer.py "D:\Project\RMS_THD.csv" -o "D:\Project\rms_thd_output" --interactive

更多指令與範例：
    python RMS_THD_Analyzer.py --help

平常只需要修改下方「1. 使用者設定」；其餘區段通常不需更動。
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator


# =============================================================================
# 1. 使用者設定（平常只需修改本區）
# =============================================================================

# 1-1. 規格上下限；不使用時設為 None。
# RMS 單位會跟隨輸入 CSV（例如 dBSPL 或 dBFS）；THD / THD+N 必須為 %。
RMS_USL = None                 # 例如 110.0
RMS_LSL = None                 # 例如 75.0
THD_USL = None                 # %，例如 10.0；THD+N 也沿用此設定
THD_LSL = None                 # %，通常不設定

# 1-2. 圖形顯示及 CSV 輸出的頻率範圍。
FREQUENCY_RANGE_HZ = (100.0, 10_000.0)

# 1-3. Y 軸範圍與格線；設為 None 代表自動。
RMS_Y_RANGE = (20.0, 120.0)   # 單位同輸入；若要顯示 50～60，改為 (50.0, 60.0)
RMS_Y_GRID_INTERVAL = 2.0     # 每條水平格線相差 2 dB；None = 自動
THD_Y_RANGE = (0.05, 100.0)   # %；對數軸時上下限必須大於 0
THD_Y_SCALE = "log"           # "log" 或 "linear"

# 1-4. 圖形外觀。
FONT_SIZE = 12
LINE_WIDTH = 2.0
LIMIT_LINE_WIDTH = 1.6
FIGURE_SIZE = (14, 7)
IMAGE_DPI = 180

# 1-5. 未使用 command 參數時，預設放入比較圖的 DUT。
# None = 全部 DUT；也可填編號或完整名稱，例如 ["1", "3"]。
RMS_COMPARE_DUTS = None
THD_COMPARE_DUTS = None

# 1-6. 其他輸出開關。
CREATE_INDIVIDUAL_PLOTS = True
CREATE_ONE_CSV_PER_DUT = True

# True：輸出資料夾自動加入時間標籤，例如 rms_thd_output_2608121147010。
# 格式為 YYMMDDHHMMSS + 1 位小數秒；command 加上 --no-timestamp 可暫時關閉。
# 無論是否使用時間標籤，程式都不會沿用既有資料夾；撞名時會加 _001、_002……。
ADD_OUTPUT_TIMESTAMP = True

# AP 有時把 RMS 名稱匯出成 Ch1，但相同量測順序的失真曲線保留 DUT 名稱。
# True：RMS / 失真區塊數相同時，依量測順序自動配對名稱。
AUTO_MATCH_GENERIC_CHANNEL_NAMES = True

# =============================================================================
# 2. 資料結構與共用常數（通常不需修改）
# =============================================================================


@dataclass
class MeasurementBlock:
    kind: str                 # "RMS" or "THD"
    metric: str               # "RMS", "THD", or "THD+N"
    name: str
    unit: str
    points: list[tuple[float, float]]
    source_block_number: int


GENERIC_NAMES = {"ch", "channel", "trace", "data", "curve"}
AP_FREQUENCY_TICKS = [
    20, 30, 40, 50, 60, 70, 80, 90,
    100, 200, 300, 400, 500, 600, 700, 800, 900,
    1_000, 2_000, 3_000, 4_000, 5_000, 6_000, 7_000, 8_000, 9_000, 10_000,
    20_000,
]
THD_LOG_TICKS = [0.01, 0.02, 0.03, 0.05, 0.1, 0.2, 0.3, 0.5,
                 1, 2, 3, 5, 10, 20, 30, 50, 100]
MAX_LABELED_RMS_GRID_LINES = 15
WINDOWS_RESERVED_FILENAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


# =============================================================================
# 3. AP CSV 解析與 DUT 名稱整理
# =============================================================================


def _clean_cell(value: str) -> str:
    return value.strip().lstrip("\ufeff")


def _is_number(value: str) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def _is_generic_name(name: str) -> bool:
    normalized = re.sub(r"[\s_\-]+", "", name).casefold()
    return any(normalized == prefix or re.fullmatch(prefix + r"\d+", normalized)
               for prefix in GENERIC_NAMES)


def parse_ap_csv(path: Path) -> list[MeasurementBlock]:
    """Read AP's repeated-section CSV rather than assuming one table header."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [[_clean_cell(cell) for cell in row] for row in csv.reader(handle)]

    blocks: list[MeasurementBlock] = []
    index = 0
    block_number = 0

    while index < len(rows):
        title = rows[index][0] if rows[index] else ""
        normalized_title = title.casefold()
        is_summary = normalized_title.startswith("summary:")
        if not is_summary and re.search(r"\bthd\s*\+\s*n\b", normalized_title):
            kind = "THD"
            metric = "THD+N"
        elif not is_summary and "thd ratio" in normalized_title:
            kind = "THD"
            metric = "THD"
        elif not is_summary and "rms level" in normalized_title:
            kind = "RMS"
            metric = "RMS"
        else:
            index += 1
            continue

        block_number += 1
        cursor = index + 1
        while cursor < len(rows) and (not rows[cursor] or not rows[cursor][0]):
            cursor += 1
        if cursor >= len(rows):
            break
        name = rows[cursor][0]

        # Locate the units row (normally "Hz,%" or "Hz,dBSPL").
        units_row = None
        for candidate in range(cursor + 1, min(cursor + 8, len(rows))):
            first = rows[candidate][0].casefold() if rows[candidate] else ""
            if first in {"hz", "frequency", "frequency (hz)"}:
                units_row = candidate
                break
        if units_row is None:
            raise ValueError(
                f"Block {block_number} ({kind}, {name!r}) has no frequency units row."
            )

        unit = rows[units_row][1] if len(rows[units_row]) > 1 else ""
        points: list[tuple[float, float]] = []
        cursor = units_row + 1
        while cursor < len(rows):
            row = rows[cursor]
            if len(row) < 2 or not _is_number(row[0]) or not _is_number(row[1]):
                break
            points.append((float(row[0]), float(row[1])))
            cursor += 1

        if not points:
            raise ValueError(f"Block {block_number} ({kind}, {name!r}) contains no numeric data.")
        blocks.append(MeasurementBlock(kind, metric, name, unit, points, block_number))
        index = max(cursor, index + 1)

    if not blocks:
        raise ValueError(
            "No 'RMS Level', 'THD Ratio', or 'THD+N' data blocks were found in the CSV."
        )
    return blocks


def _canonical_unit(unit: str) -> str:
    """Normalize common AP unit spellings without changing the numeric values."""
    compact = re.sub(r"\s+", "", unit).casefold()
    aliases = {
        "%": "%",
        "percent": "%",
        "pct": "%",
        "dbspl": "dBSPL",
        "dbfs": "dBFS",
        "dbv": "dBV",
        "vrms": "Vrms",
        "v": "V",
    }
    return aliases.get(compact, unit.strip())


def validate_measurement_metadata(
    blocks: Sequence[MeasurementBlock],
) -> tuple[str, str]:
    """Return the RMS unit and distortion metric after consistency checks."""
    rms_blocks = [block for block in blocks if block.kind == "RMS"]
    distortion_blocks = [block for block in blocks if block.kind == "THD"]

    for block in blocks:
        block.unit = _canonical_unit(block.unit)
        if not block.unit:
            raise ValueError(
                f"Block {block.source_block_number} ({block.metric}, {block.name!r}) "
                "has no measurement unit."
            )

    rms_units = {block.unit for block in rms_blocks}
    if len(rms_units) != 1:
        raise ValueError(
            "RMS blocks use inconsistent units: " + ", ".join(sorted(rms_units))
        )

    distortion_units = {block.unit for block in distortion_blocks}
    if distortion_units != {"%"}:
        shown = ", ".join(sorted(distortion_units)) or "none"
        raise ValueError(
            "THD / THD+N data must use percent (%). "
            f"Detected unit(s): {shown}. dB values are not converted automatically."
        )

    distortion_metrics = {block.metric for block in distortion_blocks}
    if len(distortion_metrics) != 1:
        raise ValueError(
            "The same CSV cannot mix THD Ratio and THD+N blocks. "
            "Export one distortion metric at a time."
        )

    return next(iter(rms_units)), next(iter(distortion_metrics))


def reconcile_dut_names(blocks: list[MeasurementBlock]) -> list[str]:
    """Repair generic AP channel names conservatively and return warning notes."""
    warnings: list[str] = []
    rms_blocks = [block for block in blocks if block.kind == "RMS"]
    thd_blocks = [block for block in blocks if block.kind == "THD"]

    if AUTO_MATCH_GENERIC_CHANNEL_NAMES and len(rms_blocks) == len(thd_blocks):
        for position, (rms, thd) in enumerate(zip(rms_blocks, thd_blocks), start=1):
            rms_generic = _is_generic_name(rms.name)
            thd_generic = _is_generic_name(thd.name)
            if rms_generic and not thd_generic:
                warnings.append(
                    f"RMS block {position}: generic name {rms.name!r} matched to {thd.name!r} by order."
                )
                rms.name = thd.name
            elif thd_generic and not rms_generic:
                warnings.append(
                    f"THD block {position}: generic name {thd.name!r} matched to {rms.name!r} by order."
                )
                thd.name = rms.name
            elif rms_generic and thd_generic:
                generated = f"DUT_{position:02d}"
                warnings.append(
                    f"RMS/THD block {position}: both names were generic; assigned {generated!r}."
                )
                rms.name = thd.name = generated

    # Make repeated names unique while keeping paired RMS/THD runs aligned.
    occurrence_by_kind: dict[str, Counter[str]] = {"RMS": Counter(), "THD": Counter()}
    for kind in ("RMS", "THD"):
        for block in [item for item in blocks if item.kind == kind]:
            occurrence_by_kind[kind][block.name] += 1

    seen: dict[str, Counter[str]] = {"RMS": Counter(), "THD": Counter()}
    for kind in ("RMS", "THD"):
        for block in [item for item in blocks if item.kind == kind]:
            seen[kind][block.name] += 1
            if occurrence_by_kind[kind][block.name] > 1:
                original = block.name
                block.name = f"{original}_run{seen[kind][original]}"
                warnings.append(f"Repeated {kind} name {original!r} renamed to {block.name!r}.")

    return warnings


def build_measurement_map(
    blocks: Iterable[MeasurementBlock], kind: str
) -> dict[str, dict[float, float]]:
    """將量測區塊轉成 {DUT: {頻率: 數值}}，供輸出與繪圖共用。"""
    return {
        block.name: {frequency: value for frequency, value in block.points}
        for block in blocks
        if block.kind == kind
    }


def _frequency_in_range(frequency: float) -> bool:
    low, high = FREQUENCY_RANGE_HZ
    return low <= frequency <= high


def _safe_filename(name: str) -> str:
    """Create a Windows-safe filename stem while preserving readable Unicode."""
    normalized = unicodedata.normalize("NFKC", name)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    if not cleaned:
        cleaned = "DUT"
    if cleaned.upper() in WINDOWS_RESERVED_FILENAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:120].rstrip(". ") or "DUT"


def _unique_filename_stems(names: Sequence[str]) -> dict[str, str]:
    """Return deterministic, case-insensitively unique filename stems."""
    stems: dict[str, str] = {}
    used: set[str] = set()
    for name in names:
        base = _safe_filename(name)
        candidate = base
        sequence = 2
        while candidate.casefold() in used:
            suffix = f"_{sequence:03d}"
            candidate = f"{base[:120 - len(suffix)].rstrip()}{suffix}"
            sequence += 1
        used.add(candidate.casefold())
        stems[name] = candidate
    return stems


def _column_unit_token(unit: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", unit).strip("_") or "Value"


def _distortion_token(metric: str) -> str:
    return "THD_N" if metric == "THD+N" else "THD"


def _number_text(value: float | None) -> str:
    return "" if value is None else f"{value:.10g}"


def _limit_result(value: float | None, lsl: float | None, usl: float | None) -> str:
    if value is None:
        return "NO_DATA"
    if lsl is not None and value < lsl:
        return "FAIL_LSL"
    if usl is not None and value > usl:
        return "FAIL_USL"
    if lsl is None and usl is None:
        return "NOT_SET"
    return "PASS"


# =============================================================================
# 4. CSV 輸出
# =============================================================================


def write_wide_csv(path: Path, data: dict[str, dict[float, float]]) -> None:
    """輸出寬表：每個 DUT 一欄，便於直接在 Excel 比較。"""
    frequencies = sorted({frequency for trace in data.values() for frequency in trace if _frequency_in_range(frequency)})
    names = list(data)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Frequency_Hz", *names])
        for frequency in frequencies:
            writer.writerow([_number_text(frequency), *[_number_text(data[name].get(frequency)) for name in names]])


def write_long_csv(
    path: Path,
    rms_data: dict[str, dict[float, float]],
    thd_data: dict[str, dict[float, float]],
    rms_unit: str,
    distortion_metric: str,
) -> None:
    """輸出長表：每列為 DUT + 頻率，並包含上下限與 PASS/FAIL。"""
    all_names = list(dict.fromkeys([*rms_data, *thd_data]))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        rms_unit_token = _column_unit_token(rms_unit)
        distortion_token = _distortion_token(distortion_metric)
        writer.writerow([
            "DUT_ID", "Frequency_Hz",
            f"RMS_Level_{rms_unit_token}", f"{distortion_token}_Percent",
            f"RMS_LSL_{rms_unit_token}", f"RMS_USL_{rms_unit_token}", "RMS_Result",
            f"{distortion_token}_LSL_Percent", f"{distortion_token}_USL_Percent",
            f"{distortion_token}_Result",
        ])
        for name in all_names:
            frequencies = sorted({*rms_data.get(name, {}), *thd_data.get(name, {})})
            for frequency in frequencies:
                if not _frequency_in_range(frequency):
                    continue
                rms_value = rms_data.get(name, {}).get(frequency)
                thd_value = thd_data.get(name, {}).get(frequency)
                writer.writerow([
                    name, _number_text(frequency), _number_text(rms_value), _number_text(thd_value),
                    _number_text(RMS_LSL), _number_text(RMS_USL), _limit_result(rms_value, RMS_LSL, RMS_USL),
                    _number_text(THD_LSL), _number_text(THD_USL), _limit_result(thd_value, THD_LSL, THD_USL),
                ])


def write_per_dut_csvs(
    output_dir: Path,
    rms_data: dict[str, dict[float, float]],
    thd_data: dict[str, dict[float, float]],
    rms_unit: str,
    distortion_metric: str,
) -> None:
    """每個 DUT 各輸出一份 RMS 與 THD CSV，並將 DUT 名稱寫入量測欄名。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    all_names = list(dict.fromkeys([*rms_data, *thd_data]))
    filename_stems = _unique_filename_stems(all_names)
    rms_unit_token = _column_unit_token(rms_unit)
    distortion_token = _distortion_token(distortion_metric)
    for name in all_names:
        path = output_dir / f"{filename_stems[name]}.csv"
        frequencies = sorted({*rms_data.get(name, {}), *thd_data.get(name, {})})
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "Frequency_Hz",
                f"{name}_RMS_Level_{rms_unit_token}",
                f"{name}_{distortion_token}_Percent",
                "RMS_Result", f"{distortion_token}_Result",
            ])
            for frequency in frequencies:
                if not _frequency_in_range(frequency):
                    continue
                rms_value = rms_data.get(name, {}).get(frequency)
                thd_value = thd_data.get(name, {}).get(frequency)
                writer.writerow([
                    _number_text(frequency), _number_text(rms_value), _number_text(thd_value),
                    _limit_result(rms_value, RMS_LSL, RMS_USL),
                    _limit_result(thd_value, THD_LSL, THD_USL),
                ])


# =============================================================================
# 5. 圖形座標、規格線與單張圖輸出
# =============================================================================


def _frequency_tick_label(value: float, _position: int) -> str:
    if value >= 1000:
        return f"{value / 1000:g}k"
    return f"{value:g}"


def _plain_tick_label(value: float, _position: int) -> str:
    return f"{value:g}"


def _configure_axis(
    ax: plt.Axes,
    measurement: str,
    rms_unit: str,
    distortion_metric: str,
) -> None:
    low_frequency, high_frequency = FREQUENCY_RANGE_HZ
    ax.set_xscale("log")
    ax.set_xlim(low_frequency, high_frequency)
    ticks = [tick for tick in AP_FREQUENCY_TICKS if low_frequency <= tick <= high_frequency]
    ax.set_xticks(ticks)
    ax.xaxis.set_major_formatter(FuncFormatter(_frequency_tick_label))
    ax.set_xlabel("Frequency (Hz)")

    if measurement == "RMS":
        ax.set_ylabel(f"RMS Level ({rms_unit})")
        if RMS_Y_RANGE is not None:
            ax.set_ylim(*RMS_Y_RANGE)
        if RMS_Y_GRID_INTERVAL is not None:
            # 例如 50～60、間距 2 時，直接標示 50/52/54/56/58/60。
            # 若範圍很大，2 dB 仍保留為小格線，但只標示每 10 dB，避免文字擠在一起。
            bottom, top = ax.get_ylim()
            grid_count = (top - bottom) / RMS_Y_GRID_INTERVAL
            if grid_count <= MAX_LABELED_RMS_GRID_LINES:
                ax.yaxis.set_major_locator(MultipleLocator(RMS_Y_GRID_INTERVAL))
            else:
                ax.yaxis.set_major_locator(MultipleLocator(RMS_Y_GRID_INTERVAL * 5))
                ax.yaxis.set_minor_locator(MultipleLocator(RMS_Y_GRID_INTERVAL))
    else:
        ax.set_ylabel(f"{distortion_metric} (%)")
        ax.set_yscale(THD_Y_SCALE)
        if THD_Y_RANGE is not None:
            ax.set_ylim(*THD_Y_RANGE)
        if THD_Y_SCALE == "log":
            bottom, top = ax.get_ylim()
            ax.set_yticks([tick for tick in THD_LOG_TICKS if bottom <= tick <= top])
            ax.yaxis.set_major_formatter(FuncFormatter(_plain_tick_label))

    ax.grid(True, which="major", color="#9aa0a6", alpha=0.48, linewidth=0.7)
    ax.grid(True, which="minor", color="#c7cbd1", alpha=0.30, linewidth=0.5)
    ax.set_axisbelow(True)


def _draw_limits(ax: plt.Axes, measurement: str) -> None:
    lsl, usl = (RMS_LSL, RMS_USL) if measurement == "RMS" else (THD_LSL, THD_USL)
    if usl is not None:
        ax.axhline(usl, color="#d62728", linestyle="--", linewidth=LIMIT_LINE_WIDTH,
                   label=f"USL = {usl:g}")
    if lsl is not None:
        ax.axhline(lsl, color="#ff7f0e", linestyle="--", linewidth=LIMIT_LINE_WIDTH,
                   label=f"LSL = {lsl:g}")


def _filtered_xy(trace: dict[float, float], measurement: str) -> tuple[list[float], list[float]]:
    pairs = sorted((frequency, value) for frequency, value in trace.items() if _frequency_in_range(frequency))
    if measurement == "THD" and THD_Y_SCALE == "log":
        pairs = [(frequency, value) for frequency, value in pairs if value > 0]
    return [item[0] for item in pairs], [item[1] for item in pairs]


def save_plot(
    path: Path,
    data: dict[str, dict[float, float]],
    selected_names: Sequence[str],
    measurement: str,
    title: str,
    rms_unit: str,
    distortion_metric: str,
) -> None:
    """儲存一張 RMS 或 THD 圖，可包含一條或多條 DUT 曲線。"""
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for name in selected_names:
        x_values, y_values = _filtered_xy(data[name], measurement)
        ax.plot(x_values, y_values, linewidth=LINE_WIDTH, label=name)

    _draw_limits(ax, measurement)
    _configure_axis(ax, measurement, rms_unit, distortion_metric)
    ax.set_title(title)
    ax.legend(loc="best", fontsize=max(8, FONT_SIZE - 1), framealpha=0.92)
    fig.tight_layout()
    fig.savefig(path, dpi=IMAGE_DPI, bbox_inches="tight")
    plt.close(fig)


# =============================================================================
# 6. DUT 選擇、個別圖、比較圖與互動模式
# =============================================================================


def _resolve_selection(
    requested: Sequence[str] | None,
    available: Sequence[str],
    label: str,
) -> list[str]:
    if requested is None:
        return list(available)

    # 支援完整名稱、從 1 開始的 DUT 編號、逗號/分號分隔，以及 all。
    tokens = [
        token.strip()
        for value in requested
        for token in re.split(r"[,;]", value)
        if token.strip()
    ]
    if len(tokens) == 1 and tokens[0].casefold() == "all":
        return list(available)

    resolved: list[str] = []
    missing: list[str] = []
    for token in tokens:
        if token.isdigit():
            position = int(token)
            if 1 <= position <= len(available):
                name = available[position - 1]
            else:
                missing.append(token)
                continue
        elif token in available:
            name = token
        else:
            missing.append(token)
            continue
        if name not in resolved:
            resolved.append(name)

    if missing:
        raise ValueError(
            f"找不到 {label} DUT：{', '.join(missing)}。"
            f"請使用 1～{len(available)} 的 DUT 編號或完整名稱。"
            f"目前可用：{', '.join(available) or '無'}"
        )
    return resolved


def _configure_plot_style() -> None:
    plt.rcParams.update({
        "font.size": FONT_SIZE,
        "axes.titlesize": FONT_SIZE + 2,
        "axes.labelsize": FONT_SIZE,
        "xtick.labelsize": max(8, FONT_SIZE - 1),
        "ytick.labelsize": max(8, FONT_SIZE - 1),
    })


def create_individual_plots(
    output_dir: Path,
    rms_data: dict[str, dict[float, float]],
    thd_data: dict[str, dict[float, float]],
    rms_unit: str,
    distortion_metric: str,
) -> None:
    if not CREATE_INDIVIDUAL_PLOTS:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    filename_stems = _unique_filename_stems(
        list(dict.fromkeys([*rms_data, *thd_data]))
    )
    distortion_file_token = _distortion_token(distortion_metric)
    for name in rms_data:
        save_plot(
            output_dir / f"{filename_stems[name]}_RMS_Level.png",
            rms_data, [name], "RMS", f"RMS Level — {name}",
            rms_unit, distortion_metric,
        )
    for name in thd_data:
        save_plot(
            output_dir / f"{filename_stems[name]}_{distortion_file_token}.png",
            thd_data, [name], "THD", f"{distortion_metric} — {name}",
            rms_unit, distortion_metric,
        )


def create_comparison_plots(
    output_dir: Path,
    rms_data: dict[str, dict[float, float]],
    thd_data: dict[str, dict[float, float]],
    rms_requested: Sequence[str] | None,
    thd_requested: Sequence[str] | None,
    rms_unit: str,
    distortion_metric: str,
    rms_filename: str = "RMS_Level_Comparison.png",
    thd_filename: str | None = None,
) -> tuple[list[str], list[str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if thd_filename is None:
        thd_filename = f"{_distortion_token(distortion_metric)}_Comparison.png"
    rms_selection = _resolve_selection(rms_requested, list(rms_data), "RMS")
    thd_selection = _resolve_selection(thd_requested, list(thd_data), "THD")
    if rms_selection:
        save_plot(
            output_dir / rms_filename,
            rms_data, rms_selection, "RMS", "RMS Level Comparison",
            rms_unit, distortion_metric,
        )
    if thd_selection:
        save_plot(
            output_dir / thd_filename,
            thd_data, thd_selection, "THD", f"{distortion_metric} Comparison",
            rms_unit, distortion_metric,
        )
    return rms_selection, thd_selection


def create_plots(
    output_dir: Path,
    rms_data: dict[str, dict[float, float]],
    thd_data: dict[str, dict[float, float]],
    rms_requested: Sequence[str] | None,
    thd_requested: Sequence[str] | None,
    rms_unit: str,
    distortion_metric: str,
) -> None:
    _configure_plot_style()
    create_individual_plots(
        output_dir / "individual", rms_data, thd_data,
        rms_unit, distortion_metric,
    )
    create_comparison_plots(
        output_dir / "comparison", rms_data, thd_data,
        rms_requested, thd_requested, rms_unit, distortion_metric,
    )


def _print_dut_menu(
    rms_names: Sequence[str],
    thd_names: Sequence[str],
    distortion_metric: str,
) -> None:
    print("\n可選擇的 RMS DUT：")
    for number, name in enumerate(rms_names, start=1):
        print(f"  {number}: {name}")
    print(f"可選擇的 {distortion_metric} DUT：")
    for number, name in enumerate(thd_names, start=1):
        print(f"  {number}: {name}")


def _next_comparison_path(
    output_dir: Path,
    measurement: str,
    distortion_metric: str,
) -> Path:
    stem = (
        "RMS_Level_Comparison"
        if measurement == "RMS"
        else f"{_distortion_token(distortion_metric)}_Comparison"
    )
    sequence = 1
    while True:
        candidate = output_dir / f"{stem}_{sequence:03d}.png"
        if not candidate.exists():
            return candidate
        sequence += 1


def run_interactive_comparison(
    output_dir: Path,
    rms_data: dict[str, dict[float, float]],
    thd_data: dict[str, dict[float, float]],
    rms_unit: str,
    distortion_metric: str,
) -> None:
    """CSV 只解析一次，在同一執行階段連續建立多組比較圖。"""
    rms_names = list(rms_data)
    thd_names = list(thd_data)
    output_dir.mkdir(parents=True, exist_ok=True)
    _print_dut_menu(rms_names, thd_names, distortion_metric)
    print(
        "\n可用命令：rms 1 2 3 | thd 1,2,3 | both 1 2 | list | help | quit\n"
        "可使用 DUT 編號、完整名稱或 all；每次都會另存新的 PNG，不覆蓋舊圖。"
    )

    while True:
        try:
            command_line = input("compare> ").strip()
        except EOFError:
            print()
            break
        if not command_line:
            continue
        parts = command_line.split()
        command = parts[0].casefold()
        requested = parts[1:]

        if command in {"quit", "exit", "q"}:
            break
        if command == "list":
            _print_dut_menu(rms_names, thd_names, distortion_metric)
            continue
        if command == "help":
            print("範例：rms 1 3 5 | thd all | both 2,4,6 | quit")
            continue
        if command not in {"rms", "thd", "both"} or not requested:
            print("無效命令。範例：rms 1 3 5")
            continue

        try:
            if command in {"rms", "both"}:
                selection = _resolve_selection(requested, rms_names, "RMS")
                destination = _next_comparison_path(output_dir, "RMS", distortion_metric)
                save_plot(
                    destination, rms_data, selection, "RMS", "RMS Level Comparison",
                    rms_unit, distortion_metric,
                )
                print(f"已儲存：{destination.resolve()}")
            if command in {"thd", "both"}:
                selection = _resolve_selection(
                    requested, thd_names, distortion_metric
                )
                destination = _next_comparison_path(output_dir, "THD", distortion_metric)
                save_plot(
                    destination, thd_data, selection, "THD",
                    f"{distortion_metric} Comparison", rms_unit, distortion_metric,
                )
                print(f"已儲存：{destination.resolve()}")
        except ValueError as error:
            print(f"錯誤：{error}")


def write_run_notes(
    path: Path,
    input_path: Path,
    rms_names: Sequence[str],
    thd_names: Sequence[str],
    warnings: Sequence[str],
    rms_unit: str,
    distortion_metric: str,
) -> None:
    lines = [
        f"輸入檔案：{input_path.resolve()}",
        f"頻率範圍：{FREQUENCY_RANGE_HZ[0]:g}～{FREQUENCY_RANGE_HZ[1]:g} Hz",
        f"RMS 單位：{rms_unit}",
        f"失真測項：{distortion_metric} (%)",
        f"RMS DUTs ({len(rms_names)}): {', '.join(rms_names)}",
        f"THD DUTs ({len(thd_names)}): {', '.join(thd_names)}",
        "",
        "DUT 名稱配對紀錄：",
        *([f"- {note}" for note in warnings] or ["- 無"]),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# =============================================================================
# 7. 設定驗證與命令列參數
# =============================================================================


def validate_settings() -> None:
    """在讀取大型資料前先檢查使用者設定，提供容易理解的錯誤訊息。"""
    frequency_low, frequency_high = FREQUENCY_RANGE_HZ
    if frequency_low <= 0 or frequency_low >= frequency_high:
        raise ValueError("FREQUENCY_RANGE_HZ 必須是由小到大的兩個正數。")

    for label, axis_range in (("RMS_Y_RANGE", RMS_Y_RANGE), ("THD_Y_RANGE", THD_Y_RANGE)):
        if axis_range is not None and axis_range[0] >= axis_range[1]:
            raise ValueError(f"{label} 必須是由小到大的兩個數值，或設為 None。")

    if RMS_Y_GRID_INTERVAL is not None and RMS_Y_GRID_INTERVAL <= 0:
        raise ValueError("RMS_Y_GRID_INTERVAL 必須大於 0，或設為 None。")
    if THD_Y_SCALE not in {"log", "linear"}:
        raise ValueError("THD_Y_SCALE 只能設為 'log' 或 'linear'。")
    if THD_Y_SCALE == "log" and THD_Y_RANGE is not None and THD_Y_RANGE[0] <= 0:
        raise ValueError("THD 使用對數軸時，THD_Y_RANGE 下限必須大於 0。")

    for label, lsl, usl in (
        ("RMS", RMS_LSL, RMS_USL),
        ("THD", THD_LSL, THD_USL),
    ):
        if lsl is not None and usl is not None and lsl > usl:
            raise ValueError(f"{label}_LSL 不可大於 {label}_USL。")


def validate_frequency_coverage(
    data: dict[str, dict[float, float]],
    label: str,
) -> None:
    """Reject traces that would otherwise create empty CSV rows or plots."""
    missing = [
        name
        for name, trace in data.items()
        if not any(_frequency_in_range(frequency) for frequency in trace)
    ]
    if missing:
        low, high = FREQUENCY_RANGE_HZ
        raise ValueError(
            f"{label} DUT has no data within {low:g}–{high:g} Hz: "
            + ", ".join(missing)
        )


def build_timestamped_output_dir(
    base_output_dir: Path,
    now: datetime | None = None,
) -> Path:
    """在輸出資料夾名稱後加入 13 碼時間標籤。

    例如 2026-08-12 11:47:01.0 會產生：
    rms_thd_output_2608121147010
    """
    current_time = now or datetime.now()
    timestamp = (
        current_time.strftime("%y%m%d%H%M%S")
        + str(current_time.microsecond // 100_000)
    )
    return base_output_dir.with_name(f"{base_output_dir.name}_{timestamp}")


def create_unique_output_dir(
    base_output_dir: Path,
    add_timestamp: bool = True,
    now: datetime | None = None,
) -> Path:
    """原子建立全新輸出資料夾，絕不沿用或覆蓋既有資料夾。

    啟用時間標籤時，先嘗試建立 ``base_YYMMDDHHMMSSd``；若該名稱
    已存在，依序改用 ``_001``、``_002``……。停用時間標籤時也採用
    相同防呆規則，名稱依序為 ``base``、``base_001``、``base_002``……。
    """
    desired = (
        build_timestamped_output_dir(base_output_dir, now)
        if add_timestamp
        else base_output_dir
    )
    candidate = desired
    sequence = 1

    while True:
        try:
            # exist_ok=False 是防覆蓋的核心：只有全新目錄才會成功。
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            candidate = desired.with_name(f"{desired.name}_{sequence:03d}")
            sequence += 1


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="解析 Audio Precision CSV，輸出 RMS / THD / THD+N 數值與曲線圖。",
        epilog=(
            "使用範例：\n"
            "  完整輸出：\n"
            "    python RMS_THD_Analyzer.py RMS_THD.csv -o rms_thd_output\n\n"
            "  先查看 DUT 編號：\n"
            "    python RMS_THD_Analyzer.py RMS_THD.csv --list-duts\n\n"
            "  指定比較圖 DUT（空格或逗號皆可）：\n"
            "    python RMS_THD_Analyzer.py RMS_THD.csv --rms-compare-duts 1 2 3 "
            "--thd-compare-duts 4,5,6\n\n"
            "  只更新比較圖，不重做 CSV / 個別圖：\n"
            "    python RMS_THD_Analyzer.py RMS_THD.csv -o rms_thd_output "
            "--compare-only --rms-compare-duts 1,2,3 --thd-compare-duts 4,5,6\n\n"
            "  互動模式（可連續輸出多組比較圖）：\n"
            "    python RMS_THD_Analyzer.py RMS_THD.csv -o rms_thd_output --interactive\n\n"
            "  不使用時間標籤（若名稱已存在，會自動加流水號）：\n"
            "    python RMS_THD_Analyzer.py RMS_THD.csv -o rms_thd_output --no-timestamp\n\n"
            "預設輸出資料夾會加入 13 碼執行時間，例如 "
            "rms_thd_output_2608121147010；若撞名則加 _001、_002……。\n"
            "為避免誤蓋量測結果，程式不會沿用已存在的輸出資料夾。\n"
            "注意：command 指定的 DUT 會優先於程式設定區的 RMS_COMPARE_DUTS / "
            "THD_COMPARE_DUTS。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input_csv", nargs="?", default=Path("RMS_THD.csv"), type=Path,
        help="AP 匯出的 CSV 路徑（預設：RMS_THD.csv）",
    )
    parser.add_argument(
        "-o", "--output-dir", default=Path("rms_thd_output"), type=Path,
        help="輸出資料夾的基本名稱（預設：rms_thd_output；自動加入時間標籤）",
    )
    parser.add_argument(
        "--rms-compare-duts", "--rms-duts", dest="rms_compare_duts",
        nargs="+", default=None, metavar="DUT",
        help="RMS 比較圖的 DUT 編號或完整名稱；可用空格或逗號分隔",
    )
    parser.add_argument(
        "--thd-compare-duts", "--thd-duts", dest="thd_compare_duts",
        nargs="+", default=None, metavar="DUT",
        help="THD / THD+N 比較圖的 DUT 編號或完整名稱；可用空格或逗號分隔",
    )
    parser.add_argument(
        "--compare-only", action="store_true",
        help="只建立比較圖，不重寫 CSV、個別圖與執行紀錄",
    )
    parser.add_argument(
        "--interactive", action="store_true",
        help="進入互動模式，CSV 解析一次後可連續建立多組比較圖",
    )
    parser.add_argument(
        "--list-duts", action="store_true",
        help="列出 RMS / THD / THD+N DUT 編號後結束，不建立任何檔案",
    )
    parser.add_argument(
        "--no-timestamp", action="store_true",
        help="不加時間標籤；若 -o 路徑已存在，仍會自動建立 _001、_002……新資料夾",
    )
    return parser.parse_args()


# =============================================================================
# 8. 主流程
# =============================================================================


def load_measurements(
    input_path: Path,
) -> tuple[
    dict[str, dict[float, float]],
    dict[str, dict[float, float]],
    list[str],
    str,
    str,
]:
    """解析 CSV、修正 DUT 名稱，並分別回傳 RMS、THD 與配對紀錄。"""
    blocks = parse_ap_csv(input_path)
    if not any(block.kind == "RMS" for block in blocks) or not any(
        block.kind == "THD" for block in blocks
    ):
        raise ValueError(
            "輸入檔案至少需要一個 RMS 區塊，以及一個 THD 或 THD+N 區塊。"
        )
    rms_unit, distortion_metric = validate_measurement_metadata(blocks)
    warnings = reconcile_dut_names(blocks)
    rms_data = build_measurement_map(blocks, "RMS")
    thd_data = build_measurement_map(blocks, "THD")
    validate_frequency_coverage(rms_data, "RMS")
    validate_frequency_coverage(thd_data, distortion_metric)
    return rms_data, thd_data, warnings, rms_unit, distortion_metric


def run() -> None:
    """執行完整工作流程；預期中的檔案/設定錯誤交由 main() 顯示。"""
    args = parse_arguments()
    if not args.input_csv.is_file():
        raise FileNotFoundError(f"找不到輸入 CSV：{args.input_csv}")
    validate_settings()
    rms_data, thd_data, warnings, rms_unit, distortion_metric = load_measurements(
        args.input_csv
    )

    if args.list_duts:
        _print_dut_menu(list(rms_data), list(thd_data), distortion_metric)
        return

    # Command line 優先；未指定時才採用上方使用者設定。
    rms_requested = (
        args.rms_compare_duts
        if args.rms_compare_duts is not None
        else RMS_COMPARE_DUTS
    )
    thd_requested = (
        args.thd_compare_duts
        if args.thd_compare_duts is not None
        else THD_COMPARE_DUTS
    )

    # 在建立輸出資料夾前先驗證選擇，避免錯誤指令留下空資料夾。
    if not args.interactive:
        _resolve_selection(rms_requested, list(rms_data), "RMS")
        _resolve_selection(thd_requested, list(thd_data), distortion_metric)

    output_dir = create_unique_output_dir(
        args.output_dir,
        add_timestamp=ADD_OUTPUT_TIMESTAMP and not args.no_timestamp,
    )
    # 在開始寫檔前顯示實際位置，方便確認執行到的是具防覆蓋功能的版本。
    print(f"全新輸出資料夾：{output_dir.resolve()}")
    print(f"量測格式：RMS ({rms_unit}) / {distortion_metric} (%)")

    _configure_plot_style()

    # compare-only 會跳過這一段，因此既有 CSV 與個別圖不會被重寫。
    if not args.compare_only:
        write_wide_csv(output_dir / "rms_level_values.csv", rms_data)
        distortion_file_token = _distortion_token(distortion_metric).casefold()
        write_wide_csv(output_dir / f"{distortion_file_token}_values.csv", thd_data)
        write_long_csv(
            output_dir / "rms_thd_all_values.csv",
            rms_data, thd_data, rms_unit, distortion_metric,
        )
        if CREATE_ONE_CSV_PER_DUT:
            write_per_dut_csvs(
                output_dir / "data_by_dut", rms_data, thd_data,
                rms_unit, distortion_metric,
            )
        create_individual_plots(
            output_dir / "plots" / "individual", rms_data, thd_data,
            rms_unit, distortion_metric,
        )
        write_run_notes(
            output_dir / "run_notes.txt", args.input_csv,
            list(rms_data), list(thd_data), warnings,
            rms_unit, distortion_metric,
        )

    # 一般模式輸出一組比較圖；互動模式則等待使用者連續選擇。
    if args.interactive:
        run_interactive_comparison(
            output_dir / "plots" / "comparison", rms_data, thd_data,
            rms_unit, distortion_metric,
        )
    else:
        create_comparison_plots(
            output_dir / "plots" / "comparison",
            rms_data, thd_data, rms_requested, thd_requested,
            rms_unit, distortion_metric,
        )

    print(f"完成。RMS DUT：{', '.join(rms_data)}")
    print(f"完成。{distortion_metric} DUT：{', '.join(thd_data)}")
    for warning in warnings:
        print(f"注意：{warning}")
    print(f"輸出資料夾：{output_dir.resolve()}")


def main() -> int:
    """顯示簡潔錯誤訊息；未預期的程式錯誤仍保留 traceback 方便除錯。"""
    try:
        run()
    except (FileNotFoundError, ValueError, OSError) as error:
        print(f"錯誤：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
