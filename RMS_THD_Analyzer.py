
r"""Audio Precision RMS / THD CSV 分析工具（單檔版）。

主要功能：
1. 解析 AP 匯出的多區塊 RMS Level / THD Ratio CSV。
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
from collections import Counter, defaultdict
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
RMS_USL = None                 # dBSPL，例如 110.0
RMS_LSL = None                 # dBSPL，例如 75.0
THD_USL = None                 # %，例如 10.0
THD_LSL = None                 # %，通常不設定

# 1-2. 圖形顯示及 CSV 輸出的頻率範圍。
FREQUENCY_RANGE_HZ = (100.0, 10_000.0)

# 1-3. Y 軸範圍與格線；設為 None 代表自動。
RMS_Y_RANGE = (20.0, 120.0)   # dBSPL；若要顯示 50～60，改為 (50.0, 60.0)
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

# AP 有時把 RMS 名稱匯出成 Ch1，但相同量測順序的 THD 保留 DUT 名稱。
# True：RMS / THD 區塊數相同時，依量測順序自動配對名稱。
AUTO_MATCH_GENERIC_CHANNEL_NAMES = True

# =============================================================================
# 2. 資料結構與共用常數（通常不需修改）
# =============================================================================


@dataclass
class MeasurementBlock:
    kind: str                 # "RMS" or "THD"
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
        is_summary = title.casefold().startswith("summary:")
        if not is_summary and "THD Ratio" in title:
            kind = "THD"
        elif not is_summary and "RMS Level" in title:
            kind = "RMS"
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

        unit = rows[units_row][1] if len(rows[units_row]) > 1 else ("%" if kind == "THD" else "dBSPL")
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
        blocks.append(MeasurementBlock(kind, name, unit, points, block_number))
        index = max(cursor, index + 1)

    if not blocks:
        raise ValueError("No 'RMS Level' or 'THD Ratio' data blocks were found in the CSV.")
    return blocks


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
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or "DUT"


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
) -> None:
    """輸出長表：每列為 DUT + 頻率，並包含上下限與 PASS/FAIL。"""
    all_names = list(dict.fromkeys([*rms_data, *thd_data]))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "DUT_ID", "Frequency_Hz", "RMS_Level_dBSPL", "THD_Percent",
            "RMS_LSL_dBSPL", "RMS_USL_dBSPL", "RMS_Result",
            "THD_LSL_Percent", "THD_USL_Percent", "THD_Result",
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
) -> None:
    """每個 DUT 各輸出一份 RMS 與 THD CSV，並將 DUT 名稱寫入量測欄名。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    all_names = list(dict.fromkeys([*rms_data, *thd_data]))
    for name in all_names:
        path = output_dir / f"{_safe_filename(name)}.csv"
        frequencies = sorted({*rms_data.get(name, {}), *thd_data.get(name, {})})
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "Frequency_Hz", f"{name}_RMS_Level_dBSPL", f"{name}_THD_Percent",
                "RMS_Result", "THD_Result",
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


def _configure_axis(ax: plt.Axes, measurement: str) -> None:
    low_frequency, high_frequency = FREQUENCY_RANGE_HZ
    ax.set_xscale("log")
    ax.set_xlim(low_frequency, high_frequency)
    ticks = [tick for tick in AP_FREQUENCY_TICKS if low_frequency <= tick <= high_frequency]
    ax.set_xticks(ticks)
    ax.xaxis.set_major_formatter(FuncFormatter(_frequency_tick_label))
    ax.set_xlabel("Frequency (Hz)")

    if measurement == "RMS":
        ax.set_ylabel("RMS Level (dBSPL)")
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
        ax.set_ylabel("THD Ratio (%)")
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
) -> None:
    """儲存一張 RMS 或 THD 圖，可包含一條或多條 DUT 曲線。"""
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for name in selected_names:
        x_values, y_values = _filtered_xy(data[name], measurement)
        ax.plot(x_values, y_values, linewidth=LINE_WIDTH, label=name)

    _draw_limits(ax, measurement)
    _configure_axis(ax, measurement)
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
) -> None:
    if not CREATE_INDIVIDUAL_PLOTS:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in rms_data:
        save_plot(
            output_dir / f"{_safe_filename(name)}_RMS_Level.png",
            rms_data, [name], "RMS", f"RMS Level — {name}",
        )
    for name in thd_data:
        save_plot(
            output_dir / f"{_safe_filename(name)}_THD.png",
            thd_data, [name], "THD", f"THD Ratio — {name}",
        )


