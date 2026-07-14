"""Multivariable BLE CS respiration fusion experiments.

This module is intentionally separate from ``liu_2016_paper``.  It studies
BLE-specific channel/tone fusion and variable-level fusion across local
amplitude, remote amplitude, and phase observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

MULTIVARIABLE_VARIABLES: Tuple[str, ...] = (
    "local_amplitudes",
    "remote_amplitudes",
    "phases",
)

CHANNEL_FUSION_METHODS: Tuple[str, ...] = (
    "best_tone",
    "equal_average",
    "liu_weighted_median",
    "snr_mrc",
    "quality_mrc",
)

VARIABLE_FUSION_METHODS: Tuple[str, ...] = (
    "variable_equal_average",
    "variable_quality_weighted",
    "variable_weighted_median",
    "variable_mrc",
    "adaptive_selection",
)

HIERARCHICAL_COMPARISON_METHODS: Tuple[str, ...] = (
    "best_tone__adaptive_selection",
    "liu_weighted_median__variable_weighted_median",
    "snr_mrc__variable_mrc",
    "hierarchical_quality_fusion",
)


@dataclass
class MultivariableFusionConfig:
    """Configuration for deterministic multivariable fusion experiments."""

    breath_freq_low: float = 0.1
    breath_freq_high: float = 0.35
    total_freq_low: float = 0.05
    total_freq_high: float = 0.8
    window_length_sec: float = 20.0
    step_length_sec: float = 1.0
    snr_good: float = 6.0
    pr_good: float = 4.0
    stability_good_bpm: float = 2.0
    eps: float = 1e-12


def _as_time_by_tone(data: Sequence[Sequence[float]]) -> np.ndarray:
    arr = np.asarray(data, dtype=float)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.ndim != 2:
        raise ValueError("window data must be a 1-D or 2-D array")
    return arr


def _finite_columns(data: np.ndarray) -> np.ndarray:
    if data.size == 0:
        return data.reshape((data.shape[0], 0))
    mask = np.all(np.isfinite(data), axis=0)
    return data[:, mask]


def _next_pow2(n: int) -> int:
    return 1 << int(np.ceil(np.log2(max(1, n))))


def estimate_bpm_fft(
    signal: Sequence[float],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> dict:
    """Estimate BPM from a single waveform with breath-band FFT peak search."""
    cfg = cfg or MultivariableFusionConfig()
    x = np.asarray(signal, dtype=float)
    if len(x) < 4 or fs <= 0 or not np.all(np.isfinite(x)):
        return {"valid": False, "bpm": np.nan, "freq_hz": np.nan, "peak_snr": np.nan}
    x = x - np.mean(x)
    if np.std(x) <= cfg.eps:
        return {"valid": False, "bpm": np.nan, "freq_hz": np.nan, "peak_snr": 0.0}
    nfft = _next_pow2(max(len(x), 4 * len(x)))
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)), n=nfft)) ** 2
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
    if not np.any(band):
        return {"valid": False, "bpm": np.nan, "freq_hz": np.nan, "peak_snr": np.nan}
    p = spec[band]
    f = freqs[band]
    k = int(np.argmax(p))
    freq_hz = float(f[k])
    if 0 < k < len(p) - 1:
        y0, y1, y2 = p[k - 1], p[k], p[k + 1]
        denom = y0 - 2.0 * y1 + y2
        if abs(denom) > cfg.eps:
            freq_hz = float(f[k] + 0.5 * (y0 - y2) / denom * (f[1] - f[0]))
    freq_hz = float(np.clip(freq_hz, cfg.breath_freq_low, cfg.breath_freq_high))
    peak_snr = float(np.max(p) / (np.median(p) + cfg.eps))
    return {
        "valid": bool(np.isfinite(freq_hz)),
        "bpm": 60.0 * freq_hz,
        "freq_hz": freq_hz,
        "peak_snr": peak_snr,
    }


def breath_band_snr(
    signal: Sequence[float],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> float:
    """Return breath-band peak/median spectrum ratio."""
    return float(estimate_bpm_fft(signal, fs, cfg).get("peak_snr", np.nan))


def periodicity_pr(
    signal: Sequence[float],
    fs: float,
    freq_hz: float,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> dict:
    """Fixed-frequency sinusoid fit quality ``pr=A/RMSE``."""
    cfg = cfg or MultivariableFusionConfig()
    x = np.asarray(signal, dtype=float)
    if len(x) < 4 or fs <= 0 or not np.isfinite(freq_hz) or freq_hz <= 0:
        return {"valid": False, "A": np.nan, "rmse": np.nan, "pr": np.nan}
    t = np.arange(len(x), dtype=float) / fs
    design = np.column_stack(
        [np.sin(2.0 * np.pi * freq_hz * t), np.cos(2.0 * np.pi * freq_hz * t), np.ones_like(t)]
    )
    try:
        coeffs, *_ = np.linalg.lstsq(design, x, rcond=None)
    except np.linalg.LinAlgError:
        return {"valid": False, "A": np.nan, "rmse": np.nan, "pr": np.nan}
    if not np.all(np.isfinite(coeffs)) or float(np.max(np.abs(coeffs))) > 1e9:
        return {"valid": False, "A": np.nan, "rmse": np.nan, "pr": np.nan}
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        fitted = design @ coeffs
    if not np.all(np.isfinite(fitted)):
        return {"valid": False, "A": np.nan, "rmse": np.nan, "pr": np.nan}
    rmse = float(np.sqrt(np.mean((x - fitted) ** 2)))
    amp = float(np.sqrt(coeffs[0] ** 2 + coeffs[1] ** 2))
    pr = amp / (rmse + cfg.eps)
    return {"valid": True, "A": amp, "rmse": rmse, "pr": float(pr)}


def stability_from_bpms(bpms: Sequence[float], cfg: Optional[MultivariableFusionConfig] = None) -> float:
    """Map BPM dispersion to a compact stability score in [0, 1]."""
    cfg = cfg or MultivariableFusionConfig()
    arr = np.asarray(bpms, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size <= 1:
        return 1.0 if arr.size == 1 else np.nan
    std = float(np.std(arr, ddof=1))
    return float(1.0 / (1.0 + std / (cfg.stability_good_bpm + cfg.eps)))


def _normalize_metric(value: Optional[float], good: float, eps: float) -> Optional[float]:
    if value is None or not np.isfinite(value):
        return None
    return float(np.clip(float(value) / (good + eps), 0.0, 1.0))


def geometric_quality(
    *,
    snr: Optional[float] = None,
    pr: Optional[float] = None,
    stability: Optional[float] = None,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> dict:
    """Combine available quality indicators with a geometric mean.

    Missing indicators are ignored.  If all indicators are missing, the result
    is invalid for the current window.
    """
    cfg = cfg or MultivariableFusionConfig()
    vals: List[float] = []
    for item in (
        _normalize_metric(snr, cfg.snr_good, cfg.eps),
        _normalize_metric(pr, cfg.pr_good, cfg.eps),
        _normalize_metric(stability, 1.0, cfg.eps),
    ):
        if item is not None:
            vals.append(max(float(item), cfg.eps))
    if not vals:
        return {"valid": False, "quality": 0.0, "n_metrics": 0}
    q = float(np.exp(np.mean(np.log(vals))))
    return {"valid": True, "quality": q, "n_metrics": len(vals)}


def normalized_weights(qualities: Sequence[float], eps: float = 1e-12) -> np.ndarray:
    """Return nonnegative normalized weights; fall back to uniform if needed."""
    q = np.asarray(qualities, dtype=float)
    valid = np.isfinite(q) & (q > 0)
    if not np.any(valid):
        return np.ones_like(q, dtype=float) / max(len(q), 1)
    out = np.zeros_like(q, dtype=float)
    out[valid] = q[valid]
    return out / (np.sum(out) + eps)


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    """Weighted median over finite values and positive weights."""
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask = np.isfinite(v) & np.isfinite(w) & (w > 0)
    if not np.any(mask):
        finite = v[np.isfinite(v)]
        return float(np.nanmedian(finite)) if finite.size else np.nan
    v = v[mask]
    w = w[mask]
    order = np.argsort(v)
    v = v[order]
    w = w[order]
    cdf = np.cumsum(w) / (np.sum(w) + 1e-12)
    return float(v[np.searchsorted(cdf, 0.5)])


def tone_diagnostics(
    window_data: Sequence[Sequence[float]],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> List[dict]:
    """Compute per-tone BPM and quality diagnostics for one window."""
    cfg = cfg or MultivariableFusionConfig()
    data = _finite_columns(_as_time_by_tone(window_data))
    rows: List[dict] = []
    for i in range(data.shape[1]):
        x = data[:, i]
        est = estimate_bpm_fft(x, fs, cfg)
        pr = periodicity_pr(x, fs, est.get("freq_hz", np.nan), cfg)
        q = geometric_quality(snr=est.get("peak_snr"), pr=pr.get("pr"), stability=1.0, cfg=cfg)
        rows.append(
            {
                "tone_index": i,
                "valid": bool(est["valid"] and q["valid"]),
                "bpm": float(est["bpm"]) if np.isfinite(est.get("bpm", np.nan)) else np.nan,
                "freq_hz": float(est["freq_hz"]) if np.isfinite(est.get("freq_hz", np.nan)) else np.nan,
                "snr": float(est["peak_snr"]) if np.isfinite(est.get("peak_snr", np.nan)) else np.nan,
                "pr": float(pr["pr"]) if np.isfinite(pr.get("pr", np.nan)) else np.nan,
                "stability": 1.0,
                "quality": float(q["quality"]),
            }
        )
    return rows


def best_tone_selection(
    window_data: Sequence[Sequence[float]],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> dict:
    """Select the highest-quality tone and estimate BPM from it."""
    cfg = cfg or MultivariableFusionConfig()
    data = _finite_columns(_as_time_by_tone(window_data))
    if data.shape[1] == 0:
        return _invalid_channel_result("best_tone")
    diag = tone_diagnostics(data, fs, cfg)
    qualities = np.array([d["quality"] if d["valid"] else 0.0 for d in diag], dtype=float)
    if np.sum(qualities) <= cfg.eps:
        return _invalid_channel_result("best_tone", diagnostics=diag)
    idx = int(np.argmax(qualities))
    waveform = data[:, idx]
    return _channel_result("best_tone", waveform, fs, cfg, diag, selected_tone=idx)


def equal_average_fusion(
    window_data: Sequence[Sequence[float]],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> dict:
    """Equal-average tone waveform fusion baseline."""
    cfg = cfg or MultivariableFusionConfig()
    data = _finite_columns(_as_time_by_tone(window_data))
    if data.shape[1] == 0:
        return _invalid_channel_result("equal_average")
    diag = tone_diagnostics(data, fs, cfg)
    waveform = np.mean(data, axis=1)
    return _channel_result("equal_average", waveform, fs, cfg, diag)


def liu_weighted_median_channel_fusion(
    window_data: Sequence[Sequence[float]],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> dict:
    """Liu-style tone BPM candidates fused by periodicity-weighted median."""
    cfg = cfg or MultivariableFusionConfig()
    data = _finite_columns(_as_time_by_tone(window_data))
    if data.shape[1] == 0:
        return _invalid_channel_result("liu_weighted_median")
    diag = tone_diagnostics(data, fs, cfg)
    bpms = np.array([d["bpm"] for d in diag], dtype=float)
    weights = np.array([d["pr"] if d["valid"] else 0.0 for d in diag], dtype=float)
    bpm = weighted_median(bpms, weights)
    valid = np.isfinite(bpm)
    return {
        "method": "liu_weighted_median",
        "valid": bool(valid),
        "bpm_pred": float(bpm) if valid else np.nan,
        "fused_waveform": np.mean(data, axis=1),
        "quality_snr": _nanmean([d["snr"] for d in diag]),
        "quality_pr": _nanmean([d["pr"] for d in diag]),
        "quality_stability": stability_from_bpms(bpms, cfg),
        "quality": float(np.nanmean(weights)) if np.any(np.isfinite(weights)) else 0.0,
        "n_valid_tones": int(np.sum(np.isfinite(bpms) & (weights > 0))),
        "n_tones": int(data.shape[1]),
        "outlier_frac": _outlier_fraction(bpms),
        "diagnostics": diag,
        "weights": normalized_weights(weights, cfg.eps).tolist(),
    }


def snr_mrc_channel_fusion(
    window_data: Sequence[Sequence[float]],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> dict:
    """Tone waveform MRC using breath-band SNR as weight."""
    return _mrc_channel_fusion(window_data, fs, cfg, method="snr_mrc", quality_mode="snr")


def quality_mrc_channel_fusion(
    window_data: Sequence[Sequence[float]],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> dict:
    """BLE-adapted tone waveform MRC using snr/pr/stability quality."""
    return _mrc_channel_fusion(window_data, fs, cfg, method="quality_mrc", quality_mode="quality")


def run_channel_fusion_methods(
    window_data: Sequence[Sequence[float]],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
    methods: Sequence[str] = CHANNEL_FUSION_METHODS,
) -> Dict[str, dict]:
    """Run selected channel/tone-level fusion methods for one variable window."""
    funcs = {
        "best_tone": best_tone_selection,
        "equal_average": equal_average_fusion,
        "liu_weighted_median": liu_weighted_median_channel_fusion,
        "snr_mrc": snr_mrc_channel_fusion,
        "quality_mrc": quality_mrc_channel_fusion,
    }
    return {m: funcs[m](window_data, fs, cfg) for m in methods}


def variable_level_fusion(
    variable_results: Mapping[str, Mapping[str, Any]],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
    methods: Sequence[str] = VARIABLE_FUSION_METHODS,
) -> Dict[str, dict]:
    """Fuse already channel-fused local/remote/phase variable results."""
    cfg = cfg or MultivariableFusionConfig()
    valid_items = {
        k: v
        for k, v in variable_results.items()
        if bool(v.get("valid")) and np.isfinite(v.get("bpm_pred", np.nan))
    }
    out: Dict[str, dict] = {}
    for method in methods:
        if not valid_items:
            out[method] = _invalid_variable_result(method)
            continue
        names = list(valid_items.keys())
        bpms = np.array([valid_items[n]["bpm_pred"] for n in names], dtype=float)
        qualities = np.array([valid_items[n].get("quality", 0.0) for n in names], dtype=float)
        waveforms = [np.asarray(valid_items[n].get("fused_waveform"), dtype=float) for n in names]

        if method == "variable_equal_average":
            bpm = float(np.nanmean(bpms))
            weights = np.ones(len(names), dtype=float) / len(names)
            waveform = _weighted_waveform(waveforms, weights)
            selected = ""
        elif method == "variable_quality_weighted":
            weights = normalized_weights(qualities, cfg.eps)
            bpm = float(np.sum(weights * bpms))
            waveform = _weighted_waveform(waveforms, weights)
            selected = ""
        elif method == "variable_weighted_median":
            weights = normalized_weights(qualities, cfg.eps)
            bpm = weighted_median(bpms, weights)
            waveform = _weighted_waveform(waveforms, weights)
            selected = ""
        elif method == "variable_mrc":
            weights = normalized_weights(
                [valid_items[n].get("quality_snr", valid_items[n].get("quality", 0.0)) for n in names],
                cfg.eps,
            )
            waveform = _weighted_waveform(waveforms, weights)
            est = estimate_bpm_fft(waveform, fs, cfg)
            bpm = float(est.get("bpm", np.nan))
            selected = ""
        elif method == "adaptive_selection":
            idx = int(np.argmax(qualities))
            weights = np.zeros(len(names), dtype=float)
            weights[idx] = 1.0
            bpm = float(bpms[idx])
            waveform = waveforms[idx]
            selected = names[idx]
        else:
            raise KeyError(f"Unknown variable fusion method: {method}")

        out[method] = {
            "method": method,
            "valid": bool(np.isfinite(bpm)),
            "bpm_pred": bpm if np.isfinite(bpm) else np.nan,
            "fused_waveform": waveform,
            "quality": float(np.nanmean(qualities)) if len(qualities) else 0.0,
            "variables_used": ",".join(names),
            "selected_variable": selected,
            "weights": {n: float(w) for n, w in zip(names, weights)},
        }
    return out


def hierarchical_quality_fusion(
    variable_window_data: Mapping[str, Sequence[Sequence[float]]],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> dict:
    """Proposed two-level fusion: quality-MRC per variable, quality-weighted variables."""
    cfg = cfg or MultivariableFusionConfig()
    per_variable = {
        var: quality_mrc_channel_fusion(data, fs, cfg)
        for var, data in variable_window_data.items()
    }
    fused = variable_level_fusion(
        per_variable, fs, cfg, methods=("variable_quality_weighted",)
    )["variable_quality_weighted"]
    fused["method"] = "hierarchical_quality_fusion"
    fused["per_variable"] = per_variable
    return fused


def run_hierarchical_comparisons(
    variable_window_data: Mapping[str, Sequence[Sequence[float]]],
    fs: float,
    cfg: Optional[MultivariableFusionConfig] = None,
) -> Dict[str, dict]:
    """Run paired channel+variable fusion comparisons for one multivariable window."""
    cfg = cfg or MultivariableFusionConfig()
    pairs = {
        "best_tone__adaptive_selection": ("best_tone", "adaptive_selection"),
        "liu_weighted_median__variable_weighted_median": (
            "liu_weighted_median",
            "variable_weighted_median",
        ),
        "snr_mrc__variable_mrc": ("snr_mrc", "variable_mrc"),
    }
    out: Dict[str, dict] = {}
    for key, (ch_method, var_method) in pairs.items():
        per_variable = {
            var: run_channel_fusion_methods(data, fs, cfg, methods=(ch_method,))[ch_method]
            for var, data in variable_window_data.items()
        }
        fused = variable_level_fusion(per_variable, fs, cfg, methods=(var_method,))[var_method]
        fused["method"] = key
        fused["per_variable"] = per_variable
        out[key] = fused
    out["hierarchical_quality_fusion"] = hierarchical_quality_fusion(variable_window_data, fs, cfg)
    return out


def summarize_windows(rows: Sequence[Mapping[str, Any]], group_keys: Sequence[str]) -> List[dict]:
    """Aggregate per-window rows into summary records."""
    grouped: Dict[Tuple[Any, ...], List[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(tuple(row.get(k) for k in group_keys), []).append(row)
    out: List[dict] = []
    for key, items in sorted(grouped.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        rec = {k: v for k, v in zip(group_keys, key)}
        bpm_gt = _nanmean([r.get("bpm_gt") for r in items])
        bpms = np.asarray([r.get("bpm_pred", np.nan) for r in items], dtype=float)
        valid = np.isfinite(bpms)
        rels = np.asarray([r.get("rel_err_pct", np.nan) for r in items], dtype=float)
        rec.update(
            {
                "bpm_gt": bpm_gt,
                "bpm_pred": float(np.nanmean(bpms)) if np.any(valid) else np.nan,
                "rel_err_pct": float(np.nanmean(rels)) if np.any(np.isfinite(rels)) else np.nan,
                "n_windows": len(items),
                "valid_window_rate": float(np.mean(valid)) if len(items) else 0.0,
                "median_n_valid_tones": _nanmedian([r.get("n_valid_tones") for r in items]),
                "mean_snr": _nanmean([r.get("quality_snr") for r in items]),
                "mean_pr": _nanmean([r.get("quality_pr") for r in items]),
                "mean_stability": _nanmean([r.get("quality_stability") for r in items]),
                "mean_outlier_frac": _nanmean([r.get("outlier_frac") for r in items]),
                "failure_reason": _failure_reason(items),
            }
        )
        out.append(rec)
    return out


def _channel_result(
    method: str,
    waveform: np.ndarray,
    fs: float,
    cfg: MultivariableFusionConfig,
    diagnostics: List[dict],
    *,
    selected_tone: Optional[int] = None,
    weights: Optional[Sequence[float]] = None,
) -> dict:
    est = estimate_bpm_fft(waveform, fs, cfg)
    bpms = np.array([d["bpm"] for d in diagnostics], dtype=float)
    snrs = np.array([d["snr"] for d in diagnostics], dtype=float)
    prs = np.array([d["pr"] for d in diagnostics], dtype=float)
    quality = geometric_quality(
        snr=est.get("peak_snr"),
        pr=_nanmean(prs),
        stability=stability_from_bpms(bpms, cfg),
        cfg=cfg,
    )
    return {
        "method": method,
        "valid": bool(est["valid"] and quality["valid"]),
        "bpm_pred": float(est["bpm"]) if np.isfinite(est.get("bpm", np.nan)) else np.nan,
        "fused_waveform": np.asarray(waveform, dtype=float),
        "quality_snr": float(est.get("peak_snr", np.nan)),
        "quality_pr": _nanmean(prs),
        "quality_stability": stability_from_bpms(bpms, cfg),
        "quality": float(quality["quality"]),
        "n_valid_tones": int(sum(d["valid"] for d in diagnostics)),
        "n_tones": int(len(diagnostics)),
        "outlier_frac": _outlier_fraction(bpms),
        "diagnostics": diagnostics,
        "selected_tone": selected_tone,
        "weights": list(weights) if weights is not None else [],
    }


def _invalid_channel_result(method: str, diagnostics: Optional[List[dict]] = None) -> dict:
    return {
        "method": method,
        "valid": False,
        "bpm_pred": np.nan,
        "fused_waveform": np.asarray([], dtype=float),
        "quality_snr": np.nan,
        "quality_pr": np.nan,
        "quality_stability": np.nan,
        "quality": 0.0,
        "n_valid_tones": 0,
        "n_tones": 0,
        "outlier_frac": np.nan,
        "diagnostics": diagnostics or [],
        "weights": [],
    }


def _invalid_variable_result(method: str) -> dict:
    return {
        "method": method,
        "valid": False,
        "bpm_pred": np.nan,
        "fused_waveform": np.asarray([], dtype=float),
        "quality": 0.0,
        "variables_used": "",
        "selected_variable": "",
        "weights": {},
    }


def _mrc_channel_fusion(
    window_data: Sequence[Sequence[float]],
    fs: float,
    cfg: Optional[MultivariableFusionConfig],
    *,
    method: str,
    quality_mode: str,
) -> dict:
    cfg = cfg or MultivariableFusionConfig()
    data = _finite_columns(_as_time_by_tone(window_data))
    if data.shape[1] == 0:
        return _invalid_channel_result(method)
    diag = tone_diagnostics(data, fs, cfg)
    if quality_mode == "snr":
        q = np.array([d["snr"] if d["valid"] else 0.0 for d in diag], dtype=float)
    else:
        q = np.array([d["quality"] if d["valid"] else 0.0 for d in diag], dtype=float)
    weights = normalized_weights(q, cfg.eps)
    waveform = np.sum(data * weights[None, :], axis=1)
    return _channel_result(method, waveform, fs, cfg, diag, weights=weights)


def _weighted_waveform(waveforms: Sequence[np.ndarray], weights: Sequence[float]) -> np.ndarray:
    if not waveforms:
        return np.asarray([], dtype=float)
    n = min(len(w) for w in waveforms)
    if n == 0:
        return np.asarray([], dtype=float)
    arr = np.column_stack([np.asarray(w[:n], dtype=float) for w in waveforms])
    w = np.asarray(weights, dtype=float)
    return np.sum(arr * w[None, :], axis=1)


def _nanmean(values: Iterable[Any]) -> float:
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    return float(np.nanmean(arr)) if arr.size and np.any(np.isfinite(arr)) else np.nan


def _nanmedian(values: Iterable[Any]) -> float:
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    return float(np.nanmedian(arr)) if arr.size and np.any(np.isfinite(arr)) else np.nan


def _outlier_fraction(bpms: Sequence[float]) -> float:
    arr = np.asarray(bpms, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 3:
        return 0.0
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    if mad <= 1e-12:
        return 0.0
    z = 0.6745 * (arr - med) / mad
    return float(np.mean(np.abs(z) > 3.5))


def _failure_reason(items: Sequence[Mapping[str, Any]]) -> str:
    if not items:
        return "no_windows"
    valid = [bool(r.get("valid", np.isfinite(r.get("bpm_pred", np.nan)))) for r in items]
    if any(valid):
        return ""
    reasons = [str(r.get("failure_reason", "")) for r in items if r.get("failure_reason")]
    return reasons[0] if reasons else "no_valid_windows"
