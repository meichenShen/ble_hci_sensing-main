"""通道相关操作。

CS 数据中每帧的 ``channels`` 字典 key 可能是 int 或 str；
本模块负责枚举、匹配，以及从全部帧中提取单通道时间序列。
"""

import warnings

import numpy as np


def _channel_sort_key(channel):
    if isinstance(channel, str) and channel.isdigit():
        return (0, int(channel))
    if isinstance(channel, (int, float)):
        return (0, int(channel))
    return (1, str(channel))


def get_available_channels(frames):
    """返回所有帧中出现过的通道号列表（已排序）。

    排序规则：数字通道按数值升序，非数字 key 排在后面。
    """
    all_channels = set()
    for frame in frames:
        all_channels.update(frame.get("channels", {}).keys())
    return sorted(all_channels, key=_channel_sort_key)


def find_channel_key(channels, channel):
    """在 channels 字典中查找与给定通道等价的 key。

    依次尝试原值、``str(channel)``、``int(channel)``，兼容 int/str 混用。

    Returns
    -------
    key or None
        匹配到的 dict key；未找到返回 None。
    """
    candidates = [channel]
    try:
        candidates.append(str(channel))
    except (ValueError, TypeError):
        pass
    try:
        candidates.append(int(channel))
    except (ValueError, TypeError):
        pass

    seen = set()
    for ch_key in candidates:
        if ch_key in seen:
            continue
        seen.add(ch_key)
        if ch_key in channels:
            return ch_key
    return None


def resolve_channel(frames, channel, verbose=True):
    """解析通道号；不存在时可回退到第一个可用通道。

    Parameters
    ----------
    frames : list
        帧列表。
    channel : int or str
        期望分析的通道号。
    verbose : bool
        是否打印匹配/回退信息。

    Returns
    -------
    channel
        实际使用的通道 key（int 或 str）。
    """
    available = get_available_channels(frames)
    if not available:
        return channel

    matched = find_channel_key({ch: True for ch in available}, channel)
    if matched is not None:
        if verbose:
            print(f"✓ 找到通道: {matched} (类型: {type(matched).__name__})")
        return matched

    if verbose:
        print(f"⚠️  警告: 通道 {channel} 在数据中不存在")
        print(f"建议使用以下通道之一: {available[:10]}")
        print(f"自动使用通道: {available[0]}")
    return available[0]


def extract_channel_series(frames, channel, verbose=True):
    """从全部帧中提取单通道幅值/相位时间序列。

    仅收集**包含该通道**的帧；缺失帧记录在 ``missing_frames`` 中，不报错。
    ``time_sec`` 以该通道第一个有效时间戳为 0 点。

    Returns
    -------
    dict
        含 ``channel``, ``indices``, ``timestamps_ms``, ``time_sec``,
        ``amplitudes``, ``phases``, ``local_amplitudes``, ``remote_amplitudes``,
        ``presence``, ``missing_frames``。
    """
    empty = {
        "channel": channel,
        "indices": np.array([], dtype=int),
        "timestamps_ms": np.array([], dtype=float),
        "time_sec": np.array([], dtype=float),
        "amplitudes": np.array([], dtype=float),
        "phases": np.array([], dtype=float),
        "local_amplitudes": np.array([], dtype=float),
        "remote_amplitudes": np.array([], dtype=float),
        "presence": [],
        "missing_frames": [],
    }

    if not frames:
        if verbose:
            warnings.warn("frames 为空，无法提取通道数据")
        return empty

    channel = resolve_channel(frames, channel, verbose=verbose)

    amplitudes = []
    phases = []
    local_amplitudes = []
    remote_amplitudes = []
    indices = []
    timestamps_ms = []
    presence = []
    missing_frames = []

    for i, frame in enumerate(frames):
        channels = frame.get("channels", {})
        ch_data = None
        matched_key = find_channel_key(channels, channel)
        if matched_key is not None:
            ch_data = channels[matched_key]

        if ch_data:
            presence.append(True)
            amplitudes.append(ch_data.get("amplitude", 0))
            phases.append(ch_data.get("phase", 0))
            local_amplitudes.append(ch_data.get("local_amplitude", 0))
            remote_amplitudes.append(ch_data.get("remote_amplitude", 0))
            indices.append(frame.get("index", i))
            timestamps_ms.append(frame.get("timestamp_ms", 0))
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

    timestamps_ms_arr = np.array(timestamps_ms, dtype=float)
    if len(timestamps_ms_arr) > 0:
        time_sec = (timestamps_ms_arr - timestamps_ms_arr[0]) / 1000.0
    else:
        time_sec = np.array([], dtype=float)

    series = {
        "channel": channel,
        "indices": np.array(indices, dtype=int),
        "timestamps_ms": timestamps_ms_arr,
        "time_sec": time_sec,
        "amplitudes": np.array(amplitudes, dtype=float),
        "phases": np.array(phases, dtype=float),
        "local_amplitudes": np.array(local_amplitudes, dtype=float),
        "remote_amplitudes": np.array(remote_amplitudes, dtype=float),
        "presence": presence,
        "missing_frames": missing_frames,
    }

    total_frames = len(frames)
    if verbose:
        print(f"\n✓ 提取通道 {channel} 的数据")
        print(f"  数据点数: {len(amplitudes)} (从 {total_frames} 帧中提取)")
        if len(amplitudes) == 0:
            print("  ⚠️  警告: 没有提取到任何数据！")
            print("  可能的原因:")
            print("  1. 该通道在所有帧中都不存在")
            print("  2. 通道号类型不匹配（整数 vs 字符串）")
            print("  请检查上面的可用通道列表，并修改 channel 变量")
        else:
            print(
                f"  幅值范围: {np.min(amplitudes):.2f} - {np.max(amplitudes):.2f}"
            )
            print(f"  幅值均值: {np.mean(amplitudes):.2f}")
            print(f"  幅值标准差: {np.std(amplitudes):.2f}")
            print(
                f"\n💡 说明: 数据点数量 ({len(amplitudes)}) 少于总帧数 ({total_frames}) 是正常的，"
            )
            print(f"   因为不是所有帧都包含通道 {channel} 的数据。")

    return series
