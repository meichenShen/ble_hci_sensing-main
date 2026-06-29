"""诊断与统计打印。

包括文件元信息、通道在各帧中的覆盖率、
单通道时间戳间隔分析（CV、估计采样率、大间隔检测）等。
"""

import warnings

import numpy as np

from ble_analysis.plotting import plot_time_intervals


def print_file_info(data, frames):
    """打印文件元数据与帧级时间统计。

    输出版本、保存时间、帧数、首尾帧 index/timestamp、时间跨度与平均帧率。
    无数据时仅打印警告并返回。
    """
    if not data:
        print("⚠️  无数据可显示")
        return

    print("=== 文件信息 ===")
    print(f"版本: {data.get('version', 'N/A')}")
    print(f"保存时间: {data.get('saved_at', 'N/A')}")
    print(f"原始总帧数: {data.get('total_frames', 0)}")
    print(f"保存的帧数: {data.get('saved_frames', 0)}")

    max_frames_param = data.get("max_frames_param")
    if max_frames_param is None:
        print("保存模式: 全部帧")
    else:
        print(f"保存模式: 最近 {max_frames_param} 帧")

    if not frames:
        return

    print(
        f"\n第一帧: index={frames[0]['index']}, timestamp={frames[0]['timestamp_ms']} ms"
    )
    print(
        f"最后一帧: index={frames[-1]['index']}, timestamp={frames[-1]['timestamp_ms']} ms"
    )

    time_span = (frames[-1]["timestamp_ms"] - frames[0]["timestamp_ms"]) / 1000.0
    print(f"时间跨度: {time_span:.2f} 秒")

    if len(frames) > 1:
        intervals = [
            (frames[i]["timestamp_ms"] - frames[i - 1]["timestamp_ms"]) / 1000.0
            for i in range(1, len(frames))
        ]
        if intervals:
            avg_interval = float(np.mean(intervals))
            print(f"平均帧间隔: {avg_interval:.3f} 秒")
            print(f"平均帧率: {1.0 / avg_interval:.2f} 帧/秒")


def _cv_label(cv):
    if cv < 0.1:
        return "均匀"
    if cv < 0.3:
        return "较均匀"
    return "不均匀"


def cv_uniformity_label(cv):
    """根据变异系数 CV 返回中文均匀性描述（均匀 / 较均匀 / 不均匀）。"""
    return _cv_label(cv)


