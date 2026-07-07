"""Liu et al. 2016 baselines for BLE CS breathing BPM estimation.

Two methods live in this module and are intentionally kept separate:

``liu_2016_paper``
    Strict reproduction of Liu et al. 2016's CFR-amplitude workflow:
    Hampel -> interpolation -> db4 wavelet, per-tone FFT peak +/- 1 IFFT
    phase-slope estimation, ``pr=A/RMSE`` periodicity weighting, modified
    Z-score outlier removal, and weighted median fusion.

``liu_eta_rho_adapted``
    Existing BLE-adapted baseline using repository-specific eta/rho quality
    scores and dominant-tone fallback. It is useful for BLE experiments, but
    it is not a strict reproduction of Liu et al. 2016.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ble_analysis.chfusion import (
    ChFusionConfig,
    _energy_ratio,
    _seg_bpm_stats,
    _weighted_median,
)
from ble_analysis.segments import BreathMetricParams, FilterParams, _sliding_window_indices

try:
    import pywt
except ImportError:  # pragma: no cover - exercised only when dependency is absent.
    pywt = None

MODAL_LIU_VARIABLES: Tuple[str, ...] = (
    "remote_amplitudes",
    "local_amplitudes",
    "phases",
)

__all__ = [
    "Liu2016PaperConfig",
    "estimate_fft_phase_slope_bpm",
    "score_sinusoid_periodicity",
    "modified_z_score_filter",
    "weighted_median_frequency",
    "preprocess_liu_2016_paper_series",
    "estimate_liu_2016_paper_window",
    "run_liu_2016_paper_benchmark",
    "estimate_liu_eta_rho_adapted_window_bpms",
    "run_liu_eta_rho_adapted_benchmark",
    "estimate_liu_style_window_bpms",
    "estimate_liu_style_segment",
    "run_liu_2016_benchmark",
    "MODAL_LIU_VARIABLES",
    "_gather_liu_modal_window_data",
]


@dataclass
class Liu2016PaperConfig:
    """Configuration for the strict Liu 2016 paper reproduction.

    The default modified Z-score scale follows the Liu 2016 PDF formula
    (0.7645), even though the common robust-statistics constant is 0.6745.
    """

    breath_freq_low: float = 0.1
    breath_freq_high: float = 0.35
    window_length_sec: float = 20.0
    step_length_sec: float = 1.0
    zscore_scale: float = 0.7645
    zscore_threshold: float = 3.5
    hampel_window_sec: float = 1.0
    hampel_n_sigma: float = 3.0
    wavelet: str = "db4"
    wavelet_level: int = 4
    eps: float = 1e-12


def _variable_field_name(variable: str) -> str:
    return {
        "amplitudes": "amplitude",
        "phases": "phase",
        "local_amplitudes": "local_amplitude",
        "remote_amplitudes": "remote_amplitude",
    }.get(variable, variable)


def _hampel_replace(values: np.ndarray, window_size: int, n_sigma: float) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return values.copy()
    if window_size % 2 == 0:
        window_size += 1
    window_size = max(3, window_size)
    half = window_size // 2
    out = values.copy()
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        w = values[lo:hi]
        med = float(np.nanmedian(w))
        mad = float(np.nanmedian(np.abs(w - med)))
        sigma = 1.4826 * mad
        if sigma > 0 and abs(values[i] - med) > n_sigma * sigma:
            out[i] = med
    return out


def preprocess_liu_2016_paper_series(
    timestamps_ms: Sequence[float],
    values: Sequence[float],
    cfg: Optional[Liu2016PaperConfig] = None,
) -> dict:
    """Apply Liu-style raw preprocessing to one tone amplitude sequence.

    The strict path uses raw per-tone amplitudes and applies Hampel outlier
    replacement, linear interpolation to a uniform grid, and four-level db4
    approximation reconstruction. If the sequence cannot support the requested
    wavelet level, no lower level is silently substituted.
    """
    cfg = cfg or Liu2016PaperConfig()
    t_ms = np.asarray(timestamps_ms, dtype=float)
    x = np.asarray(values, dtype=float)
    mask = np.isfinite(t_ms) & np.isfinite(x)
    t_ms = t_ms[mask]
    x = x[mask]
    if len(t_ms) < 4:
        return {
            "valid": False,
            "skip_reason": "too_few_samples",
            "preprocessing_mode": "raw_liu_style",
        }

    order = np.argsort(t_ms)
    t_ms = t_ms[order]
    x = x[order]
    uniq_mask = np.concatenate([[True], np.diff(t_ms) > 0])
    t_ms = t_ms[uniq_mask]
    x = x[uniq_mask]
    if len(t_ms) < 4:
        return {
            "valid": False,
            "skip_reason": "too_few_unique_timestamps",
            "preprocessing_mode": "raw_liu_style",
        }

    time_sec = (t_ms - t_ms[0]) / 1000.0
    dt = np.diff(time_sec)
    mean_dt = float(np.mean(dt))
    if mean_dt <= cfg.eps:
        return {
            "valid": False,
            "skip_reason": "bad_timestamps",
            "preprocessing_mode": "raw_liu_style",
        }
    fs = 1.0 / mean_dt

    hampel_window = max(3, int(round(cfg.hampel_window_sec * fs)))
    hampel_filtered = _hampel_replace(x, hampel_window, cfg.hampel_n_sigma)

    uniform_time = np.arange(time_sec[0], time_sec[-1] + mean_dt / 2.0, mean_dt)
    if len(uniform_time) < 4:
        return {
            "valid": False,
            "skip_reason": "too_few_uniform_samples",
            "preprocessing_mode": "raw_liu_style",
        }
    resampled = np.interp(uniform_time, time_sec, hampel_filtered)

    if pywt is None:
        return {
            "valid": False,
            "skip_reason": "missing_pywavelets",
            "preprocessing_mode": "raw_liu_style",
        }
    wavelet = pywt.Wavelet(cfg.wavelet)
    max_level = pywt.dwt_max_level(len(resampled), wavelet.dec_len)
    if max_level < cfg.wavelet_level:
        return {
            "valid": False,
            "skip_reason": "wavelet_level_insufficient",
            "fs": fs,
            "n_samples": int(len(resampled)),
            "max_wavelet_level": int(max_level),
            "preprocessing_mode": "raw_liu_style",
        }

    coeffs = pywt.wavedec(resampled, wavelet, level=cfg.wavelet_level, mode="symmetric")
    approx_only = [coeffs[0]] + [np.zeros_like(c) for c in coeffs[1:]]
    wavelet_filtered = pywt.waverec(approx_only, wavelet, mode="symmetric")[: len(resampled)]

    return {
        "valid": True,
        "skip_reason": "",
        "time_sec": uniform_time,
        "values": np.asarray(wavelet_filtered, dtype=float),
        "fs": float(fs),
        "hampel_filtered": hampel_filtered,
        "resampled": resampled,
        "max_wavelet_level": int(max_level),
        "preprocessing_mode": "raw_liu_style",
        "n_samples": int(len(wavelet_filtered)),
    }


def estimate_fft_phase_slope_bpm(
    signal: Sequence[float],
    fs: float,
    cfg: Optional[Liu2016PaperConfig] = None,
) -> dict:
    """Estimate one tone's breathing frequency using Liu's FFT/IFFT refinement.

    The full complex FFT is used. Only the positive-frequency peak bin and its
    two adjacent bins are retained before inverse FFT. Negative conjugate bins
    are intentionally not mirrored: Liu describes a complex time-domain signal
    whose unwrapped phase is linear; mirroring would make the signal mostly real
    and remove the analytic narrowband phase behavior.
    """
    cfg = cfg or Liu2016PaperConfig()
    x = np.asarray(signal, dtype=float)
    if len(x) < 4 or fs <= 0 or not np.all(np.isfinite(x)):
        return {"valid": False, "freq_hz": np.nan, "bpm": np.nan, "skip_reason": "bad_signal"}
    x0 = x - np.mean(x)
    n = len(x0)
    fft_vals = np.fft.fft(x0)
    freqs = np.fft.fftfreq(n, d=1.0 / fs)
    pos_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
    if not np.any(pos_mask):
        return {"valid": False, "freq_hz": np.nan, "bpm": np.nan, "skip_reason": "empty_band"}
    pos_indices = np.where(pos_mask)[0]
    peak_bin = int(pos_indices[np.argmax(np.abs(fft_vals[pos_indices]))])

    narrow = np.zeros_like(fft_vals, dtype=complex)
    keep = [k for k in (peak_bin - 1, peak_bin, peak_bin + 1) if 0 <= k < n and freqs[k] > 0]
    if not keep:
        return {"valid": False, "freq_hz": np.nan, "bpm": np.nan, "skip_reason": "no_bins_kept"}
    narrow[keep] = fft_vals[keep]
    complex_signal = np.fft.ifft(narrow)
    amp = np.abs(complex_signal)
    if np.max(amp) <= cfg.eps:
        return {"valid": False, "freq_hz": np.nan, "bpm": np.nan, "skip_reason": "zero_narrowband"}
    phase = np.unwrap(np.angle(complex_signal))
    t = np.arange(n, dtype=float) / fs
    slope, intercept = np.polyfit(t, phase, 1)
    freq_hz = float(slope / (2.0 * np.pi))
    if freq_hz < 0:
        freq_hz = abs(freq_hz)
    valid = cfg.breath_freq_low <= freq_hz <= cfg.breath_freq_high
    return {
        "valid": bool(valid and np.isfinite(freq_hz)),
        "freq_hz": freq_hz if np.isfinite(freq_hz) else np.nan,
        "bpm": 60.0 * freq_hz if np.isfinite(freq_hz) else np.nan,
        "fft_peak_freq_hz": float(freqs[peak_bin]),
        "peak_bin": peak_bin,
        "kept_bins": keep,
        "phase_slope": float(slope),
        "phase_intercept": float(intercept),
        "skip_reason": "" if valid else "phase_slope_out_of_band",
    }


def score_sinusoid_periodicity(
    signal: Sequence[float],
    fs: float,
    freq_hz: float,
    cfg: Optional[Liu2016PaperConfig] = None,
) -> dict:
    """Compute Liu's periodicity level ``pr=A/RMSE`` for one tone.

    Liu fits ``A sin(2*pi*f*t + phi) + D`` using nonlinear optimization.
    Since ``f`` has already been estimated and is fixed here, the equivalent
    deterministic least-squares form is ``a sin(2*pi*f*t) + b cos(2*pi*f*t) + D``.
    """
    cfg = cfg or Liu2016PaperConfig()
    x = np.asarray(signal, dtype=float)
    if len(x) < 4 or fs <= 0 or not np.isfinite(freq_hz) or freq_hz <= 0:
        return {"valid": False, "amplitude": 0.0, "rmse": np.nan, "pr": 0.0}
    t = np.arange(len(x), dtype=float) / fs
    sin_col = np.sin(2.0 * np.pi * freq_hz * t)
    cos_col = np.cos(2.0 * np.pi * freq_hz * t)
    design = np.column_stack([sin_col, cos_col, np.ones_like(t)])
    coeffs, *_ = np.linalg.lstsq(design, x, rcond=None)
    if not np.all(np.isfinite(coeffs)):
        return {"valid": False, "amplitude": 0.0, "rmse": np.nan, "pr": 0.0}
    a, b, offset = [float(v) for v in coeffs]
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        fit = design @ coeffs
    if not np.all(np.isfinite(fit)):
        return {"valid": False, "amplitude": 0.0, "rmse": np.nan, "pr": 0.0}
    rmse = float(np.sqrt(np.mean((fit - x) ** 2)))
    amplitude = float(np.sqrt(a * a + b * b))
    pr = amplitude / (rmse + cfg.eps)
    return {
        "valid": bool(np.isfinite(pr)),
        "amplitude": amplitude,
        "rmse": rmse,
        "pr": float(pr) if np.isfinite(pr) else 0.0,
        "phase": float(np.arctan2(b, a)),
        "offset": offset,
    }


def modified_z_score_filter(
    freqs_hz: Sequence[float],
    cfg: Optional[Liu2016PaperConfig] = None,
) -> dict:
    """Remove frequency-candidate outliers using Liu's modified Z-score test."""
    cfg = cfg or Liu2016PaperConfig()
    freqs = np.asarray(freqs_hz, dtype=float)
    finite = np.isfinite(freqs)
    z = np.full_like(freqs, np.nan, dtype=float)
    mask = finite.copy()
    if np.sum(finite) == 0:
        return {"mask": mask, "z_scores": z, "median": np.nan, "mad": np.nan}
    med = float(np.nanmedian(freqs[finite]))
    mad = float(np.nanmedian(np.abs(freqs[finite] - med)))
    if mad <= cfg.eps:
        z[finite] = 0.0
        mask = finite
    else:
        z[finite] = cfg.zscore_scale * (freqs[finite] - med) / mad
        mask = finite & (np.abs(z) <= cfg.zscore_threshold)
    return {
        "mask": mask,
        "z_scores": z,
        "median": med,
        "mad": mad,
        "zscore_scale": cfg.zscore_scale,
        "threshold": cfg.zscore_threshold,
    }


