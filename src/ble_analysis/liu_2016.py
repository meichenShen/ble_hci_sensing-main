"""Liu et al. 2016 style per-tone BPM estimation and weighted fusion.

This module is a paper-faithful adaptation of the Liu-style workflow for BLE CS:
1. estimate BPM independently for each tone/window using the same breath-band peak search;
2. derive tone quality weights from the per-tone signal quality metrics;
3. fuse the per-tone BPM estimates with a weighted median.

The implementation is intentionally conservative and does not invent extra fusion
steps beyond the paper's core idea. It also accepts multiple modal variables so
that the method can be evaluated on BLE CS inputs beyond a remote-only mapping.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ble_analysis.chfusion import (
    ChFusionConfig,
    _energy_ratio,
    _parabolic_peak_freq,
    _peak_prominence,
    _seg_bpm_stats,
    _weighted_median,
)
from ble_analysis.segments import BreathMetricParams, FilterParams, _sliding_window_indices

MODAL_LIU_VARIABLES: Tuple[str, ...] = (
    "remote_amplitudes",
    "local_amplitudes",
    "phases",
)

__all__ = [
    "estimate_liu_style_window_bpms",
    "estimate_liu_style_segment",
    "run_liu_2016_benchmark",
    "MODAL_LIU_VARIABLES",
    "_gather_liu_modal_window_data",
]


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


def estimate_liu_style_window_bpms(
    window_data: np.ndarray,
    fs: float,
    *,
    cfg: Optional[ChFusionConfig] = None,
    eta_per_tone: Optional[np.ndarray] = None,
    rho_per_tone: Optional[np.ndarray] = None,
) -> Tuple[float, np.ndarray, np.ndarray]:
    """Estimate per-tone BPMs and fuse them with a weighted median.

    Parameters
    ----------
    window_data : array-like, shape [T, n_tones]
        One sliding-window worth of tone signals.
    fs : float
        Sampling rate in Hz.
    cfg : ChFusionConfig
        Breath-band configuration.
    eta_per_tone, rho_per_tone : optional arrays
        Per-tone quality scores used as fusion weights; if absent they are derived
        from the window itself using the same η/ρ metrics already used in the
        repository.
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
    """End-to-end Liu-style benchmark on BLE CS segments."""
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