def diagnose_channel_presence(
    frames, channel, max_missing_to_print=10, verbose=True
):
    """诊断指定通道在每一帧中是否存在。

    兼容 int/str 通道 key。缺失帧写入 ``missing_frames``，并统计缺失间隔。

    Parameters
    ----------
    frames : list
        帧列表。
    channel : int or str
        目标通道。
    max_missing_to_print : int
        verbose 模式下最多打印多少条缺失帧记录。
    verbose : bool
        是否打印覆盖率与缺失详情。

    Returns
    -------
    dict
        ``channel``, ``total_frames``, ``frames_with_channel``,
        ``coverage``, ``presence``, ``missing_frames``, ``missing_gaps``。
    """
    from ble_analysis.channels import find_channel_key, resolve_channel

    if not frames:
        result = {
            "total_frames": 0,
            "frames_with_channel": 0,
            "frames_without_channel": 0,
            "coverage": 0.0,
            "presence": [],
            "missing_frames": [],
            "missing_gaps": [],
        }
        if verbose:
            print("⚠️  frames 为空")
        return result

    channel = resolve_channel(frames, channel, verbose=False)
    presence = []
    missing_frames = []

    for i, frame in enumerate(frames):
        channels = frame.get("channels", {})
        matched_key = find_channel_key(channels, channel)
        if matched_key is not None:
            presence.append(True)
        else:
            presence.append(False)
            missing_frames.append(
                {
                    "frame_index": i,
                    "seq": frame.get("index", "N/A"),
                    "timestamp": frame.get("timestamp_ms", "N/A"),
                    "channels_in_frame": list(channels.keys())[:10],
                }
            )

    total_frames = len(frames)
    frames_with_channel = sum(presence)
    frames_without_channel = len(missing_frames)
    coverage = frames_with_channel / total_frames if total_frames else 0.0

    missing_indices = [mf["frame_index"] for mf in missing_frames]
    missing_gaps = []
    if len(missing_indices) > 1:
        missing_gaps = [
            missing_indices[i + 1] - missing_indices[i]
            for i in range(len(missing_indices) - 1)
        ]

    result = {
        "channel": channel,
        "total_frames": total_frames,
        "frames_with_channel": frames_with_channel,
        "frames_without_channel": frames_without_channel,
        "coverage": coverage,
        "presence": presence,
        "missing_frames": missing_frames,
        "missing_gaps": missing_gaps,
    }

    if not verbose:
        return result

    print(f"\n=== 诊断：通道 {channel} 在各帧中的存在情况 ===")
    print(f"总帧数: {total_frames}")
    print(f"包含通道 {channel} 的帧数: {frames_with_channel}")
    print(f"不包含通道 {channel} 的帧数: {frames_without_channel}")
    print(f"通道 {channel} 的覆盖率: {coverage * 100:.1f}%")

    if missing_frames:
        print(f"\n⚠️  前{max_missing_to_print}个缺失通道 {channel} 的帧:")
        print(
            f"{'帧序号':<8} {'序列号':<8} {'时间戳(ms)':<12} {'该帧包含的通道数':<15} {'前几个通道':<30}"
        )
        print("-" * 80)
        for mf in missing_frames[:max_missing_to_print]:
            channels_in_frame = mf["channels_in_frame"]
            print(
                f"{mf['frame_index']:<8} {mf['seq']:<8} {mf['timestamp']:<12} "
                f"{len(channels_in_frame):<15} {str(channels_in_frame):<30}"
            )

        if missing_gaps:
            print("\n缺失帧的间隔分析:")
            print(f"  连续缺失: {sum(1 for g in missing_gaps if g == 1)} 次")
            print(f"  平均间隔: {np.mean(missing_gaps):.1f} 帧")
            print(f"  最大间隔: {max(missing_gaps)} 帧")
            print(f"  最小间隔: {min(missing_gaps)} 帧")

    return result