def weighted_median_frequency(
    freqs_hz: Sequence[float],
    pr_weights: Sequence[float],
    mask: Sequence[bool],
    cfg: Optional[Liu2016PaperConfig] = None,
) -> float:
    """Fuse surviving tone frequencies with Liu's pr-weighted median."""
    cfg = cfg or Liu2016PaperConfig()
    freqs = np.asarray(freqs_hz, dtype=float)
    weights = np.asarray(pr_weights, dtype=float)
    keep = np.asarray(mask, dtype=bool) & np.isfinite(freqs)
    if weights.shape != freqs.shape:
        weights = np.ones_like(freqs)
    weights = np.where(np.isfinite(weights) & (weights > 0), weights, 0.0)
    keep &= np.isfinite(weights)
    if np.sum(keep) == 0:
        return float("nan")
    vals = freqs[keep]
    w = weights[keep]
    if np.sum(w) <= cfg.eps:
        w = np.ones_like(vals)
    order = np.argsort(vals)
    vals = vals[order]
    w = w[order]
    cdf = np.cumsum(w) / (np.sum(w) + cfg.eps)
    return float(vals[np.searchsorted(cdf, 0.5, side="left")])


def estimate_liu_2016_paper_window(
    window_data: np.ndarray,
    fs: float,
    cfg: Optional[Liu2016PaperConfig] = None,
) -> dict:
    """Estimate one window with the strict Liu 2016 frequency/pr/median flow."""
    cfg = cfg or Liu2016PaperConfig()
    data = np.asarray(window_data, dtype=float)
    if data.ndim == 1:
        data = data[:, None]
    if data.ndim != 2 or data.shape[0] < 4 or data.shape[1] == 0:
        return {"valid": False, "bpm": np.nan, "freq_hz": np.nan, "skip_reason": "bad_window"}
    n_tones = data.shape[1]
    freqs = np.full(n_tones, np.nan, dtype=float)
    bpms = np.full(n_tones, np.nan, dtype=float)
    pr = np.zeros(n_tones, dtype=float)
    for i in range(n_tones):
        est = estimate_fft_phase_slope_bpm(data[:, i], fs, cfg)
        if not est.get("valid", False):
            continue
        freqs[i] = est["freq_hz"]
        bpms[i] = est["bpm"]
        score = score_sinusoid_periodicity(data[:, i], fs, freqs[i], cfg)
        pr[i] = score["pr"] if score.get("valid", False) else 0.0
    zinfo = modified_z_score_filter(freqs, cfg)
    mask = zinfo["mask"]
    freq_final = weighted_median_frequency(freqs, pr, mask, cfg)
    keep = np.asarray(mask, dtype=bool) & np.isfinite(freqs)
    weights = np.zeros_like(pr)
    if np.any(keep):
        kept_pr = np.where(pr[keep] > 0, pr[keep], 0.0)
        if np.sum(kept_pr) <= cfg.eps:
            weights[keep] = 1.0 / np.sum(keep)
        else:
            weights[keep] = kept_pr / np.sum(kept_pr)
    return {
        "valid": bool(np.isfinite(freq_final)),
        "freq_hz": freq_final,
        "bpm": 60.0 * freq_final if np.isfinite(freq_final) else np.nan,
        "freqs_hz": freqs,
        "bpms": bpms,
        "pr": pr,
        "weights": weights,
        "z_scores": zinfo["z_scores"],
        "valid_mask": mask,
        "n_tones": int(n_tones),
        "n_kept": int(np.sum(keep)),
        "outlier_frac": float(1.0 - np.sum(keep) / max(1, np.sum(np.isfinite(freqs)))),
        "mean_pr": float(np.mean(pr[keep])) if np.any(keep) else np.nan,
        "skip_reason": "" if np.isfinite(freq_final) else "no_valid_fused_frequency",
    }


