"""高层探索工作流。

``run_cs_exploration`` 将加载、通道提取、时间诊断、基础绘图合并为一步，
并输出一行摘要，供 ``glb_cs_load_and_explore.ipynb`` 使用。
"""

from pathlib import Path

import numpy as np

from ble_analysis.channels import extract_channel_series, get_available_channels
from ble_analysis.data import load_ble_frames
from ble_analysis.diagnostics import (
    _cv_label,
    analyze_time_intervals,
    diagnose_channel_presence,
    print_file_info,
)
from ble_analysis.plotting import plot_channel_amplitude_phase


def _compact_file_summary(data, frames):
    if not data or not frames:
        return "无数据"
    span = (frames[-1]["timestamp_ms"] - frames[0]["timestamp_ms"]) / 1000.0
    return (
        f"v{data.get('version', '?')} | {len(frames)} frames | "
        f"span {span:.0f}s | saved {data.get('saved_at', '?')[:19]}"
    )


def run_cs_exploration(
    filepath,
    channel=2,
    *,
    figures_dir=None,
    verbose=False,
    save_figures=True,
    show_plots=True,
    show_first_frame=False,
):
    """一键完成 CS 单通道数据探索。

    流程：加载 → 通道存在性诊断 → 提取序列 → 时间间隔分析 → 幅值/相位图。
    默认 ``verbose=False``，仅打印一行摘要。

    Parameters
    ----------
    filepath : str or Path
        JSON/JSONL 帧文件。
    channel : int or str, optional
        目标通道，默认 2。
    figures_dir : Path, optional
        若提供且 ``save_figures=True``，保存时间间隔图与幅值/相位图。
    verbose, save_figures, show_plots, show_first_frame : bool
        控制打印、存图、弹窗与首帧摘要。

    Returns
    -------
    dict
        ``data``, ``frames``, ``channel``, ``series``, ``time_info``,
        ``actual_sampling_rate``, ``presence_info``, ``available_channels``。
    """
    filepath = Path(filepath)
    if figures_dir is not None:
        figures_dir = Path(figures_dir)
        figures_dir.mkdir(parents=True, exist_ok=True)

    data, frames = load_ble_frames(filepath, verbose=verbose)
    if data is None:
        print(f"✗ 加载失败: {filepath}")
        return {"data": None, "frames": [], "series": None, "time_info": {}}

    if verbose:
        print_file_info(data, frames)

    available = get_available_channels(frames)
    presence_info = diagnose_channel_presence(frames, channel, verbose=verbose)
    channel = presence_info["channel"]
    series = extract_channel_series(frames, channel, verbose=verbose)

    save_path_intervals = None
    save_path_amp_phase = None
    if save_figures and figures_dir is not None:
        save_path_intervals = figures_dir / f"channel_{channel}_time_intervals.png"
        save_path_amp_phase = figures_dir / f"channel_{channel}_amp_phase.png"

    time_info = analyze_time_intervals(
        series["timestamps_ms"],
        plot=show_plots,
        save_path=save_path_intervals,
        verbose=verbose,
    )

    plot_channel_amplitude_phase(
        series,
        channel=channel,
        save_path=save_path_amp_phase,
        show=show_plots,
    )

    actual_sampling_rate = time_info.get("estimated_sampling_rate", np.nan)
    if np.isnan(actual_sampling_rate):
        actual_sampling_rate = 2.0

    cv = time_info.get("cv", np.nan)
    cv_text = f"{cv:.3f} ({_cv_label(cv)})" if not np.isnan(cv) else "N/A"
    fig_note = ""
    if save_figures and figures_dir is not None:
        fig_note = f" → {figures_dir.name}/channel_{channel}_*.png"

    print(
        f"✓ {filepath.name} | {_compact_file_summary(data, frames)} | "
        f"ch{channel}: {len(series['amplitudes'])} pts | fs≈{actual_sampling_rate:.2f} Hz | "
        f"CV={cv_text}{fig_note}"
    )

    if show_first_frame and frames:
        from ble_analysis.channels import find_channel_key

        first = frames[0]
        chs = first.get("channels", {})
        print(
            f"  首帧 index={first.get('index')} ts={first.get('timestamp_ms')}ms "
            f"channels={len(chs)} | 可用通道 {len(available)}"
        )

    return {
        "data": data,
        "frames": frames,
        "channel": channel,
        "available_channels": available,
        "presence_info": presence_info,
        "series": series,
        "time_info": time_info,
        "actual_sampling_rate": float(actual_sampling_rate),
    }