def analyze_time_intervals(
    timestamps_ms, plot=False, save_path=None, verbose=True
):
    """分析时间戳间隔并估计采样率。

    - CV < 0.1：均匀；CV < 0.3：较均匀；否则不均匀。
    - 大间隔定义：间隔 > 2 × 平均间隔。
    - ``estimated_sampling_rate = 1 / mean_interval``（Hz）。

    Parameters
    ----------
    timestamps_ms : array-like
        毫秒时间戳（通常为单通道有效帧的时间戳）。
    plot : bool
        是否绘制间隔序列图与直方图。
    save_path : path-like, optional
        存图路径。
    verbose : bool
        是否打印统计与滤波影响提示。

    Returns
    -------
    dict
        含 ``time_intervals_sec``, ``mean_interval``, ``cv``,
        ``estimated_sampling_rate``, ``large_gap_indices`` 等。
    """
    empty = {
        "time_intervals_ms": np.array([]),
        "time_intervals_sec": np.array([]),
        "mean_interval": np.nan,
        "std_interval": np.nan,
        "min_interval": np.nan,
        "max_interval": np.nan,
        "cv": np.nan,
        "estimated_sampling_rate": np.nan,
        "large_gap_indices": np.array([], dtype=int),
        "n_large_gaps": 0,
    }

    timestamps_ms = np.asarray(timestamps_ms, dtype=float)
    if len(timestamps_ms) < 2:
        if verbose:
            print("⚠️  数据点不足，无法分析时间间隔")
        return empty

    time_intervals_ms = np.diff(timestamps_ms)
    time_intervals_sec = time_intervals_ms / 1000.0

    mean_interval = float(np.mean(time_intervals_sec))
    std_interval = float(np.std(time_intervals_sec))
    min_interval = float(np.min(time_intervals_sec))
    max_interval = float(np.max(time_intervals_sec))
    cv = std_interval / mean_interval if mean_interval > 0 else 0.0
    estimated_sampling_rate = 1.0 / mean_interval if mean_interval > 0 else np.nan

    large_gaps = time_intervals_sec > mean_interval * 2
    large_gap_indices = np.where(large_gaps)[0]
    n_large_gaps = int(np.sum(large_gaps))

    result = {
        "time_intervals_ms": time_intervals_ms,
        "time_intervals_sec": time_intervals_sec,
        "mean_interval": mean_interval,
        "std_interval": std_interval,
        "min_interval": min_interval,
        "max_interval": max_interval,
        "cv": cv,
        "estimated_sampling_rate": estimated_sampling_rate,
        "large_gap_indices": large_gap_indices,
        "n_large_gaps": n_large_gaps,
    }

    if verbose:
        print("=== 时间戳间隔分析（关键！）===")
        print("时间间隔统计（秒）:")
        print(f"  平均间隔: {mean_interval:.3f} 秒")
        print(f"  标准差: {std_interval:.3f} 秒")
        print(f"  最小间隔: {min_interval:.3f} 秒")
        print(f"  最大间隔: {max_interval:.3f} 秒")
        print(f"  变异系数 (CV): {cv:.3f} ({_cv_label(cv)})")
        print(f"\n估计采样率: {estimated_sampling_rate:.3f} Hz")

        if n_large_gaps > 0:
            print(f"\n⚠️  发现 {n_large_gaps} 个较大的时间间隔（> 2倍平均间隔）")
            print("   前5个大间隔的位置和大小:")
            for idx in large_gap_indices[:5]:
                ratio = time_intervals_sec[idx] / mean_interval
                print(
                    f"     位置 {idx}: {time_intervals_sec[idx]:.3f} 秒 "
                    f"(平均值的 {ratio:.1f} 倍)"
                )
        else:
            print("\n✓ 时间间隔相对均匀，没有发现异常大的间隔")

        print("\n💡 关于滤波的影响:")
        if cv < 0.1:
            print(f"   ✓ 时间间隔非常均匀（CV={cv:.3f}），滤波效果应该很好")
            print("   ✓ 滤波函数假设等间隔采样，这个假设基本满足")
        elif cv < 0.3:
            print(f"   ⚠️  时间间隔较均匀（CV={cv:.3f}），滤波效果应该还可以")
            print("   ⚠️  但可能存在轻微的时间对齐问题")
        else:
            print(f"   ⚠️  时间间隔不均匀（CV={cv:.3f}），可能影响滤波效果")
            print("   ⚠️  特别是高通滤波，因为它依赖于采样率参数")
            print("   ⚠️  建议：使用实际的平均采样率，或考虑重采样到均匀网格")

    if plot:
        plot_time_intervals(result, save_path=save_path, show=True)

    return result


def print_time_interval_summary(channel, n_points, total_frames, time_info):
    """在时间间隔分析后打印简短中文总结（点数差异、CV、建议采样率）。"""
    cv = time_info.get("cv", np.nan)
    estimated_sampling_rate = time_info.get("estimated_sampling_rate", np.nan)
    cv_text = "未知" if np.isnan(cv) else f"{cv:.3f}"

    print("\n💡 总结:")
    print(f"   1. 数据点数量 ({n_points}) 少于总帧数 ({total_frames}) 是因为")
    print(f"      不是所有帧都包含通道 {channel} 的数据（这是正常的数据特征）")
    if not np.isnan(cv):
        uniformity = _cv_label(cv)
        print(f"   2. 时间间隔{uniformity}（CV={cv_text}），这可能会影响滤波效果")
    if not np.isnan(estimated_sampling_rate):
        print(
            f"   3. 实际采样率是 {estimated_sampling_rate:.3f} Hz，"
            "而不是固定的2.0 Hz"
        )
        print("   4. 建议：在后续滤波中使用实际采样率，而不是固定的2.0 Hz")