def _channel_sort_key(channel: Any) -> Tuple[int, str]:
    if isinstance(channel, str) and channel.isdigit():
        return (0, f"{int(channel):06d}")
    if isinstance(channel, (int, np.integer)):
        return (0, f"{int(channel):06d}")
    return (1, str(channel))


def _extract_raw_segment_tones(
    frames,
    segment_config: Dict[str, dict],
    seg_name: str,
    variable: str,
) -> Tuple[Dict[Any, Tuple[np.ndarray, np.ndarray]], dict]:
    seg = segment_config[seg_name]
    field = _variable_field_name(variable)
    start = seg["start"]
    end = seg["end"]
    by_ch: Dict[Any, Tuple[List[float], List[float]]] = {}
    for frame in frames:
        idx = frame.get("index", -1)
        if not (start <= idx <= end):
            continue
        ts = frame.get("timestamp_ms")
        if ts is None:
            continue
        for ch, ch_data in frame.get("channels", {}).items():
            if field not in ch_data:
                continue
            t_list, x_list = by_ch.setdefault(ch, ([], []))
            t_list.append(float(ts))
            x_list.append(float(ch_data.get(field, np.nan)))
    arrays = {
        ch: (np.asarray(t, dtype=float), np.asarray(x, dtype=float))
        for ch, (t, x) in by_ch.items()
        if len(t) >= 4
    }
    metadata = {
        "segment_type": seg.get("type", "breath"),
        "bpm_gt": seg.get("bpm_gt"),
        "start_index": start,
        "end_index": end,
    }
    return arrays, metadata