def create_comparison_plots(
    output_dir: Path,
    rms_data: dict[str, dict[float, float]],
    thd_data: dict[str, dict[float, float]],
    rms_requested: Sequence[str] | None,
    thd_requested: Sequence[str] | None,
    rms_filename: str = "RMS_Level_Comparison.png",
    thd_filename: str = "THD_Comparison.png",
) -> tuple[list[str], list[str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rms_selection = _resolve_selection(rms_requested, list(rms_data), "RMS")
    thd_selection = _resolve_selection(thd_requested, list(thd_data), "THD")
    if rms_selection:
        save_plot(
            output_dir / rms_filename,
            rms_data, rms_selection, "RMS", "RMS Level Comparison",
        )
    if thd_selection:
        save_plot(
            output_dir / thd_filename,
            thd_data, thd_selection, "THD", "THD Ratio Comparison",
        )
    return rms_selection, thd_selection


def create_plots(
    output_dir: Path,
    rms_data: dict[str, dict[float, float]],
    thd_data: dict[str, dict[float, float]],
    rms_requested: Sequence[str] | None,
    thd_requested: Sequence[str] | None,
) -> None:
    _configure_plot_style()
    create_individual_plots(output_dir / "individual", rms_data, thd_data)
    create_comparison_plots(
        output_dir / "comparison", rms_data, thd_data,
        rms_requested, thd_requested,
    )


def _print_dut_menu(
    rms_names: Sequence[str],
    thd_names: Sequence[str],
) -> None:
    print("\n可選擇的 RMS DUT：")
    for number, name in enumerate(rms_names, start=1):
        print(f"  {number}: {name}")
    print("可選擇的 THD DUT：")
    for number, name in enumerate(thd_names, start=1):
        print(f"  {number}: {name}")


def _next_comparison_path(output_dir: Path, measurement: str) -> Path:
    stem = "RMS_Level_Comparison" if measurement == "RMS" else "THD_Comparison"
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
) -> None:
    """CSV 只解析一次，在同一執行階段連續建立多組比較圖。"""
    rms_names = list(rms_data)
    thd_names = list(thd_data)
    output_dir.mkdir(parents=True, exist_ok=True)
    _print_dut_menu(rms_names, thd_names)
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
            _print_dut_menu(rms_names, thd_names)
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
                destination = _next_comparison_path(output_dir, "RMS")
                save_plot(destination, rms_data, selection, "RMS", "RMS Level Comparison")
                print(f"已儲存：{destination.resolve()}")
            if command in {"thd", "both"}:
                selection = _resolve_selection(requested, thd_names, "THD")
                destination = _next_comparison_path(output_dir, "THD")
                save_plot(destination, thd_data, selection, "THD", "THD Ratio Comparison")
                print(f"已儲存：{destination.resolve()}")
        except ValueError as error:
            print(f"錯誤：{error}")


def write_run_notes(
    path: Path,
    input_path: Path,
    rms_names: Sequence[str],
    thd_names: Sequence[str],
    warnings: Sequence[str],
) -> None:
    lines = [
        f"輸入檔案：{input_path.resolve()}",
        f"頻率範圍：{FREQUENCY_RANGE_HZ[0]:g}～{FREQUENCY_RANGE_HZ[1]:g} Hz",
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
        description="解析 Audio Precision CSV，輸出 RMS / THD 數值與曲線圖。",
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
        help="THD 比較圖的 DUT 編號或完整名稱；可用空格或逗號分隔",
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
        help="列出 RMS / THD DUT 編號後結束，不建立任何檔案",
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
) -> tuple[dict[str, dict[float, float]], dict[str, dict[float, float]], list[str]]:
    """解析 CSV、修正 DUT 名稱，並分別回傳 RMS、THD 與配對紀錄。"""
    blocks = parse_ap_csv(input_path)
    warnings = reconcile_dut_names(blocks)
    rms_data = build_measurement_map(blocks, "RMS")
    thd_data = build_measurement_map(blocks, "THD")
    if not rms_data or not thd_data:
        raise ValueError("輸入檔案至少需要一個 RMS 區塊與一個 THD 區塊。")
    return rms_data, thd_data, warnings


def run() -> None:
    """執行完整工作流程；預期中的檔案/設定錯誤交由 main() 顯示。"""
    args = parse_arguments()
    if not args.input_csv.is_file():
        raise FileNotFoundError(f"找不到輸入 CSV：{args.input_csv}")
    validate_settings()
    rms_data, thd_data, warnings = load_measurements(args.input_csv)

    if args.list_duts:
        _print_dut_menu(list(rms_data), list(thd_data))
        return

    output_dir = create_unique_output_dir(
        args.output_dir,
        add_timestamp=ADD_OUTPUT_TIMESTAMP and not args.no_timestamp,
    )
    # 在開始寫檔前顯示實際位置，方便確認執行到的是具防覆蓋功能的版本。
    print(f"全新輸出資料夾：{output_dir.resolve()}")
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

    _configure_plot_style()

    # compare-only 會跳過這一段，因此既有 CSV 與個別圖不會被重寫。
    if not args.compare_only:
        write_wide_csv(output_dir / "rms_level_values.csv", rms_data)
        write_wide_csv(output_dir / "thd_values.csv", thd_data)
        write_long_csv(output_dir / "rms_thd_all_values.csv", rms_data, thd_data)
        if CREATE_ONE_CSV_PER_DUT:
            write_per_dut_csvs(output_dir / "data_by_dut", rms_data, thd_data)
        create_individual_plots(
            output_dir / "plots" / "individual", rms_data, thd_data,
        )
        write_run_notes(
            output_dir / "run_notes.txt", args.input_csv,
            list(rms_data), list(thd_data), warnings,
        )

    # 一般模式輸出一組比較圖；互動模式則等待使用者連續選擇。
    if args.interactive:
        run_interactive_comparison(
            output_dir / "plots" / "comparison", rms_data, thd_data,
        )
    else:
        create_comparison_plots(
            output_dir / "plots" / "comparison",
            rms_data, thd_data, rms_requested, thd_requested,
        )

    print(f"完成。RMS DUT：{', '.join(rms_data)}")
    print(f"完成。THD DUT：{', '.join(thd_data)}")
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
