"""分段呼吸分析 pipeline。

按原始帧 index 切分数据，对每段执行 median → highpass → bandpass，
并进行 apnea 检测与 BPM/IE 滑窗估计。供 ``glb_cs_segment_breath_analysis.ipynb`` 使用。

段落配置 ``segment_config`` 示例::

    {"1a": {"start": 131, "end": 244, "type": "breath", "bpm_gt": 8.6, "ie_gt": 1.0}}

录制好的场景（数据路径 + 分段）见 ``config/scenarios/*.json``，
通过 ``ble_analysis.scenarios.load_scenario`` 加载。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

from ble_analysis.channels import find_channel_key, resolve_channel
from ble_analysis.filters import apply_filter_pipeline

STANDARD_VARIABLES = [
    "amplitudes",
    "phases",
    "local_amplitudes",
    "remote_amplitudes",
    "local_phases",
    "remote_phases",
]

VAR_FIELD_MAP = {
    "amplitudes": "amplitude",
    "phases": "phase",
    "local_amplitudes": "local_amplitude",
    "remote_amplitudes": "remote_amplitude",
    "local_phases": "local_phase",
    "remote_phases": "remote_phase",
}


@dataclass
class FilterParams:
    """分段滤波参数：中值窗口、高通/带通截止频率与阶数。"""
    median_window: int = 3
    highpass_cutoff: float = 0.05
    highpass_order: int = 1
    bandpass_lowcut: float = 0.1
    bandpass_highcut: float = 0.35
    bandpass_order: int = 2


@dataclass
class BreathMetricParams:
    """滑窗呼吸指标参数：呼吸频带、窗长（秒）与步长（秒）。"""
    breath_freq_low: float = 0.1
    breath_freq_high: float = 0.35
    window_length_sec: float = 20.0
    step_length_sec: float = 1.0


def estimate_sampling_rate_from_frames(frames, max_frames: int = 100) -> float:
    """从前若干帧的时间戳估算平均采样率（Hz），不足时返回 2.0。"""
    if len(frames) < 2:
        return 2.0
    timestamps = [f.get("timestamp_ms", 0) for f in frames[:max_frames]]
    if len(timestamps) < 2:
        return 2.0
    avg_interval = float(np.mean(np.diff(timestamps))) / 1000.0
    return 1.0 / avg_interval if avg_interval > 0 else 2.0


def extract_segment_data(
    frames,
    segment_config: Dict[str, dict],
    channel,
    variables: Sequence[str],
    *,
    estimated_fs: Optional[float] = None,
    verbose: bool = True,
) -> Dict[str, Optional[dict]]:
    """按 segment_config 从 frames 中提取各段落数据。

    apnea 段会在 index 范围前后各扩展约 10 秒 context（按 estimated_fs 换算）。
    仅保留指定 channel 且落在范围内的帧。
    """
    if estimated_fs is None:
        estimated_fs = estimate_sampling_rate_from_frames(frames)

    channel = resolve_channel(frames, channel, verbose=False)
    segment_data: Dict[str, Optional[dict]] = {}

    for seg_name in sorted(segment_config.keys()):
        seg = segment_config[seg_name]
        if isinstance(seg, dict):
            start_idx = seg["start"]
            end_idx = seg["end"]
            seg_type = seg.get("type", "breath")
        else:
            start_idx, end_idx = seg
            seg_type = "breath"

        if seg_type == "apnea":
            context_samples = int(round(10.0 * estimated_fs))
            actual_start_idx = max(0, start_idx - context_samples)
            actual_end_idx = end_idx + context_samples
        else:
            actual_start_idx = start_idx
            actual_end_idx = end_idx

        seg_data_dict: dict = {
            "indices": [],
            "timestamps_ms": [],
            "start_index": start_idx,
            "end_index": end_idx,
            "original_start": start_idx,
            "original_end": end_idx,
            "segment_type": seg_type,
            "ie_gt": seg.get("ie_gt") if isinstance(seg, dict) else None,
            "bpm_gt": seg.get("bpm_gt") if isinstance(seg, dict) else None,
            "apnea_gt_sec": seg.get("apnea_gt_sec") if isinstance(seg, dict) else None,
        }
        for var_name in variables:
            seg_data_dict[var_name] = []

        for frame in frames:
            frame_index = frame.get("index", -1)
            if not (actual_start_idx <= frame_index <= actual_end_idx):
                continue
            channels = frame.get("channels", {})
            matched = find_channel_key(channels, channel)
            if matched is None:
                continue
            ch_data = channels[matched]
            seg_data_dict["indices"].append(frame_index)
            seg_data_dict["timestamps_ms"].append(frame.get("timestamp_ms", 0))
            for var_name in variables:
                field_name = VAR_FIELD_MAP.get(var_name, var_name)
                seg_data_dict[var_name].append(ch_data.get(field_name, 0))

        if len(seg_data_dict["indices"]) == 0:
            segment_data[seg_name] = None
            if verbose:
                print(f"⚠️  段落 {seg_name}: 无数据 (index {actual_start_idx}-{actual_end_idx})")
            continue

        seg_data_dict["indices"] = np.array(seg_data_dict["indices"])
        seg_data_dict["timestamps_ms"] = np.array(seg_data_dict["timestamps_ms"])
        seg_data_dict["n_points"] = len(seg_data_dict["indices"])
        for var_name in variables:
            seg_data_dict[var_name] = np.array(seg_data_dict[var_name])
        segment_data[seg_name] = seg_data_dict
        if verbose:
            print(
                f"✓ {seg_name} ({seg_type}): {seg_data_dict['n_points']} pts "
                f"[{seg_data_dict['indices'][0]}-{seg_data_dict['indices'][-1]}]"
            )

    if verbose:
        n_ok = sum(1 for v in segment_data.values() if v is not None)
        print(f"✓ 提取 {n_ok}/{len(segment_config)} 段 | ch={channel} | fs≈{estimated_fs:.2f} Hz")
    return segment_data


def process_segments(
    segment_data: Dict[str, Optional[dict]],
    sampling_rate: float,
    variables: Sequence[str],
    filter_params: Optional[FilterParams] = None,
    *,
    verbose: bool = True,
) -> Dict[str, Optional[dict]]:
    """对每段数据依次应用中值、高通、带通滤波，写入 segment_processed。"""
    fp = filter_params or FilterParams()
    segment_processed: Dict[str, Optional[dict]] = {}

    for seg_name in sorted(segment_data.keys()):
        seg_data = segment_data[seg_name]
        if seg_data is None:
            segment_processed[seg_name] = None
            continue
        if seg_data["n_points"] < fp.median_window:
            segment_processed[seg_name] = None
            if verbose:
                print(f"⚠️  {seg_name}: 数据点过少，跳过")
            continue

        seg_proc: dict = {}
        for var_name in variables:
            if var_name not in seg_data:
                continue
            var_data = seg_data[var_name]
            median_filtered = apply_filter_pipeline(
                var_data, pipeline=[{"type": "median", "window_size": fp.median_window}]
            )
            highpass_filtered = apply_filter_pipeline(
                median_filtered,
                fs=sampling_rate,
                pipeline=[
                    {"type": "highpass", "cutoff": fp.highpass_cutoff, "order": fp.highpass_order}
                ],
            )
            bandpass_filtered = apply_filter_pipeline(
                highpass_filtered,
                fs=sampling_rate,
                pipeline=[
                    {
                        "type": "bandpass",
                        "lowcut": fp.bandpass_lowcut,
                        "highcut": fp.bandpass_highcut,
                        "order": fp.bandpass_order,
                    }
                ],
            )
            seg_proc[var_name] = {
                "original": var_data,
                "median_filtered": median_filtered,
                "highpass_filtered": highpass_filtered,
                "bandpass_filtered": bandpass_filtered,
            }

        seg_proc["metadata"] = {
            "start_index": seg_data["start_index"],
            "end_index": seg_data["end_index"],
            "n_points": seg_data["n_points"],
            "indices": seg_data["indices"],
            "timestamps_ms": seg_data["timestamps_ms"],
            "sampling_rate": sampling_rate,
            "segment_type": seg_data.get("segment_type", "breath"),
            "original_start": seg_data.get("original_start", seg_data["start_index"]),
            "original_end": seg_data.get("original_end", seg_data["end_index"]),
            "ie_gt": seg_data.get("ie_gt"),
            "bpm_gt": seg_data.get("bpm_gt"),
            "apnea_gt_sec": seg_data.get("apnea_gt_sec"),
        }
        segment_processed[seg_name] = seg_proc

    if verbose:
        n_ok = sum(1 for v in segment_processed.values() if v is not None)
        print(f"✓ 滤波完成 {n_ok} 段 @ {sampling_rate:.2f} Hz")
    return segment_processed


def apnea_est_with_context(
    x, fs, apnea_start, apnea_end, ctx_sec=10.0, win_sec=2.0, q=0.2
):
    """在 apnea 核区间周围取 context，用 context RMS 分位数作阈值，估计低能量时长（秒）。

    用于 ``detect_apnea_segments``；信号 x 通常为 median_filtered、未 bandpass。
    返回 (apnea_est_sec, debug_dict)。
    """
    x = np.asarray(x, float).reshape(-1)
    n = len(x)
    s, e = int(apnea_start), int(apnea_end)
    if e <= s or s < 0 or e > n:
        return np.nan, {"reason": "bad segment indices"}

    ctx = int(round(ctx_sec * fs))
    w0, w1 = max(0, s - ctx), min(n, e + ctx)
    xw = x[w0:w1]
    if len(xw) < 5:
        return np.nan, {"reason": "window too short"}

    win = max(1, int(round(win_sec * fs)))
    baseline = uniform_filter1d(xw, size=win, mode="nearest")
    x0 = xw - baseline
    rms = np.sqrt(uniform_filter1d(x0 * x0, size=win, mode="nearest"))

    core_s, core_e = s - w0, e - w0
    mask_ctx = np.ones(len(rms), dtype=bool)
    mask_ctx[core_s:core_e] = False
    rms_ctx = rms[mask_ctx]
    if len(rms_ctx) == 0:
        return np.nan, {"reason": "no context points"}

    thresh = float(np.quantile(rms_ctx, q))
    low_core = rms < thresh
    low_core = low_core[core_s:core_e]
    apnea_est_sec = float(np.sum(low_core) / fs)
    dbg = {
        "w0": w0,
        "w1": w1,
        "core_s": s,
        "core_e": e,
        "thresh": thresh,
        "low_core_ratio": float(np.mean(low_core)) if len(low_core) else np.nan,
    }
    return apnea_est_sec, dbg


def detect_apnea_segments(
    segment_processed: Dict[str, Optional[dict]],
    *,
    q: float = 0.4,
    verbose: bool = True,
) -> int:
    """对 segment_type 为 apnea 的段落执行暂停检测，结果写入 seg_proc["apnea_analysis"]。

    Returns
    -------
    int
        成功处理的 apnea 段数量。
    """
    count = 0
    for seg_name in sorted(segment_processed.keys()):
        seg_proc = segment_processed[seg_name]
        if seg_proc is None:
            continue
        metadata = seg_proc.get("metadata", {})
        if metadata.get("segment_type") != "apnea":
            continue

        var_for_apnea = next(
            (v for v in ("amplitudes", "remote_amplitudes", "local_amplitudes") if v in seg_proc),
            None,
        )
        if var_for_apnea is None:
            continue

        median_filtered = seg_proc[var_for_apnea]["median_filtered"]
        fs = metadata.get("sampling_rate", 2.0)
        original_start = metadata.get("original_start", metadata.get("start_index", 0))
        original_end = metadata.get("original_end", metadata.get("end_index", len(median_filtered)))
        indices = metadata.get("indices", np.arange(len(median_filtered)))

        if len(indices) > 0:
            start_mask = indices == original_start
            end_mask = indices == original_end
            if np.any(start_mask) and np.any(end_mask):
                apnea_start_idx = int(np.where(start_mask)[0][0])
                apnea_end_idx = int(np.where(end_mask)[0][0])
            else:
                apnea_start_idx = int(np.argmin(np.abs(indices - original_start)))
                apnea_end_idx = int(np.argmin(np.abs(indices - original_end)))
        else:
            apnea_start_idx, apnea_end_idx = 0, len(median_filtered)

        apnea_est_sec, dbg = apnea_est_with_context(
            median_filtered, fs, apnea_start_idx, apnea_end_idx, q=q
        )

        apnea_gt_sec = metadata.get("apnea_gt_sec")
        timestamps_ms = metadata.get("timestamps_ms")
        if apnea_gt_sec is not None:
            apnea_actual_sec = float(apnea_gt_sec)
        elif timestamps_ms is not None and len(timestamps_ms) > 0:
            start_time_idx = int(np.argmin(np.abs(indices - original_start)))
            end_time_idx = int(np.argmin(np.abs(indices - original_end)))
            apnea_actual_sec = (
                timestamps_ms[end_time_idx] - timestamps_ms[start_time_idx]
            ) / 1000.0
        else:
            apnea_actual_sec = (original_end - original_start + 1) / fs if fs > 0 else np.nan

        result = {
            "apnea_est_sec": apnea_est_sec,
            "apnea_gt_sec": apnea_gt_sec,
            "apnea_actual_sec": apnea_actual_sec,
            "abs_err_sec": abs(apnea_est_sec - apnea_actual_sec)
            if not np.isnan(apnea_est_sec)
            else np.nan,
            "rel_err": (
                abs(apnea_est_sec - apnea_actual_sec) / apnea_actual_sec
                if (not np.isnan(apnea_est_sec) and apnea_actual_sec > 0)
                else np.nan
            ),
            "variable_used": var_for_apnea,
            "debug": dbg,
        }
        seg_proc["apnea_analysis"] = result
        count += 1
        if verbose and not np.isnan(apnea_est_sec):
            print(
                f"✓ {seg_name} apnea: est={apnea_est_sec:.1f}s gt={apnea_actual_sec:.1f}s "
                f"rel={result['rel_err']*100:.1f}%"
                if not np.isnan(result["rel_err"])
                else f"✓ {seg_name} apnea: est={apnea_est_sec:.1f}s"
            )

    if verbose:
        print(f"✓ apnea 检测 {count} 段")
    return count


def _estimate_breathing_freq_hz(bandpass_slice, sampling_rate, low_hz, high_hz):
    if len(bandpass_slice) < 4:
        return np.nan
    windowed = bandpass_slice * np.hanning(len(bandpass_slice))
    fft_power = np.abs(np.fft.rfft(windowed)) ** 2
    fft_freq = np.fft.rfftfreq(len(windowed), 1.0 / sampling_rate)
    freq_mask = (fft_freq >= low_hz) & (fft_freq <= high_hz)
    if not np.any(freq_mask):
        return np.nan
    freq_indices = np.where(freq_mask)[0]
    max_freq_idx = freq_indices[np.argmax(fft_power[freq_mask])]
    return float(fft_freq[max_freq_idx])


def _estimate_ie_ratio(bandpass_slice, sampling_rate):
    if len(bandpass_slice) < 10:
        return np.nan
    dt = 1.0 / sampling_rate
    min_distance = max(1, int(sampling_rate * 0.3))
    try:
        peaks, _ = find_peaks(bandpass_slice, distance=min_distance)
        valleys, _ = find_peaks(-bandpass_slice, distance=min_distance)
        if len(peaks) >= 2 and len(valleys) >= 1:
            all_points = sorted(
                [("valley", v) for v in valleys] + [("peak", p) for p in peaks],
                key=lambda x: x[1],
            )
            insp_times, exp_times = [], []
            for i in range(len(all_points) - 1):
                curr_type, curr_idx = all_points[i]
                next_type, next_idx = all_points[i + 1]
                dt_seg = (next_idx - curr_idx) * dt
                if curr_type == "valley" and next_type == "peak":
                    insp_times.append(dt_seg)
                elif curr_type == "peak" and next_type == "valley":
                    exp_times.append(dt_seg)
            if insp_times and exp_times:
                avg_insp, avg_exp = np.mean(insp_times), np.mean(exp_times)
                if avg_exp > 0:
                    return avg_insp / avg_exp
    except Exception:
        pass
    return np.nan


def _sliding_window_indices(signal_length, window_samples, step_samples):
    if signal_length <= 0 or window_samples <= 0:
        return []
    if signal_length < window_samples:
        return [0]
    starts, s = [], 0
    while s + window_samples <= signal_length:
        starts.append(s)
        s += step_samples
    return starts


def estimate_segment_breath_metrics(
    segment_processed: Dict[str, Optional[dict]],
    segment_config: Optional[Dict[str, dict]] = None,
    variables: Optional[Sequence[str]] = None,
    metric_params: Optional[BreathMetricParams] = None,
    *,
    verbose: bool = True,
) -> None:
    """20 s 窗 / 1 s 步滑窗估计 BPM 与 IE，并与 GT 计算相对误差（写入 breathing_analysis）。"""
    mp = metric_params or BreathMetricParams()
    segment_config = segment_config or {}

    for seg_name in sorted(segment_processed.keys()):
        seg_proc = segment_processed[seg_name]
        if seg_proc is None:
            continue
        metadata = seg_proc["metadata"]
        fs = metadata["sampling_rate"]
        window_samples = int(round(mp.window_length_sec * fs))
        step_samples = int(round(mp.step_length_sec * fs))
        vars_to_analyze = list(variables or [])
        if not vars_to_analyze:
            vars_to_analyze = [k for k in seg_proc if k not in ("metadata", "breathing_analysis", "apnea_analysis")]

        for var_name in vars_to_analyze:
            if var_name not in seg_proc:
                continue
            bandpass_data = seg_proc[var_name]["bandpass_filtered"]
            if len(bandpass_data) < 10:
                continue

            starts = _sliding_window_indices(len(bandpass_data), window_samples, step_samples)
            bpm_per_win, ie_per_win, freq_hz_per_win = [], [], []
            for st in starts:
                sl = bandpass_data[st : min(st + window_samples, len(bandpass_data))]
                f_hz = _estimate_breathing_freq_hz(
                    sl, fs, mp.breath_freq_low, mp.breath_freq_high
                )
                freq_hz_per_win.append(f_hz)
                bpm_per_win.append(f_hz * 60.0 if not np.isnan(f_hz) else np.nan)
                ie_per_win.append(_estimate_ie_ratio(sl, fs))

            bpm_arr = np.asarray(bpm_per_win, dtype=float)
            ie_arr = np.asarray(ie_per_win, dtype=float)
            bpm_est = float(np.nanmean(bpm_arr))
            ie_est = float(np.nanmean(ie_arr))
            breathing_freq = float(np.nanmean(np.asarray(freq_hz_per_win, dtype=float)))

            ie_gt = metadata.get("ie_gt")
            bpm_gt = metadata.get("bpm_gt")
            sc = segment_config.get(seg_name, {})
            if bpm_gt is None and isinstance(sc, dict):
                bpm_gt = sc.get("bpm_gt")
            if ie_gt is None and isinstance(sc, dict):
                ie_gt = sc.get("ie_gt")

            bpm_rel_per_win = np.array(
                [
                    abs(b - bpm_gt) / bpm_gt
                    if (bpm_gt and bpm_gt > 0 and not np.isnan(b))
                    else np.nan
                    for b in bpm_arr
                ],
                dtype=float,
            )
            ie_rel_per_win = np.array(
                [
                    abs(x - ie_gt) / ie_gt
                    if (ie_gt and ie_gt > 0 and not np.isnan(x))
                    else np.nan
                    for x in ie_arr
                ],
                dtype=float,
            )

            def _mean_std(a):
                v = a[~np.isnan(a)]
                if v.size == 0:
                    return np.nan, np.nan
                return float(np.mean(v)), float(np.std(v, ddof=1)) if v.size > 1 else 0.0

            bpm_rel_err_mean, bpm_rel_err_std = _mean_std(bpm_rel_per_win)
            ie_rel_err_mean, ie_rel_err_std = _mean_std(ie_rel_per_win)

            if "breathing_analysis" not in seg_proc:
                seg_proc["breathing_analysis"] = {}
            seg_proc["breathing_analysis"][var_name] = {
                "breathing_freq": breathing_freq,
                "breathing_rate": bpm_est,
                "ie_ratio": ie_est,
                "ie_gt": ie_gt,
                "bpm_gt": bpm_gt,
                "ie_rel_err": ie_rel_err_mean,
                "bpm_rel_err": bpm_rel_err_mean,
                "ie_rel_err_std": ie_rel_err_std,
                "bpm_rel_err_std": bpm_rel_err_std,
                "bpm_per_window": bpm_arr,
                "ie_per_window": ie_arr,
                "n_windows": len(starts),
            }

        if verbose and "breathing_analysis" in seg_proc:
            for var_name, analysis in seg_proc["breathing_analysis"].items():
                rate = analysis.get("breathing_rate", np.nan)
                ie = analysis.get("ie_ratio", np.nan)
                bpm_gt = analysis.get("bpm_gt")
                bpm_rel = analysis.get("bpm_rel_err")
                parts = [f"{var_name}: BPM={rate:.2f}" if not np.isnan(rate) else f"{var_name}: BPM=N/A"]
                if not np.isnan(ie):
                    parts.append(f"IE={ie:.3f}")
                if bpm_gt and bpm_rel is not None and not np.isnan(bpm_rel):
                    parts.append(f"rel BPM={bpm_rel*100:.1f}% (GT {bpm_gt})")
                print(f"  {seg_name} | " + " | ".join(parts))

    if verbose:
        print("✓ 呼吸指标估计完成")


def save_segment_processed(
    segment_processed: Dict[str, Optional[dict]],
    output_path: Path,
    *,
    verbose: bool = True,
) -> Path:
    """将 segment_processed 序列化保存为 .npy（allow_pickle）。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_data = {}
    for seg_name in sorted(segment_processed.keys()):
        seg_proc = segment_processed[seg_name]
        if seg_proc is None:
            continue
        save_data[seg_name] = {
            k: v
            for k, v in seg_proc.items()
            if k in ("metadata", "breathing_analysis", "apnea_analysis")
            or isinstance(v, dict)
        }
    np.save(output_path, save_data, allow_pickle=True)
    if verbose:
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"✓ 已保存 {output_path.name} ({len(save_data)} 段, {size_mb:.2f} MB)")
    return output_path