def _preprocess_raw_segment_matrix(
    frames,
    segment_config: Dict[str, dict],
    seg_name: str,
    variable: str,
    cfg: Liu2016PaperConfig,
) -> dict:
    raw_tones, metadata = _extract_raw_segment_tones(frames, segment_config, seg_name, variable)
    cols: List[np.ndarray] = []
    labels: List[Any] = []
    diag_rows: List[dict] = []
    fs_values: List[float] = []
    for ch in sorted(raw_tones.keys(), key=_channel_sort_key):
        timestamps_ms, values = raw_tones[ch]
        prep = preprocess_liu_2016_paper_series(timestamps_ms, values, cfg)
        diag = {
            "segment": seg_name,
            "channel": ch,
            "valid": bool(prep.get("valid", False)),
            "skip_reason": prep.get("skip_reason", ""),
            "n_raw": int(len(values)),
            "n_samples": int(prep.get("n_samples", 0)),
            "fs": float(prep.get("fs", np.nan)) if "fs" in prep else np.nan,
            "max_wavelet_level": int(prep.get("max_wavelet_level", -1)),
            "preprocessing_mode": prep.get("preprocessing_mode", "raw_liu_style"),
        }
        diag_rows.append(diag)
        if not prep.get("valid", False):
            continue
        cols.append(np.asarray(prep["values"], dtype=float))
        labels.append(ch)
        fs_values.append(float(prep["fs"]))

    if not cols:
        return {
            "valid": False,
            "skip_reason": "no_valid_preprocessed_tones",
            "metadata": metadata,
            "diagnostics": diag_rows,
            "matrix": np.empty((0, 0), dtype=float),
            "fs": np.nan,
            "channels": [],
        }
    min_len = min(len(c) for c in cols)
    if min_len < 4:
        return {
            "valid": False,
            "skip_reason": "too_few_aligned_samples",
            "metadata": metadata,
            "diagnostics": diag_rows,
            "matrix": np.empty((0, 0), dtype=float),
            "fs": float(np.nanmedian(fs_values)),
            "channels": labels,
        }
    matrix = np.column_stack([c[:min_len] for c in cols])
    return {
        "valid": True,
        "skip_reason": "",
        "metadata": metadata,
        "diagnostics": diag_rows,
        "matrix": matrix,
        "fs": float(np.nanmedian(fs_values)),
        "channels": labels,
    }


