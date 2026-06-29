"""Matplotlib 绘图辅助。

提供统一的 notebook 绘图风格，以及幅值/相位、时间间隔等常用图。
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def setup_plot_style():
    """设置 BLE 分析 notebook 的 matplotlib 默认样式（图尺寸、网格、字号、存图 DPI）。"""
    plt.rcParams.update(
        {
            "figure.figsize": (12, 6),
            "axes.grid": True,
            "grid.alpha": 0.3,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "lines.linewidth": 0.8,
            "font.size": 10,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
        }
    )


def _ensure_parent_dir(save_path):
    if save_path is not None:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)


def plot_channel_amplitude_phase(series, channel=None, save_path=None, show=True):
    """绘制单通道幅值与相位随时间变化的双子图。

    Parameters
    ----------
    series : dict
        ``extract_channel_series`` 的返回值。
    channel : int, str, or None
        图标题用通道号；None 时使用 series["channel"]。
    save_path, show
        存图路径与是否 ``plt.show()``。

    Returns
    -------
    (fig, axes) or (None, None)
        无数据时返回 (None, None) 并打印警告。
    """
    amplitudes = series.get("amplitudes", np.array([]))
    phases = series.get("phases", np.array([]))
    time_sec = series.get("time_sec", np.array([]))
    channel = channel if channel is not None else series.get("channel", "?")

    if len(amplitudes) == 0:
        print("⚠️  无法绘图: 没有数据可显示")
        return None, None

    fig, axes = plt.subplots(2, 1, figsize=(12, 6))

    axes[0].plot(time_sec, amplitudes, "b-", linewidth=0.5, alpha=0.7)
    axes[0].set_xlabel("Time (s)")
    axes[0].set_ylabel("Amplitude")
    axes[0].set_title(f"Channel {channel} Amplitude over Time")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(time_sec, phases, "r-", linewidth=0.5, alpha=0.7)
    axes[1].set_xlabel("Time (s)")
    axes[1].set_ylabel("Phase (rad)")
    axes[1].set_title(f"Channel {channel} Phase over Time")
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()

    if save_path is not None:
        _ensure_parent_dir(save_path)
        fig.savefig(save_path)

    if show:
        plt.show()
    else:
        plt.close(fig)

    return fig, axes


def plot_time_intervals(time_info, save_path=None, show=True):
    """绘制时间间隔序列图与直方图（输入为 ``analyze_time_intervals`` 的返回值）。"""
    time_intervals_sec = time_info.get("time_intervals_sec", np.array([]))
    mean_interval = time_info.get("mean_interval", np.nan)

    if len(time_intervals_sec) == 0:
        print("⚠️  无法绘图: 时间间隔数据不足")
        return None, None

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    axes[0].plot(time_intervals_sec, "b-", linewidth=0.8, alpha=0.7)
    axes[0].axhline(
        y=mean_interval,
        color="r",
        linestyle="--",
        label=f"Mean Interval: {mean_interval:.3f}s",
    )
    axes[0].set_xlabel("Sample Index")
    axes[0].set_ylabel("Time Interval (s)")
    axes[0].set_title("Time Interval Sequence")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].hist(time_intervals_sec, bins=30, edgecolor="black", alpha=0.7)
    axes[1].axvline(
        x=mean_interval,
        color="r",
        linestyle="--",
        label=f"Mean: {mean_interval:.3f}s",
    )
    axes[1].set_xlabel("Time Interval (s)")
    axes[1].set_ylabel("Frequency")
    axes[1].set_title("Time Interval Distribution Histogram")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()

    if save_path is not None:
        _ensure_parent_dir(save_path)
        fig.savefig(save_path)

    if show:
        plt.show()
    else:
        plt.close(fig)

    return fig, axes