def run_segment_breath_analysis(
    frames,
    segment_config: Dict[str, dict],
    channel,
    variables: Sequence[str],
    *,
    sampling_rate: Optional[float] = None,
    filter_params: Optional[FilterParams] = None,
    metric_params: Optional[BreathMetricParams] = None,
    save_path: Optional[Path] = None,
    verbose: bool = True,
) -> dict:
    """分段呼吸分析完整 pipeline。

    依次执行：``extract_segment_data`` → ``process_segments`` →
    ``detect_apnea_segments`` → ``estimate_segment_breath_metrics``，
    可选保存 ``segment_processed`` 到 ``.npy``。

    Parameters
    ----------
    frames : list
        由 ``load_ble_frames`` 得到的帧列表。
    segment_config : dict
        段落名 → ``{start, end, type, bpm_gt?, ie_gt?, apnea_gt_sec?}``。
    channel : int or str
        分析通道。
    variables : sequence of str
        如 ``["remote_amplitudes"]``。
    sampling_rate : float, optional
        滤波用采样率；None 时从帧时间戳估算。
    save_path : Path, optional
        保存 ``segment_processed`` 的路径。

    Returns
    -------
    dict
        ``segment_data``, ``segment_processed``, ``sampling_rate``, ``channel``。
    """
    if sampling_rate is None:
        sampling_rate = estimate_sampling_rate_from_frames(frames)

    segment_data = extract_segment_data(
        frames, segment_config, channel, variables, estimated_fs=sampling_rate, verbose=verbose
    )
    segment_processed = process_segments(
        segment_data, sampling_rate, variables, filter_params, verbose=verbose
    )
    detect_apnea_segments(segment_processed, verbose=verbose)
    estimate_segment_breath_metrics(
        segment_processed,
        segment_config=segment_config,
        variables=variables,
        metric_params=metric_params,
        verbose=verbose,
    )

    if save_path is not None:
        save_segment_processed(segment_processed, save_path, verbose=verbose)

    return {
        "segment_data": segment_data,
        "segment_processed": segment_processed,
        "sampling_rate": sampling_rate,
        "channel": resolve_channel(frames, channel, verbose=False),
    }