def estimate_liu_2016_paper_segment(
    frames,
    segment_config: Dict[str, dict],
    seg_name: str,
    *,
    variable: str = "amplitudes",
    config: Optional[Liu2016PaperConfig] = None,
) -> Optional[dict]:
    """Run the strict Liu 2016 paper method for one raw amplitude segment."""
    cfg = config or Liu2016PaperConfig()
    seg = segment_config[seg_name]
    if seg.get("type", "breath") == "apnea":
        return None
    prep = _preprocess_raw_segment_matrix(frames, segment_config, seg_name, variable, cfg)
    metadata = prep["metadata"]
    if not prep.get("valid", False):
        return {
            "segment": seg_name,
            "bpm_gt": metadata.get("bpm_gt"),
            "metadata": metadata,
            "variable": variable,
            "liu_2016_paper": {
                "bpm_mean": np.nan,
                "bpm_per_window": np.array([], dtype=float),
                "bpm_signed_err_per_window": np.array([], dtype=float),
                "bpm_rel_err": np.nan,
                "bpm_rel_err_std": np.nan,
                "n_windows": 0,
                "median_n_tones": 0,
                "median_n_kept": 0,
                "mean_outlier_frac": np.nan,
                "mean_pr": np.nan,
                "skip_reason": prep.get("skip_reason", ""),
                "preprocessing_mode": "raw_liu_style",
                "zscore_scale": cfg.zscore_scale,
                "breath_freq_low": cfg.breath_freq_low,
                "breath_freq_high": cfg.breath_freq_high,
            },
            "diagnostics": prep.get("diagnostics", []),
            "window_results": [],
        }

    matrix = prep["matrix"]
    fs = prep["fs"]
    win_len = int(round(cfg.window_length_sec * fs))
    step_len = int(round(cfg.step_length_sec * fs))
    if len(matrix) < win_len:
        starts = [0]
        win_len = len(matrix)
    else:
        starts = _sliding_window_indices(len(matrix), win_len, step_len)

    window_rows: List[dict] = []
    bpms: List[float] = []
    n_tones: List[int] = []
    n_kept: List[int] = []
    outlier_fracs: List[float] = []
    mean_prs: List[float] = []
    for wi, st in enumerate(starts):
        end = st + win_len
        w = estimate_liu_2016_paper_window(matrix[st:end, :], fs, cfg)
        bpm = float(w.get("bpm", np.nan))
        bpms.append(bpm)
        n_tones.append(int(w.get("n_tones", 0)))
        n_kept.append(int(w.get("n_kept", 0)))
        outlier_fracs.append(float(w.get("outlier_frac", np.nan)))
        mean_prs.append(float(w.get("mean_pr", np.nan)))
        window_rows.append({
            "segment": seg_name,
            "window_index": wi,
            "start_sample": int(st),
            "end_sample": int(end),
            "bpm_pred": bpm,
            "freq_hz": float(w.get("freq_hz", np.nan)),
            "n_tones": int(w.get("n_tones", 0)),
            "n_kept": int(w.get("n_kept", 0)),
            "outlier_frac": float(w.get("outlier_frac", np.nan)),
            "mean_pr": float(w.get("mean_pr", np.nan)),
            "skip_reason": w.get("skip_reason", ""),
        })

    stats = _seg_bpm_stats(np.asarray(bpms, dtype=float), metadata.get("bpm_gt"), len(starts))
    paper_stats = {
        **stats,
        "median_n_tones": float(np.nanmedian(n_tones)) if n_tones else 0,
        "median_n_kept": float(np.nanmedian(n_kept)) if n_kept else 0,
        "mean_outlier_frac": float(np.nanmean(outlier_fracs)) if outlier_fracs else np.nan,
        "mean_pr": float(np.nanmean(mean_prs)) if mean_prs else np.nan,
        "skip_reason": "",
        "preprocessing_mode": "raw_liu_style",
        "zscore_scale": cfg.zscore_scale,
        "breath_freq_low": cfg.breath_freq_low,
        "breath_freq_high": cfg.breath_freq_high,
        "fs": fs,
        "n_channels": len(prep["channels"]),
    }
    return {
        "segment": seg_name,
        "bpm_gt": metadata.get("bpm_gt"),
        "metadata": metadata,
        "variable": variable,
        "liu_2016_paper": paper_stats,
        "diagnostics": prep.get("diagnostics", []),
        "window_results": window_rows,
    }


def run_liu_2016_paper_benchmark(
    frames,
    segment_config: Dict[str, dict],
    *,
    variable: str = "amplitudes",
    config: Optional[Liu2016PaperConfig] = None,
    verbose: bool = True,
) -> dict:
    """Run strict Liu 2016 paper reproduction on raw BLE amplitude tones."""
    cfg = config or Liu2016PaperConfig()
    results: Dict[str, Optional[dict]] = {}
    for seg_name in sorted(segment_config.keys()):
        row = estimate_liu_2016_paper_segment(
            frames,
            segment_config,
            seg_name,
            variable=variable,
            config=cfg,
        )
        results[seg_name] = row
        if verbose and row is not None:
            stat = row["liu_2016_paper"]
            rel = stat.get("bpm_rel_err", np.nan)
            if np.isfinite(rel):
                print(f"✓ {seg_name}: {stat['bpm_mean']:.2f} BPM, err={rel*100:.2f}%")
            else:
                print(f"⚠ {seg_name}: skipped ({stat.get('skip_reason', 'unknown')})")
    return {
        "method": "liu_2016_paper",
        "variable": variable,
        "results": results,
        "config": cfg,
        "segment_config": segment_config,
    }


def _bpm_from_waveform(
    signal: np.ndarray,
    fs: float,
    cfg: ChFusionConfig,
) -> float:
    """Estimate BPM from one tone/window by fitting a sinusoid in the breath band."""
    if len(signal) < 8 or not np.all(np.isfinite(signal)):
        return float("nan")
    sig = np.asarray(signal, dtype=float)
    sig = sig - np.mean(sig)
    n = len(sig)
    t = np.arange(n, dtype=float) / fs
    freqs = np.linspace(cfg.breath_freq_low, cfg.breath_freq_high, 512)
    best_score = -np.inf
    best_freq = float("nan")
    for f in freqs:
        model = np.sin(2.0 * np.pi * f * t)
        A = np.column_stack([model, np.cos(2.0 * np.pi * f * t)])
        coeffs, *_ = np.linalg.lstsq(A, sig, rcond=None)
        fit = A @ coeffs
        score = float(np.dot(sig, fit)) / (np.linalg.norm(sig) * np.linalg.norm(fit) + cfg.eps)
        if score > best_score:
            best_score = score
            best_freq = f
    return float(60.0 * best_freq) if np.isfinite(best_freq) else float("nan")


def _tone_band_quality(signal: np.ndarray, fs: float, cfg: ChFusionConfig) -> float:
    """Peak-power ratio in the breath band, used as a conservative tone weight."""
    if len(signal) < 4 or not np.all(np.isfinite(signal)):
        return 0.0
    sig = np.asarray(signal, dtype=float)
    sig = sig - np.mean(sig)
    windowed = sig * np.hanning(len(sig))
    fft_power = np.abs(np.fft.rfft(windowed)) ** 2
    fft_freq = np.fft.rfftfreq(len(windowed), 1.0 / fs)
    band_mask = (fft_freq >= cfg.breath_freq_low) & (fft_freq <= cfg.breath_freq_high)
    if not np.any(band_mask):
        return 0.0
    band_power = fft_power[band_mask]
    peak_power = float(np.max(band_power))
    total_power = float(np.sum(band_power))
    if total_power <= cfg.eps:
        return 0.0
    return peak_power / total_power


def estimate_liu_eta_rho_adapted_window_bpms(
    window_data: np.ndarray,
    fs: float,
    *,
    cfg: Optional[ChFusionConfig] = None,
    eta_per_tone: Optional[np.ndarray] = None,
    rho_per_tone: Optional[np.ndarray] = None,
) -> Tuple[float, np.ndarray, np.ndarray]:
    """Estimate BPM with the existing BLE-adapted eta/rho baseline.

    This is not the strict Liu 2016 paper method. It uses repository-specific
    eta/rho quality scores and the historical dominant-tone fallback.
    """
    cfg = cfg or ChFusionConfig()
    data = np.asarray(window_data, dtype=float)
    if data.ndim == 1:
        data = data[:, None]
    n_tones = data.shape[1] if data.ndim == 2 else len(data)

    if eta_per_tone is None or rho_per_tone is None:
        eta_per_tone = np.zeros(n_tones, dtype=float)
        rho_per_tone = np.ones(n_tones, dtype=float)
        for i in range(n_tones):
            col = data[:, i] if data.ndim == 2 else data[i]
            if np.all(np.isfinite(col)):
                eta_per_tone[i] = _energy_ratio(col, fs, cfg)
                rho_per_tone[i] = _tone_band_quality(col, fs, cfg)

    eta = np.maximum(np.asarray(eta_per_tone, dtype=float), 0.0)
    rho = np.maximum(np.asarray(rho_per_tone, dtype=float), 0.0)
    weights = np.clip(eta * rho, 0.0, None) + cfg.eps
    if np.all(weights <= cfg.eps):
        weights = np.ones_like(weights)
    bpm_per_tone = np.full(n_tones, np.nan, dtype=float)
    for i in range(n_tones):
        col = data[:, i] if data.ndim == 2 else data[i]
        bpm_per_tone[i] = _bpm_from_waveform(col, fs, cfg)

    if n_tones > 1:
        best_idx = int(np.argmax(weights))
        if np.isfinite(bpm_per_tone[best_idx]):
            final_bpm = float(bpm_per_tone[best_idx])
        else:
            final_bpm = _weighted_median(bpm_per_tone, weights)
    else:
        final_bpm = _weighted_median(bpm_per_tone, weights)
    return float(final_bpm), bpm_per_tone, weights


def estimate_liu_style_window_bpms(
    window_data: np.ndarray,
    fs: float,
    *,
    cfg: Optional[ChFusionConfig] = None,
    eta_per_tone: Optional[np.ndarray] = None,
    rho_per_tone: Optional[np.ndarray] = None,
) -> Tuple[float, np.ndarray, np.ndarray]:
    """Backward-compatible alias for ``liu_eta_rho_adapted``.

    This function is retained for existing notebooks/tests. It is a BLE-adapted
    baseline, not a strict Liu et al. 2016 reproduction.
    """
    return estimate_liu_eta_rho_adapted_window_bpms(
        window_data,
        fs,
        cfg=cfg,
        eta_per_tone=eta_per_tone,
        rho_per_tone=rho_per_tone,
    )


def _gather_liu_modal_window_data(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    ch_list: Sequence[Any],
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[str]]:
    """Collect bandpass window data and quality scores from all modal variables."""
    eta_list: List[float] = []
    rho_list: List[float] = []
    bp_cols: List[np.ndarray] = []
    labels: List[str] = []

    for variable in MODAL_LIU_VARIABLES:
        ref_seg = multichannel_by_var.get(variable, {}).get(seg_name)
        if ref_seg is None:
            continue
        ch_map = ref_seg["channels"]
        if not ch_map:
            continue
        for ch in ch_list:
            ch_data = ch_map.get(ch, {})
            if not ch_data:
                continue
            ch_var = ch_data.get(variable)
            if ch_var is None:
                continue
            bp = ch_var["bandpass_filtered"]
            hp = ch_var["highpass_filtered"]
            if len(bp) < end or len(hp) < end:
                continue
            bp_slice = bp[st:end]
            hp_slice = hp[st:end]
            eta_list.append(_energy_ratio(hp_slice, fs, cfg))
            rho_list.append(_tone_band_quality(bp_slice, fs, cfg))
            bp_cols.append(bp_slice)
            labels.append(f"{variable}|ch{ch}")

    if not bp_cols:
        return (
            np.empty((end - st, 0), dtype=float),
            np.empty(0, dtype=float),
            np.empty(0, dtype=float),
            [],
        )
    data_matrix = np.column_stack(bp_cols)
    return data_matrix, np.asarray(eta_list, dtype=float), np.asarray(rho_list, dtype=float), labels


def _estimate_modal_liu_window(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    ch_list: Sequence[Any],
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
) -> Tuple[float, np.ndarray, np.ndarray]:
    data_matrix, eta_per_tone, rho_per_tone, _labels = _gather_liu_modal_window_data(
        multichannel_by_var, seg_name, ch_list, st, end, fs, cfg
    )
    if data_matrix.size == 0:
        return float("nan"), np.array([], dtype=float), np.array([], dtype=float)
    return estimate_liu_style_window_bpms(
        data_matrix, fs, cfg=cfg, eta_per_tone=eta_per_tone, rho_per_tone=rho_per_tone
    )


def estimate_liu_style_segment(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    *,
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    verbose: bool = False,
) -> Optional[dict]:
    """Run the Liu-style per-tone BPM fusion for one segment."""
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()

    ref_seg = multichannel_by_var.get("remote_amplitudes", {}).get(seg_name)
    if ref_seg is None:
        return None
    metadata = ref_seg["metadata"]
    if metadata.get("segment_type") == "apnea":
        return None

    bpm_gt = metadata.get("bpm_gt")
    fs = metadata["sampling_rate"]
    ch_map = ref_seg["channels"]
    if not ch_map:
        return None

    ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
    ref_len = max(len(ch_map[c]["remote_amplitudes"]["bandpass_filtered"]) for c in ch_list)
    win_len = int(round(mp.window_length_sec * fs))
    step_len = int(round(mp.step_length_sec * fs))
    if ref_len < win_len:
        if verbose:
            print(f"⚠️  {seg_name}: length {ref_len} < window {win_len}, skip")
        return None

    starts = _sliding_window_indices(ref_len, win_len, step_len)
    bpms: List[float] = []
    for st in starts:
        end = st + win_len
        bpm, _tone_bpms, _weights = _estimate_modal_liu_window(
            multichannel_by_var, seg_name, ch_list, st, end, fs, cfg
        )
        bpms.append(bpm)

    return {
        "segment": seg_name,
        "bpm_gt": bpm_gt,
        "metadata": metadata,
        "liu_2016": {
            **_seg_bpm_stats(np.asarray(bpms), bpm_gt, len(starts)),
            "bpm_per_window": np.asarray(bpms, dtype=float),
        },
    }


def run_liu_2016_benchmark(
    frames,
    segment_config: Dict[str, dict],
    *,
    filter_params: Optional[FilterParams] = None,
    metric_params: Optional[BreathMetricParams] = None,
    config: Optional[ChFusionConfig] = None,
    verbose: bool = True,
    cache_dir: Optional[str] = None,
    multichannel_by_var: Optional[Dict[str, Dict[str, Optional[dict]]]] = None,
) -> dict:
    """End-to-end BLE-adapted eta/rho benchmark.

    Backward-compatible name retained for existing scripts. This is not the
    strict Liu 2016 paper reproduction; use ``run_liu_2016_paper_benchmark`` for
    the raw-amplitude paper flow.
    """
    from ble_analysis.chfusion import run_multichannel_segment_filtering

    cfg = config or ChFusionConfig()
    fp = filter_params or FilterParams()
    mp = metric_params or BreathMetricParams()

    if multichannel_by_var is None:
        multichannel_by_var = {}
        for variable in MODAL_LIU_VARIABLES:
            mc, _fs = run_multichannel_segment_filtering(
                frames,
                segment_config,
                variable=variable,
                filter_params=fp,
                verbose=verbose,
                cache_dir=cache_dir,
            )
            multichannel_by_var[variable] = mc
    else:
        multichannel_by_var = dict(multichannel_by_var)

    merged: Dict[str, Optional[dict]] = {}
    for seg_name in sorted(next(iter(multichannel_by_var.values())).keys()):
        row = estimate_liu_style_segment(
            multichannel_by_var,
            seg_name,
            config=cfg,
            metric_params=mp,
            verbose=False,
        )
        if row is None:
            merged[seg_name] = None
            continue
        merged[seg_name] = row

    return {
        "results": merged,
        "multichannel_by_var": multichannel_by_var,
        "config": cfg,
        "metric_params": mp,
        "segment_config": segment_config,
    }


def run_liu_eta_rho_adapted_benchmark(*args, **kwargs) -> dict:
    """Explicit name for the existing BLE-adapted eta/rho baseline."""
    return run_liu_2016_benchmark(*args, **kwargs)


def _estimate_single_modal_window(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    modal_variable: str,
    seg_name: str,
    ch_list: Sequence[Any],
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
) -> Tuple[float, np.ndarray, np.ndarray]:
    """Estimate Liu-style BPM using only one modal variable."""
    ref_seg = multichannel_by_var.get(modal_variable, {}).get(seg_name)
    if ref_seg is None:
        return float("nan"), np.array([], dtype=float), np.array([], dtype=float)
    
    ch_map = ref_seg["channels"]
    if not ch_map:
        return float("nan"), np.array([], dtype=float), np.array([], dtype=float)
    
    eta_list: List[float] = []
    rho_list: List[float] = []
    bp_cols: List[np.ndarray] = []
    
    for ch in ch_list:
        ch_data = ch_map.get(ch, {})
        if not ch_data:
            continue
        ch_var = ch_data.get(modal_variable)
        if ch_var is None:
            continue
        bp = ch_var["bandpass_filtered"]
        hp = ch_var["highpass_filtered"]
        if len(bp) < end or len(hp) < end:
            continue
        bp_slice = bp[st:end]
        hp_slice = hp[st:end]
        eta_list.append(_energy_ratio(hp_slice, fs, cfg))
        rho_list.append(_tone_band_quality(bp_slice, fs, cfg))
        bp_cols.append(bp_slice)
    
    if not bp_cols:
        return float("nan"), np.array([], dtype=float), np.array([], dtype=float)
    
    data_matrix = np.column_stack(bp_cols)
    return estimate_liu_style_window_bpms(
        data_matrix, fs, cfg=cfg, eta_per_tone=np.asarray(eta_list), rho_per_tone=np.asarray(rho_list)
    )


def estimate_liu_style_segment_single_modal(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    modal_variable: str,
    seg_name: str,
    *,
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    verbose: bool = False,
) -> Optional[dict]:
    """Run Liu-style BPM fusion for one segment using only one modal variable."""
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()

    ref_seg = multichannel_by_var.get(modal_variable, {}).get(seg_name)
    if ref_seg is None:
        return None
    
    metadata = ref_seg["metadata"]
    if metadata.get("segment_type") == "apnea":
        return None

    bpm_gt = metadata.get("bpm_gt")
    fs = metadata["sampling_rate"]
    ch_map = ref_seg["channels"]
    if not ch_map:
        return None

    ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
    ref_len = max(len(ch_map[c][modal_variable]["bandpass_filtered"]) for c in ch_list)
    win_len = int(round(mp.window_length_sec * fs))
    step_len = int(round(mp.step_length_sec * fs))
    if ref_len < win_len:
        if verbose:
            print(f"⚠️  {seg_name}: length {ref_len} < window {win_len}, skip")
        return None

    starts = _sliding_window_indices(ref_len, win_len, step_len)
    bpms: List[float] = []
    for st in starts:
        end = st + win_len
        bpm, _tone_bpms, _weights = _estimate_single_modal_window(
            multichannel_by_var, modal_variable, seg_name, ch_list, st, end, fs, cfg
        )
        bpms.append(bpm)

    return {
        "segment": seg_name,
        "bpm_gt": bpm_gt,
        "metadata": metadata,
        "modal_variable": modal_variable,
        "liu_2016_modal": {
            **_seg_bpm_stats(np.asarray(bpms), bpm_gt, len(starts)),
            "bpm_per_window": np.asarray(bpms, dtype=float),
        },
    }


def run_liu_2016_modal_comparison(
    segment_config: Dict[str, dict],
    *,
    filter_params: Optional[FilterParams] = None,
    metric_params: Optional[BreathMetricParams] = None,
    config: Optional[ChFusionConfig] = None,
    verbose: bool = True,
    cache_dir: Optional[str] = None,
    multichannel_by_var: Optional[Dict[str, Dict[str, Optional[dict]]]] = None,
) -> dict:
    """Run Liu 2016 benchmark for each modal variable separately and combined."""
    from ble_analysis.chfusion import run_multichannel_segment_filtering

    cfg = config or ChFusionConfig()
    fp = filter_params or FilterParams()
    mp = metric_params or BreathMetricParams()

    if multichannel_by_var is None:
        multichannel_by_var = {}
        for variable in MODAL_LIU_VARIABLES:
            mc, _fs = run_multichannel_segment_filtering(
                None,
                segment_config,
                variable=variable,
                filter_params=fp,
                verbose=verbose,
                cache_dir=cache_dir,
            )
            multichannel_by_var[variable] = mc

    results_by_modal = {}
    
    # Run for each modal variable separately
    for modal_var in MODAL_LIU_VARIABLES:
        modal_results = {}
        for seg_name in sorted(segment_config.keys()):
            result = estimate_liu_style_segment_single_modal(
                multichannel_by_var, modal_var, seg_name, config=cfg, metric_params=mp, verbose=verbose
            )
            modal_results[seg_name] = result
        results_by_modal[modal_var] = modal_results
    
    # Run combined (all modals together)
    combined_results = {}
    for seg_name in sorted(segment_config.keys()):
        result = estimate_liu_style_segment(
            multichannel_by_var, seg_name, config=cfg, metric_params=mp, verbose=verbose
        )
        combined_results[seg_name] = result
    
    return {
        "results_by_modal": results_by_modal,
        "results_combined": combined_results,
        "multichannel_by_var": multichannel_by_var,
        "config": cfg,
        "metric_params": mp,
    }
