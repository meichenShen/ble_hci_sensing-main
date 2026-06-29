"""WiFi MRC baseline migration for BLE CS breathing BPM estimation.

Implements Fan-BLE (η-MRC → best modal) and MRC-PCA-BLE (√η-MRC + PCA sign)
from ``docs/plans/wifi_mrc_baselines_plan.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np
from scipy.signal import welch

from ble_analysis.chfusion import (
    ChFusionConfig,
    Plan2Config,
    _energy_ratio,
    _overall_rel_error,
    _parabolic_peak_freq,
    _peak_prominence,
    _seg_bpm_stats,
    run_multichannel_segment_filtering,
)
from ble_analysis.segments import BreathMetricParams, FilterParams, _sliding_window_indices
from ble_analysis.systematic_fusion import (
    estimate_systematic_fusion_segment,
)
from ble_analysis.voting_fusion import (
    MODAL_VOTING_VARIABLES,
    VotingConfig,
    run_voting_fusion_benchmark,
)

MrcWeightMode = Literal["linear", "sqrt", "eta_rho"]

WIFI_MRC_METHOD_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("B0 Single Remote", "b0_single_remote", "steelblue"),
    ("B1 Uniform Remote", "b1_uniform_remote", "seagreen"),
    ("Modal top2 equal", "b2_modal_top2_equal", "mediumpurple"),
    ("B1 Vote→Equal modal", "b1_vote_modal_equal", "olive"),
    ("Fan-η-linear", "fan_eta_linear", "coral"),
    ("Fan-η-sqrt", "fan_eta_sqrt", "tomato"),
    ("Fan-η-equal", "fan_eta_equal", "darkorange"),
    ("MRC-PCA-η-sqrt", "mrc_pca_eta_sqrt", "indianred"),
    ("MRC-PCA-η-equal", "mrc_pca_eta_equal", "crimson"),
    ("MRC-PCA-no-sign", "mrc_pca_no_sign", "gray"),
)

MRC_METHOD_KEYS: Tuple[str, ...] = tuple(
    key for _label, key, _color in WIFI_MRC_METHOD_SPECS if key.startswith(("fan_", "mrc_"))
)

WIFI_MRC_ABLATION_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("Fan-ηρ-linear", "fan_eta_rho_linear", "chocolate"),
    ("Fan-ηρ-equal", "fan_eta_rho_equal", "saddlebrown"),
    ("MRC-PCA-η-linear", "mrc_pca_eta_linear", "firebrick"),
)

MODAL_SHORT_NAMES = {
    "remote_amplitudes": "remote",
    "local_amplitudes": "local",
    "phases": "phase",
}

__all__ = [
    "WIFI_MRC_METHOD_SPECS",
    "WIFI_MRC_ABLATION_SPECS",
    "MRC_METHOD_KEYS",
    "MODAL_SHORT_NAMES",
    "compute_mrc_weights",
    "fan_mrc_fusion",
    "mrc_pca_fusion",
    "estimate_bpm_from_waveform",
    "estimate_wifi_mrc_segment",
    "estimate_wifi_mrc_ablation_segment",
    "run_wifi_mrc_benchmark",
    "compute_wifi_mrc_cross_domain",
    "compute_window_level_metrics",
    "compute_eta_stability_diagnostics",
    "compute_modal_switching_diagnostics",
    "compute_pca_loading_diagnostics",
    "run_wifi_mrc_diagnosis_pass",
    "plot_wifi_mrc_figures",
    "plot_wifi_mrc_diagnosis_figures",
]


def compute_mrc_weights(
    eta: np.ndarray,
    mode: MrcWeightMode = "sqrt",
    rho: Optional[np.ndarray] = None,
    eps: float = 1e-12,
) -> np.ndarray:
    """Derive normalized MRC positive weights from per-tone η."""
    eta_arr = np.asarray(eta, dtype=float)
    eta_arr = np.clip(eta_arr, 0.0, None)
    if mode == "linear":
        raw = eta_arr
    elif mode == "sqrt":
        raw = np.sqrt(eta_arr)
    elif mode == "eta_rho":
        if rho is None:
            raise ValueError("rho required for mode='eta_rho'")
        raw = eta_arr * np.clip(np.asarray(rho, dtype=float), 0.0, None)
    else:
        raise ValueError(f"Unknown MRC weight mode: {mode}")
    total = float(np.sum(raw))
    if total <= eps:
        n = len(raw)
        return np.full(n, 1.0 / n) if n else raw
    return raw / total


def _standardize_rows(X: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    out = np.zeros_like(X, dtype=float)
    for i in range(X.shape[0]):
        row = X[i]
        if not np.all(np.isfinite(row)):
            continue
        mu = float(np.mean(row))
        sd = float(np.std(row))
        out[i] = (row - mu) / sd if sd > eps else (row - mu)
    return out


def fan_mrc_fusion(
    X: np.ndarray,
    eta: np.ndarray,
    weight_mode: MrcWeightMode = "linear",
    fs: float = 2.0,
    cfg: Optional[ChFusionConfig] = None,
    rho: Optional[np.ndarray] = None,
    eps: float = 1e-12,
) -> Tuple[np.ndarray, float, dict]:
    """Fan-style η-MRC time-domain fusion for one modal variable."""
    cfg = cfg or ChFusionConfig(eps=eps)
    X_arr = np.asarray(X, dtype=float)
    g = compute_mrc_weights(eta, mode=weight_mode, rho=rho, eps=eps)
    if X_arr.ndim != 2:
        raise ValueError("X must have shape [n_tones, T_win]")
    y = np.sum(g[:, None] * X_arr, axis=0)
    eta_fused = _energy_ratio(y, fs, cfg)
    return y, eta_fused, {"weights": g}


def mrc_pca_fusion(
    X: np.ndarray,
    eta: np.ndarray,
    weight_mode: MrcWeightMode = "sqrt",
    use_pca_sign: bool = True,
    top_k: Optional[int] = 36,
    rho: Optional[np.ndarray] = None,
    eps: float = 1e-12,
) -> Tuple[np.ndarray, dict]:
    """WiFi-Sleep style √η-MRC + PCA sign correction."""
    X_arr = np.asarray(X, dtype=float)
    g = compute_mrc_weights(eta, mode=weight_mode, rho=rho, eps=eps)
    n_tones = X_arr.shape[0]
    signs = np.ones(n_tones, dtype=float)
    loadings_full = np.zeros(n_tones, dtype=float)
    explained_var_ratio = float("nan")

    if use_pca_sign and n_tones > 1:
        idx = np.arange(n_tones)
        if top_k is not None and top_k < n_tones:
            order = np.argsort(-np.asarray(eta, dtype=float))
            idx = order[:top_k]
        X_weighted = X_arr[idx] * g[idx, None]
        X_weighted = _standardize_rows(X_weighted, eps=eps)
        n_samples, n_features = X_weighted.shape
        if n_samples >= 2 and n_features >= 2:
            Z = X_weighted.T
            cov = (Z.T @ Z) / max(n_samples - 1, 1)
            evals, evecs = np.linalg.eigh(cov)
            loadings = np.asarray(evecs[:, -1], dtype=float)
            eval_sum = float(np.sum(np.maximum(evals, 0.0)))
            if eval_sum > eps:
                explained_var_ratio = float(max(evals[-1], 0.0) / eval_sum)
            for local_i, global_i in enumerate(idx):
                loadings_full[global_i] = loadings[local_i]
                s = np.sign(loadings[local_i])
                signs[global_i] = 1.0 if s == 0 else s

    w = signs * g
    w_sum = float(np.sum(np.abs(w)))
    if w_sum > eps:
        w = w / w_sum
    y = np.sum(w[:, None] * X_arr, axis=0)
    mu = float(np.mean(y))
    sd = float(np.std(y))
    if sd > eps:
        y = (y - mu) / sd
    else:
        y = y - mu
    return y, {
        "weights": w,
        "signs": signs,
        "positive_weights": g,
        "loadings": loadings_full,
        "explained_variance_ratio": explained_var_ratio,
    }


def estimate_bpm_from_waveform(
    y: np.ndarray,
    fs: float,
    breath_band: Tuple[float, float] = (0.1, 0.35),
    cfg: Optional[ChFusionConfig] = None,
) -> Tuple[float, float, np.ndarray, np.ndarray]:
    """Welch PSD peak BPM with parabolic refinement."""
    cfg = cfg or ChFusionConfig()
    sig = np.asarray(y, dtype=float)
    if len(sig) < 4 or not np.all(np.isfinite(sig)):
        nan = np.array([], dtype=float)
        return float("nan"), float("nan"), nan, nan

    nperseg = min(len(sig), 512)
    noverlap = nperseg // 2
    freqs, pxx = welch(
        sig - np.mean(sig),
        fs=fs,
        window="hann",
        nperseg=nperseg,
        noverlap=noverlap,
    )
    band_mask = (freqs >= breath_band[0]) & (freqs <= breath_band[1])
    if not np.any(band_mask):
        return float("nan"), float("nan"), freqs, pxx

    band_freqs = freqs[band_mask]
    power_band = pxx[band_mask]
    k = int(np.argmax(power_band))
    f_peak = _parabolic_peak_freq(band_freqs, power_band, k, cfg.eps)
    bpm = float(60.0 * f_peak)
    return bpm, float(f_peak), freqs, pxx


def _collect_modal_window_matrix(
    ch_list: Sequence[Any],
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Collect standardized bandpass matrix [n_tones, T], η and ρ vectors."""
    eta_list: List[float] = []
    rho_list: List[float] = []
    rows: List[np.ndarray] = []
    for ch in ch_list:
        ch_data = ch_map[ch][variable]
        bp = ch_data["bandpass_filtered"]
        hp = ch_data["highpass_filtered"]
        if len(bp) < end or len(hp) < end:
            eta_list.append(0.0)
            rho_list.append(0.0)
            rows.append(np.full(end - st, np.nan, dtype=float))
            continue
        bp_slice = bp[st:end]
        hp_slice = hp[st:end]
        eta_list.append(_energy_ratio(hp_slice, fs, cfg))
        rho_list.append(_peak_prominence(bp_slice, fs, cfg))
        rows.append(bp_slice)

    X = np.vstack(rows)
    X = _standardize_rows(X, eps=cfg.eps)
    return X, np.asarray(eta_list, dtype=float), np.asarray(rho_list, dtype=float)


def _nanmean_bpm(values: Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0 or not np.any(np.isfinite(arr)):
        return float("nan")
    return float(np.nanmean(arr))


def _fan_window_bpms(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    ch_list: Sequence[Any],
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    weight_mode: MrcWeightMode,
) -> Tuple[float, float, dict]:
    """Fan MRC per modal; return best-modal BPM, equal-modal BPM, diagnostics."""
    modal_bpms: Dict[str, float] = {}
    modal_etas: Dict[str, float] = {}
    for variable in MODAL_VOTING_VARIABLES:
        ref_seg = multichannel_by_var[variable].get(seg_name)
        if ref_seg is None:
            continue
        ch_map = ref_seg["channels"]
        X, eta, rho = _collect_modal_window_matrix(ch_list, ch_map, variable, st, end, fs, cfg)
        g = compute_mrc_weights(eta, mode=weight_mode, rho=rho, eps=cfg.eps)
        y = np.sum(g[:, None] * X, axis=0)
        eta_fused = _energy_ratio(y, fs, cfg)
        bpm, _fp, _f, _p = estimate_bpm_from_waveform(y, fs, cfg=cfg)
        modal_bpms[variable] = bpm
        modal_etas[variable] = eta_fused

    if not modal_bpms:
        return float("nan"), float("nan"), {"modal_etas": {}, "best_modal": None}

    best_modal = max(modal_etas, key=lambda k: modal_etas[k])
    return (
        modal_bpms[best_modal],
        _nanmean_bpm(list(modal_bpms.values())),
        {"modal_etas": modal_etas, "best_modal": best_modal, "modal_bpms": modal_bpms},
    )


def _mrc_pca_window_bpms(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    ch_list: Sequence[Any],
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    *,
    weight_mode: MrcWeightMode = "sqrt",
    use_pca_sign: bool = True,
    pca_top_k: int = 36,
) -> Tuple[float, float, dict]:
    modal_bpms: Dict[str, float] = {}
    modal_etas: Dict[str, float] = {}
    pca_info: Dict[str, dict] = {}
    for variable in MODAL_VOTING_VARIABLES:
        ref_seg = multichannel_by_var[variable].get(seg_name)
        if ref_seg is None:
            continue
        ch_map = ref_seg["channels"]
        X, eta, rho = _collect_modal_window_matrix(ch_list, ch_map, variable, st, end, fs, cfg)
        y, info = mrc_pca_fusion(
            X,
            eta,
            weight_mode=weight_mode,
            use_pca_sign=use_pca_sign,
            top_k=pca_top_k,
            rho=rho,
            eps=cfg.eps,
        )
        eta_fused = _energy_ratio(y, fs, cfg)
        bpm, _fp, _f, _p = estimate_bpm_from_waveform(y, fs, cfg=cfg)
        modal_bpms[variable] = bpm
        modal_etas[variable] = eta_fused
        info["eta_fused"] = eta_fused
        pca_info[variable] = info

    if not modal_bpms:
        return float("nan"), float("nan"), {"modal_etas": {}, "best_modal": None}

    best_modal = max(modal_etas, key=lambda k: modal_etas[k])
    return (
        modal_bpms[best_modal],
        _nanmean_bpm(list(modal_bpms.values())),
        {
            "modal_etas": modal_etas,
            "best_modal": best_modal,
            "modal_bpms": modal_bpms,
            "pca_info": pca_info,
        },
    )


def estimate_wifi_mrc_segment(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    *,
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    pca_top_k: int = 36,
    verbose: bool = False,
) -> Optional[dict]:
    """Per-segment WiFi MRC methods (Fan + MRC-PCA variants)."""
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()

    ref_seg = multichannel_by_var["phases"].get(seg_name)
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
    seg_var = ref_seg.get("variable", "phases")
    ref_len = max(len(ch_map[c][seg_var]["bandpass_filtered"]) for c in ch_list)
    win_len = int(round(mp.window_length_sec * fs))
    step_len = int(round(mp.step_length_sec * fs))
    if ref_len < win_len:
        if verbose:
            print(f"⚠️  {seg_name}: length {ref_len} < window {win_len}, skip")
        return None

    starts = _sliding_window_indices(ref_len, win_len, step_len)
    fan_linear: List[float] = []
    fan_sqrt: List[float] = []
    fan_equal: List[float] = []
    mrc_sqrt: List[float] = []
    mrc_equal: List[float] = []
    mrc_no_sign: List[float] = []
    best_modals_fan: List[Optional[str]] = []
    best_modals_mrc: List[Optional[str]] = []

    for st in starts:
        end = st + win_len
        b_best, b_equal, info = _fan_window_bpms(
            multichannel_by_var, seg_name, ch_list, st, end, fs, cfg, "linear"
        )
        fan_linear.append(b_best)
        fan_equal.append(b_equal)
        best_modals_fan.append(info.get("best_modal"))

        b_best_s, _b_equal_s, _ = _fan_window_bpms(
            multichannel_by_var, seg_name, ch_list, st, end, fs, cfg, "sqrt"
        )
        fan_sqrt.append(b_best_s)

        b_mrc, b_mrc_eq, info_m = _mrc_pca_window_bpms(
            multichannel_by_var,
            seg_name,
            ch_list,
            st,
            end,
            fs,
            cfg,
            use_pca_sign=True,
            pca_top_k=pca_top_k,
        )
        mrc_sqrt.append(b_mrc)
        mrc_equal.append(b_mrc_eq)
        best_modals_mrc.append(info_m.get("best_modal"))

        b_no, _, _ = _mrc_pca_window_bpms(
            multichannel_by_var,
            seg_name,
            ch_list,
            st,
            end,
            fs,
            cfg,
            use_pca_sign=False,
            pca_top_k=pca_top_k,
        )
        mrc_no_sign.append(b_no)

    return {
        "segment": seg_name,
        "bpm_gt": bpm_gt,
        "metadata": metadata,
        "fan_eta_linear": _seg_bpm_stats(np.asarray(fan_linear), bpm_gt, len(starts)),
        "fan_eta_sqrt": _seg_bpm_stats(np.asarray(fan_sqrt), bpm_gt, len(starts)),
        "fan_eta_equal": _seg_bpm_stats(np.asarray(fan_equal), bpm_gt, len(starts)),
        "mrc_pca_eta_sqrt": _seg_bpm_stats(np.asarray(mrc_sqrt), bpm_gt, len(starts)),
        "mrc_pca_eta_equal": _seg_bpm_stats(np.asarray(mrc_equal), bpm_gt, len(starts)),
        "mrc_pca_no_sign": _seg_bpm_stats(np.asarray(mrc_no_sign), bpm_gt, len(starts)),
        "fan_best_modal_per_window": best_modals_fan,
        "mrc_best_modal_per_window": best_modals_mrc,
    }


def estimate_wifi_mrc_ablation_segment(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    *,
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    pca_top_k: int = 36,
    verbose: bool = False,
) -> Optional[dict]:
    """Per-segment ablation variants: Fan-ηρ and MRC-PCA-η-linear."""
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()

    ref_seg = multichannel_by_var["phases"].get(seg_name)
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
    seg_var = ref_seg.get("variable", "phases")
    ref_len = max(len(ch_map[c][seg_var]["bandpass_filtered"]) for c in ch_list)
    win_len = int(round(mp.window_length_sec * fs))
    step_len = int(round(mp.step_length_sec * fs))
    if ref_len < win_len:
        if verbose:
            print(f"⚠️  {seg_name}: length {ref_len} < window {win_len}, skip")
        return None

    starts = _sliding_window_indices(ref_len, win_len, step_len)
    fan_rho_linear: List[float] = []
    fan_rho_equal: List[float] = []
    mrc_linear_equal: List[float] = []

    for st in starts:
        end = st + win_len
        b_best, b_equal, _info = _fan_window_bpms(
            multichannel_by_var, seg_name, ch_list, st, end, fs, cfg, "eta_rho"
        )
        fan_rho_linear.append(b_best)
        fan_rho_equal.append(b_equal)

        _b_mrc, b_mrc_eq, _info_m = _mrc_pca_window_bpms(
            multichannel_by_var,
            seg_name,
            ch_list,
            st,
            end,
            fs,
            cfg,
            weight_mode="linear",
            use_pca_sign=True,
            pca_top_k=pca_top_k,
        )
        mrc_linear_equal.append(b_mrc_eq)

    return {
        "segment": seg_name,
        "bpm_gt": bpm_gt,
        "metadata": metadata,
        "fan_eta_rho_linear": _seg_bpm_stats(np.asarray(fan_rho_linear), bpm_gt, len(starts)),
        "fan_eta_rho_equal": _seg_bpm_stats(np.asarray(fan_rho_equal), bpm_gt, len(starts)),
        "mrc_pca_eta_linear": _seg_bpm_stats(np.asarray(mrc_linear_equal), bpm_gt, len(starts)),
    }


def _merge_baseline_results(
    merged: Dict[str, Optional[dict]],
    baseline_partial: Dict[str, Optional[dict]],
    method_key: str,
    baseline_key: str,
) -> None:
    for seg_name, row in baseline_partial.items():
        if row is None:
            merged.setdefault(seg_name, None)
            continue
        block = row.get(baseline_key)
        if block is None:
            continue
        if merged.get(seg_name) is None:
            merged[seg_name] = {
                "segment": seg_name,
                "bpm_gt": row.get("bpm_gt"),
                "metadata": row.get("metadata", {}),
            }
        merged[seg_name][method_key] = block


def run_wifi_mrc_benchmark(
    frames,
    segment_config: Dict[str, dict],
    *,
    filter_params: Optional[FilterParams] = None,
    metric_params: Optional[BreathMetricParams] = None,
    config: Optional[ChFusionConfig] = None,
    plan2_config: Optional[Plan2Config] = None,
    verbose: bool = True,
    cache_dir: Optional[str] = None,
    multichannel_by_var: Optional[Dict[str, Dict[str, Optional[dict]]]] = None,
    pca_top_k: int = 36,
) -> dict:
    """Run WiFi MRC methods plus required baselines for one scenario."""
    cfg = config or ChFusionConfig()
    fp = filter_params or FilterParams()
    mp = metric_params or BreathMetricParams()
    p2 = plan2_config or Plan2Config(channel_metric="energy_ratio")
    vcfg = VotingConfig(voting_strategy="eta_rho_weighted")

    if multichannel_by_var is None:
        multichannel_by_var = {}
        for variable in MODAL_VOTING_VARIABLES:
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
    seg_names = sorted(multichannel_by_var["phases"].keys())

    if verbose:
        print("\n--- WiFi MRC methods (Fan + MRC-PCA) ---")
    for seg_name in seg_names:
        row = estimate_wifi_mrc_segment(
            multichannel_by_var,
            seg_name,
            config=cfg,
            metric_params=mp,
            pca_top_k=pca_top_k,
            verbose=verbose,
        )
        if row is None:
            merged[seg_name] = None
            continue
        merged[seg_name] = {
            "segment": seg_name,
            "bpm_gt": row["bpm_gt"],
            "metadata": row["metadata"],
        }
        for key in MRC_METHOD_KEYS:
            merged[seg_name][key] = row[key]
        if verbose:
            stats = _overall_rel_error({seg_name: row}, "fan_eta_linear")
            print(
                f"  {seg_name} fan_linear {stats['mean_rel_err_pct']:.2f}% | "
                f"mrc_pca { _overall_rel_error({seg_name: row}, 'mrc_pca_eta_sqrt')['mean_rel_err_pct']:.2f}%"
            )

    if verbose:
        print("\n--- Baselines (B0 / Uniform / Modal top2 / B1 Vote→Equal) ---")
    voting_bench = run_voting_fusion_benchmark(
        frames,
        segment_config,
        filter_params=fp,
        metric_params=mp,
        config=cfg,
        plan2_config=p2,
        verbose=False,
        cache_dir=cache_dir,
        multichannel_by_var=multichannel_by_var,
    )
    _merge_baseline_results(merged, voting_bench["results"], "b0_single_remote", "b0_single_remote")
    _merge_baseline_results(merged, voting_bench["results"], "b1_uniform_remote", "b1_uniform_remote")
    _merge_baseline_results(
        merged, voting_bench["results"], "b2_modal_top2_equal", "b2_modal_top2_equal"
    )

    b1_partial: Dict[str, Optional[dict]] = {}
    for seg_name in seg_names:
        b1_partial[seg_name] = estimate_systematic_fusion_segment(
            multichannel_by_var,
            seg_name,
            channel_strategy="vote",
            modal_strategy="equal",
            config=cfg,
            metric_params=mp,
            vcfg=vcfg,
            persistence_masks=None,
            verbose=False,
        )
    _merge_baseline_results(
        merged, b1_partial, "b1_vote_modal_equal", "b1_vote_modal_equal"
    )

    if verbose:
        for label, key, _ in WIFI_MRC_METHOD_SPECS:
            stats = _overall_rel_error(merged, key)
            if np.isfinite(stats["mean_rel_err_pct"]):
                print(f"✓ [{key}] {label} | mean err {stats['mean_rel_err_pct']:.2f}%")

    return {
        "results": merged,
        "multichannel_by_var": multichannel_by_var,
        "method_specs": WIFI_MRC_METHOD_SPECS,
    }


def compute_wifi_mrc_cross_domain(
    results_by_scenario: Dict[str, dict],
) -> List[dict]:
    """Aggregate cross-domain leaderboard rows."""
    agg: List[dict] = []
    for label, key, color in WIFI_MRC_METHOD_SPECS:
        per_scenario: Dict[str, float] = {}
        for sid, bench in results_by_scenario.items():
            stats = _overall_rel_error(bench["results"], key)
            if np.isfinite(stats["mean_rel_err_pct"]):
                per_scenario[sid] = stats["mean_rel_err_pct"]
        if not per_scenario:
            continue
        means = list(per_scenario.values())
        agg.append(
            {
                "label": label,
                "method_key": key,
                "color": color,
                "cross_domain_mean": float(np.mean(means)),
                "cross_domain_std": float(np.std(means, ddof=1)) if len(means) > 1 else 0.0,
                "n_scenarios": len(means),
                "per_scenario": per_scenario,
            }
        )
    agg.sort(key=lambda r: r["cross_domain_mean"])
    for rank, row in enumerate(agg, start=1):
        row["rank"] = rank
    return agg


def compute_window_level_metrics(
    results: Dict[str, Optional[dict]],
    method_key: str,
) -> dict:
    """Window-level BPM error metrics for one method."""
    rel_errs: List[float] = []
    abs_bpms: List[float] = []
    for row in results.values():
        if row is None or row.get("bpm_gt") is None:
            continue
        block = row.get(method_key)
        if block is None:
            continue
        bpm_gt = float(row["bpm_gt"])
        per_win = block.get("bpm_per_window")
        signed = block.get("bpm_signed_err_per_window")
        if per_win is None:
            continue
        per_win = np.asarray(per_win, dtype=float)
        if signed is not None:
            signed_arr = np.asarray(signed, dtype=float)
        else:
            signed_arr = per_win - bpm_gt
        for i, bpm in enumerate(per_win):
            if not np.isfinite(bpm) or bpm_gt <= 0:
                continue
            rel_errs.append(abs(bpm - bpm_gt) / bpm_gt * 100.0)
            if signed is not None and i < len(signed_arr) and np.isfinite(signed_arr[i]):
                abs_bpms.append(abs(signed_arr[i]))
            else:
                abs_bpms.append(abs(bpm - bpm_gt))

    if not rel_errs:
        return {
            "p90_rel_err_pct": np.nan,
            "within_1_bpm_ratio": np.nan,
            "within_2_bpm_ratio": np.nan,
            "n_windows": 0,
        }
    rel_arr = np.asarray(rel_errs, dtype=float)
    abs_arr = np.asarray(abs_bpms, dtype=float)
    return {
        "p90_rel_err_pct": float(np.percentile(rel_arr, 90)),
        "within_1_bpm_ratio": float(np.mean(abs_arr <= 1.0)),
        "within_2_bpm_ratio": float(np.mean(abs_arr <= 2.0)),
        "n_windows": int(len(rel_arr)),
    }


def plot_wifi_mrc_figures(
    results_by_scenario: Dict[str, dict],
    cross_domain: List[dict],
    *,
    figures_dir,
    scenario_ids: Sequence[str],
    show: bool = False,
    save: bool = True,
) -> dict:
    """Generate leaderboard, cross-domain summary, per-scenario, and ablation figures."""
    import matplotlib.pyplot as plt

    figures_dir = Path(figures_dir)
    paths: dict = {}

    fig, ax = plt.subplots(figsize=(12, 7))
    labels = [r["label"] for r in cross_domain]
    means = [r["cross_domain_mean"] for r in cross_domain]
    colors = [r["color"] for r in cross_domain]
    y_pos = np.arange(len(labels))
    ax.barh(y_pos, means, color=colors, alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Cross-domain mean BPM err %")
    ax.set_title("WiFi MRC baselines — cross-domain leaderboard")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    lb_path = figures_dir / "wifi_mrc_baselines_leaderboard.png"
    if save:
        fig.savefig(lb_path, dpi=150, bbox_inches="tight")
    paths["leaderboard"] = lb_path
    if not show:
        plt.close(fig)

    fig, axes = plt.subplots(1, len(scenario_ids), figsize=(5 * len(scenario_ids), 6), sharey=True)
    if len(scenario_ids) == 1:
        axes = [axes]
    for ax_i, sid in zip(axes, scenario_ids):
        bench = results_by_scenario[sid]
        vals = []
        lbls = []
        cols = []
        for row in cross_domain:
            stats = _overall_rel_error(bench["results"], row["method_key"])
            if np.isfinite(stats["mean_rel_err_pct"]):
                vals.append(stats["mean_rel_err_pct"])
                lbls.append(row["label"])
                cols.append(row["color"])
        order = np.argsort(vals)
        vals = [vals[i] for i in order]
        lbls = [lbls[i] for i in order]
        cols = [cols[i] for i in order]
        ax_i.barh(np.arange(len(vals)), vals, color=cols, alpha=0.85)
        ax_i.set_yticks(np.arange(len(lbls)))
        ax_i.set_yticklabels(lbls, fontsize=7)
        ax_i.invert_yaxis()
        ax_i.set_title(sid)
        ax_i.set_xlabel("Mean BPM err %")
        ax_i.grid(True, axis="x", alpha=0.3)
    fig.suptitle("WiFi MRC baselines — per-scenario comparison", y=1.02)
    fig.tight_layout()
    summary_path = figures_dir / "wifi_mrc_baselines_cross_domain_summary.png"
    if save:
        fig.savefig(summary_path, dpi=150, bbox_inches="tight")
    paths["cross_domain_summary"] = summary_path
    if not show:
        plt.close(fig)

    for sid in scenario_ids:
        bench = results_by_scenario[sid]
        fig_s, ax_s = plt.subplots(figsize=(10, 6))
        vals = []
        lbls = []
        cols = []
        for label, key, color in WIFI_MRC_METHOD_SPECS:
            stats = _overall_rel_error(bench["results"], key)
            if np.isfinite(stats["mean_rel_err_pct"]):
                vals.append(stats["mean_rel_err_pct"])
                lbls.append(label)
                cols.append(color)
        order = np.argsort(vals)
        vals = [vals[i] for i in order]
        lbls = [lbls[i] for i in order]
        cols = [cols[i] for i in order]
        ax_s.barh(np.arange(len(vals)), vals, color=cols, alpha=0.85)
        ax_s.set_yticks(np.arange(len(lbls)))
        ax_s.set_yticklabels(lbls, fontsize=8)
        ax_s.invert_yaxis()
        ax_s.set_xlabel("Mean BPM err %")
        ax_s.set_title(f"WiFi MRC baselines — {sid}")
        ax_s.grid(True, axis="x", alpha=0.3)
        fig_s.tight_layout()
        tag = sid.replace("cs_", "")
        scen_path = figures_dir / f"wifi_mrc_baselines_{tag}.png"
        if save:
            fig_s.savefig(scen_path, dpi=150, bbox_inches="tight")
        paths[f"scenario_{sid}"] = scen_path
        if not show:
            plt.close(fig_s)

    ablation_keys = [
        ("MRC-PCA-η-sqrt", "mrc_pca_eta_sqrt", "indianred"),
        ("MRC-PCA-no-sign", "mrc_pca_no_sign", "gray"),
        ("Fan-η-linear", "fan_eta_linear", "coral"),
        ("Fan-η-equal", "fan_eta_equal", "darkorange"),
        ("B1 Vote→Equal", "b1_vote_modal_equal", "olive"),
    ]
    fig_a, ax_a = plt.subplots(figsize=(8, 5))
    x = np.arange(len(scenario_ids))
    width = 0.15
    for i, (label, key, color) in enumerate(ablation_keys):
        ys = []
        for sid in scenario_ids:
            stats = _overall_rel_error(results_by_scenario[sid]["results"], key)
            ys.append(stats["mean_rel_err_pct"])
        ax_a.bar(x + i * width, ys, width, label=label, color=color, alpha=0.85)
    ax_a.set_xticks(x + width * (len(ablation_keys) - 1) / 2)
    ax_a.set_xticklabels([s.replace("cs_", "") for s in scenario_ids])
    ax_a.set_ylabel("Mean BPM err %")
    ax_a.set_title("WiFi MRC ablation — key methods by scenario")
    ax_a.legend(fontsize=8, loc="upper right")
    ax_a.grid(True, axis="y", alpha=0.3)
    fig_a.tight_layout()
    ablation_path = figures_dir / "wifi_mrc_baselines_ablation.png"
    if save:
        fig_a.savefig(ablation_path, dpi=150, bbox_inches="tight")
    paths["ablation"] = ablation_path
    if not show:
        plt.close(fig_a)

    return paths


def _pearson_corr_vec(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    n = min(len(a), len(b))
    if n < 3:
        return float("nan")
    a = a[:n]
    b = b[:n]
    mask = np.isfinite(a) & np.isfinite(b)
    if np.sum(mask) < 3:
        return float("nan")
    a = a[mask]
    b = b[mask]
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _top_k_jaccard(a: np.ndarray, b: np.ndarray, k: int = 10) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    n = min(len(a), len(b))
    if n < k:
        return float("nan")
    a = a[:n]
    b = b[:n]
    set_a = set(np.argsort(-a)[:k].tolist())
    set_b = set(np.argsort(-b)[:k].tolist())
    union = set_a | set_b
    if not union:
        return float("nan")
    return float(len(set_a & set_b) / len(union))


def _iter_segment_windows(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    metric_params: Optional[BreathMetricParams] = None,
) -> List[Tuple[str, List[int], float, List[Any]]]:
    """Yield (seg_name, window_starts, fs, ch_list) for non-apnea segments."""
    mp = metric_params or BreathMetricParams()
    out: List[Tuple[str, List[int], float, List[Any]]] = []
    ref_mc = multichannel_by_var["phases"]
    for seg_name, ref_seg in ref_mc.items():
        if ref_seg is None:
            continue
        if ref_seg["metadata"].get("segment_type") == "apnea":
            continue
        ch_map = ref_seg["channels"]
        if not ch_map:
            continue
        ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
        fs = ref_seg["metadata"]["sampling_rate"]
        seg_var = ref_seg.get("variable", "phases")
        ref_len = max(len(ch_map[c][seg_var]["bandpass_filtered"]) for c in ch_list)
        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            continue
        starts = _sliding_window_indices(ref_len, win_len, step_len)
        out.append((seg_name, starts, fs, ch_list))
    return out


def run_wifi_mrc_diagnosis_pass(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    scenario_id: str,
    *,
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    pca_top_k: int = 36,
) -> dict:
    """Single pass collecting D1–D3 diagnostic traces across all segments."""
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()
    win_len_sec = mp.window_length_sec

    eta_by_modal: Dict[str, List[np.ndarray]] = {v: [] for v in MODAL_VOTING_VARIABLES}
    fan_best_modals: List[Optional[str]] = []
    mrc_best_modals: List[Optional[str]] = []
    fan_modal_bpms: List[Tuple[Optional[str], float, float]] = []
    mrc_modal_bpms: List[Tuple[Optional[str], float, float]] = []
    pca_loadings: List[np.ndarray] = []
    pca_explained: List[float] = []
    pca_sign_stability: List[float] = []

    for seg_name, starts, fs, ch_list in _iter_segment_windows(
        multichannel_by_var, metric_params=mp
    ):
        ref_seg = multichannel_by_var["phases"][seg_name]
        bpm_gt = ref_seg["metadata"].get("bpm_gt")
        win_len = int(round(win_len_sec * fs))

        for st in starts:
            end = st + win_len
            for variable in MODAL_VOTING_VARIABLES:
                ref_var_seg = multichannel_by_var[variable].get(seg_name)
                if ref_var_seg is None:
                    continue
                ch_map = ref_var_seg["channels"]
                _X, eta, _rho = _collect_modal_window_matrix(
                    ch_list, ch_map, variable, st, end, fs, cfg
                )
                eta_by_modal[variable].append(eta)

            b_best, _b_eq, info_f = _fan_window_bpms(
                multichannel_by_var, seg_name, ch_list, st, end, fs, cfg, "linear"
            )
            fan_best_modals.append(info_f.get("best_modal"))
            if bpm_gt and bpm_gt > 0 and np.isfinite(b_best):
                fan_modal_bpms.append(
                    (info_f.get("best_modal"), b_best, abs(b_best - bpm_gt) / bpm_gt * 100.0)
                )

            b_mrc, _b_eq_m, info_m = _mrc_pca_window_bpms(
                multichannel_by_var,
                seg_name,
                ch_list,
                st,
                end,
                fs,
                cfg,
                weight_mode="sqrt",
                use_pca_sign=True,
                pca_top_k=pca_top_k,
            )
            mrc_best_modals.append(info_m.get("best_modal"))
            if bpm_gt and bpm_gt > 0 and np.isfinite(b_mrc):
                mrc_modal_bpms.append(
                    (info_m.get("best_modal"), b_mrc, abs(b_mrc - bpm_gt) / bpm_gt * 100.0)
                )

            best_modal = info_m.get("best_modal")
            if best_modal and best_modal in info_m.get("pca_info", {}):
                pinfo = info_m["pca_info"][best_modal]
                loadings = np.asarray(pinfo.get("loadings", []), dtype=float)
                if loadings.size:
                    pca_loadings.append(loadings)
                    evr = pinfo.get("explained_variance_ratio", float("nan"))
                    pca_explained.append(float(evr) if evr is not None else float("nan"))
                    if len(pca_loadings) >= 2:
                        prev = pca_loadings[-2]
                        signs_prev = np.sign(prev)
                        signs_curr = np.sign(loadings)
                        n = min(len(signs_prev), len(signs_curr))
                        if n > 0:
                            agree = np.mean(signs_prev[:n] == signs_curr[:n])
                            pca_sign_stability.append(float(agree))

    return {
        "scenario_id": scenario_id,
        "eta_by_modal": eta_by_modal,
        "fan_best_modals": fan_best_modals,
        "mrc_best_modals": mrc_best_modals,
        "fan_modal_bpms": fan_modal_bpms,
        "mrc_modal_bpms": mrc_modal_bpms,
        "pca_loadings": pca_loadings,
        "pca_explained": pca_explained,
        "pca_sign_stability": pca_sign_stability,
    }


def compute_eta_stability_diagnostics(
    trace: dict,
) -> dict:
    """D1: per-window η stability from diagnosis trace."""
    scenario_id = trace["scenario_id"]
    summary: Dict[str, dict] = {}
    curves: Dict[str, List[float]] = {}

    for variable in MODAL_VOTING_VARIABLES:
        eta_windows = trace["eta_by_modal"].get(variable, [])
        if len(eta_windows) < 2:
            continue
        pearson_rs: List[float] = []
        jaccards: List[float] = []
        for i in range(len(eta_windows) - 1):
            if len(eta_windows[i]) != len(eta_windows[i + 1]):
                continue
            pearson_rs.append(_pearson_corr_vec(eta_windows[i], eta_windows[i + 1]))
            jaccards.append(_top_k_jaccard(eta_windows[i], eta_windows[i + 1], k=10))

        valid_windows = [w for w in eta_windows if len(w) > 0]
        if not valid_windows:
            continue
        max_len = max(len(w) for w in valid_windows)
        padded = []
        for w in valid_windows:
            if len(w) == max_len:
                padded.append(w)
            else:
                pad = np.full(max_len, np.nan)
                pad[: len(w)] = w
                padded.append(pad)
        stacked = np.vstack(padded)
        tone_cv = np.std(stacked, axis=0) / (np.mean(stacked, axis=0) + 1e-12)
        mean_cv = float(np.nanmean(tone_cv))

        key = MODAL_SHORT_NAMES.get(variable, variable)
        summary[key] = {
            "mean_adjacent_pearson_r": float(np.nanmean(pearson_rs)),
            "std_adjacent_pearson_r": float(np.nanstd(pearson_rs)),
            "mean_top10_jaccard": float(np.nanmean(jaccards)),
            "mean_eta_cv": mean_cv,
            "n_windows": len(eta_windows),
        }
        curves[key] = pearson_rs

    return {"scenario_id": scenario_id, "by_modal": summary, "pearson_curves": curves}


def compute_modal_switching_diagnostics(
    trace: dict,
    method_key: str = "fan",
) -> dict:
    """D2: best-modal distribution and switch frequency."""
    scenario_id = trace["scenario_id"]
    modals = trace["fan_best_modals"] if method_key == "fan" else trace["mrc_best_modals"]
    bpm_rows = trace["fan_modal_bpms"] if method_key == "fan" else trace["mrc_modal_bpms"]

    counts: Dict[str, int] = {}
    for m in modals:
        if m is None:
            continue
        short = MODAL_SHORT_NAMES.get(m, m)
        counts[short] = counts.get(short, 0) + 1

    switches = 0
    valid_pairs = 0
    for i in range(len(modals) - 1):
        if modals[i] is None or modals[i + 1] is None:
            continue
        valid_pairs += 1
        if modals[i] != modals[i + 1]:
            switches += 1
    switch_rate = float(switches / valid_pairs) if valid_pairs else float("nan")

    err_by_modal: Dict[str, List[float]] = {}
    for modal, _bpm, err in bpm_rows:
        if modal is None:
            continue
        short = MODAL_SHORT_NAMES.get(modal, modal)
        err_by_modal.setdefault(short, []).append(err)

    mean_err_by_modal = {
        k: float(np.mean(v)) for k, v in err_by_modal.items() if v
    }

    return {
        "scenario_id": scenario_id,
        "method_key": method_key,
        "modal_counts": counts,
        "switch_rate": switch_rate,
        "n_windows": len(modals),
        "mean_err_by_modal": mean_err_by_modal,
    }


def compute_pca_loading_diagnostics(trace: dict) -> dict:
    """D3: PCA loading consistency from diagnosis trace."""
    scenario_id = trace["scenario_id"]
    loadings = trace.get("pca_loadings", [])
    explained = trace.get("pca_explained", [])
    sign_stab = trace.get("pca_sign_stability", [])

    cosines: List[float] = []
    for i in range(len(loadings) - 1):
        a = loadings[i]
        b = loadings[i + 1]
        n = min(len(a), len(b))
        if n < 2:
            continue
        a = a[:n]
        b = b[:n]
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na > 1e-12 and nb > 1e-12:
            cosines.append(float(np.dot(a, b) / (na * nb)))

    return {
        "scenario_id": scenario_id,
        "mean_loading_cosine": float(np.nanmean(cosines)) if cosines else float("nan"),
        "std_loading_cosine": float(np.nanstd(cosines)) if cosines else float("nan"),
        "loading_cosine_series": cosines,
        "mean_explained_variance_ratio": float(np.nanmean(explained)) if explained else float("nan"),
        "mean_sign_stability": float(np.nanmean(sign_stab)) if sign_stab else float("nan"),
        "n_windows": len(loadings),
    }


def run_wifi_mrc_ablation_benchmark(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    pca_top_k: int = 36,
    verbose: bool = False,
) -> dict:
    """Run A1/A2 ablation variants only."""
    merged: Dict[str, Optional[dict]] = {}
    seg_names = sorted(multichannel_by_var["phases"].keys())
    for seg_name in seg_names:
        row = estimate_wifi_mrc_ablation_segment(
            multichannel_by_var,
            seg_name,
            config=config,
            metric_params=metric_params,
            pca_top_k=pca_top_k,
            verbose=verbose,
        )
        if row is None:
            merged[seg_name] = None
            continue
        merged[seg_name] = {
            "segment": seg_name,
            "bpm_gt": row["bpm_gt"],
            "metadata": row["metadata"],
        }
        for _label, key, _color in WIFI_MRC_ABLATION_SPECS:
            merged[seg_name][key] = row[key]
    return {"results": merged, "method_specs": WIFI_MRC_ABLATION_SPECS}


def compute_ablation_decomposition(
    ablation_by_scenario: Dict[str, dict],
    reference: Dict[str, float],
) -> List[dict]:
    """Build ablation decomposition table vs reference methods."""
    rows: List[dict] = []
    scenario_ids = sorted(ablation_by_scenario.keys())

    def _xdom_mean(key: str) -> float:
        vals = []
        for sid in scenario_ids:
            stats = _overall_rel_error(ablation_by_scenario[sid]["results"], key)
            if np.isfinite(stats["mean_rel_err_pct"]):
                vals.append(stats["mean_rel_err_pct"])
        return float(np.mean(vals)) if vals else float("nan")

    fan_eta_rho_equal = _xdom_mean("fan_eta_rho_equal")
    fan_eta_equal = reference.get("fan_eta_equal", float("nan"))
    b1 = reference.get("b1_vote_modal_equal", float("nan"))

    eta_rho_contrib = fan_eta_equal - fan_eta_rho_equal if np.isfinite(fan_eta_equal) else float("nan")
    voting_contrib = fan_eta_rho_equal - b1 if np.isfinite(b1) else float("nan")

    for label, key, color in WIFI_MRC_ABLATION_SPECS:
        per_scenario: Dict[str, float] = {}
        for sid in scenario_ids:
            stats = _overall_rel_error(ablation_by_scenario[sid]["results"], key)
            if np.isfinite(stats["mean_rel_err_pct"]):
                per_scenario[sid] = stats["mean_rel_err_pct"]
        means = list(per_scenario.values())
        rows.append(
            {
                "label": label,
                "method_key": key,
                "color": color,
                "cross_domain_mean": float(np.mean(means)) if means else float("nan"),
                "per_scenario": per_scenario,
            }
        )

    rows.append(
        {
            "label": "η·ρ vs η (quality metric)",
            "method_key": "_eta_rho_contrib",
            "color": "steelblue",
            "cross_domain_mean": eta_rho_contrib,
            "per_scenario": {},
        }
    )
    rows.append(
        {
            "label": "Voting vs MRC (channel fusion)",
            "method_key": "_voting_contrib",
            "color": "darkorange",
            "cross_domain_mean": voting_contrib,
            "per_scenario": {},
        }
    )
    return rows


def plot_wifi_mrc_diagnosis_figures(
    d1_by_scenario: Dict[str, dict],
    d2_fan_by_scenario: Dict[str, dict],
    d2_mrc_by_scenario: Dict[str, dict],
    d3_by_scenario: Dict[str, dict],
    ablation_rows: List[dict],
    reference_rows: List[dict],
    *,
    figures_dir,
    scenario_ids: Sequence[str],
    show: bool = False,
    save: bool = True,
) -> dict:
    """Generate diagnosis plan figures (D1–D3 + ablation)."""
    import matplotlib.pyplot as plt

    figures_dir = Path(figures_dir)
    paths: dict = {}
    modal_keys = ["remote", "local", "phase"]

    fig, axes = plt.subplots(1, len(scenario_ids), figsize=(4.5 * len(scenario_ids), 4), sharey=True)
    if len(scenario_ids) == 1:
        axes = [axes]
    for ax, sid in zip(axes, scenario_ids):
        d1 = d1_by_scenario[sid]
        for mk in modal_keys:
            curve = d1.get("pearson_curves", {}).get(mk, [])
            if curve:
                ax.plot(curve, label=mk, alpha=0.8)
        ax.set_title(sid.replace("cs_", ""))
        ax.set_xlabel("Adjacent window index")
        ax.set_ylabel("η Pearson r")
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)
    fig.suptitle("D1: Adjacent-window η correlation by modal")
    fig.tight_layout()
    p1 = figures_dir / "wifi_mrc_diagnosis_eta_stability.png"
    if save:
        fig.savefig(p1, dpi=150, bbox_inches="tight")
    paths["eta_stability"] = p1
    if not show:
        plt.close(fig)

    fig, axes = plt.subplots(2, len(scenario_ids), figsize=(4.5 * len(scenario_ids), 7))
    if len(scenario_ids) == 1:
        axes = axes.reshape(2, 1)
    for col, sid in enumerate(scenario_ids):
        for row, (d2_dict, title) in enumerate(
            [(d2_fan_by_scenario, "Fan-η-linear"), (d2_mrc_by_scenario, "MRC-PCA-η-sqrt")]
        ):
            ax = axes[row, col]
            d2 = d2_dict[sid]
            counts = d2.get("modal_counts", {})
            keys = list(counts.keys())
            vals = [counts[k] for k in keys]
            ax.bar(keys, vals, color=["steelblue", "seagreen", "mediumpurple"][: len(keys)], alpha=0.85)
            ax.set_title(f"{sid.replace('cs_', '')} — {title}\nswitch={d2.get('switch_rate', 0):.1%}")
            ax.tick_params(axis="x", rotation=20)
    fig.suptitle("D2: Best-modal selection distribution")
    fig.tight_layout()
    p2 = figures_dir / "wifi_mrc_diagnosis_modal_switching.png"
    if save:
        fig.savefig(p2, dpi=150, bbox_inches="tight")
    paths["modal_switching"] = p2
    if not show:
        plt.close(fig)

    fig, axes = plt.subplots(1, len(scenario_ids), figsize=(4.5 * len(scenario_ids), 4), sharey=True)
    if len(scenario_ids) == 1:
        axes = [axes]
    for ax, sid in zip(axes, scenario_ids):
        d3 = d3_by_scenario[sid]
        series = d3.get("loading_cosine_series", [])
        if series:
            ax.plot(series, color="indianred", alpha=0.85)
        ax.axhline(d3.get("mean_loading_cosine", np.nan), color="k", ls="--", lw=0.8)
        ax.set_title(f"{sid.replace('cs_', '')}\nEVR={d3.get('mean_explained_variance_ratio', 0):.2f}")
        ax.set_xlabel("Adjacent window index")
        ax.set_ylabel("PCA loading cosine")
        ax.grid(True, alpha=0.3)
    fig.suptitle("D3: MRC-PCA loading consistency")
    fig.tight_layout()
    p3 = figures_dir / "wifi_mrc_diagnosis_pca_loading.png"
    if save:
        fig.savefig(p3, dpi=150, bbox_inches="tight")
    paths["pca_loading"] = p3
    if not show:
        plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    metrics = ["mean_adjacent_pearson_r", "mean_top10_jaccard", "mean_eta_cv"]
    titles = ["η adjacent r", "Top-10 Jaccard", "η CV"]
    x = np.arange(len(scenario_ids))
    width = 0.25
    for mi, (metric, title) in enumerate(zip(metrics, titles)):
        ax = axes[mi]
        for j, mk in enumerate(modal_keys):
            ys = []
            for sid in scenario_ids:
                val = d1_by_scenario[sid]["by_modal"].get(mk, {}).get(metric, np.nan)
                ys.append(val)
            ax.bar(x + j * width, ys, width, label=mk, alpha=0.85)
        ax.set_xticks(x + width)
        ax.set_xticklabels([s.replace("cs_", "") for s in scenario_ids])
        ax.set_title(title)
        ax.legend(fontsize=7)
        ax.grid(True, axis="y", alpha=0.3)
    fig.suptitle("D1 summary metrics by scenario")
    fig.tight_layout()
    p4 = figures_dir / "wifi_mrc_diagnosis_summary.png"
    if save:
        fig.savefig(p4, dpi=150, bbox_inches="tight")
    paths["summary"] = p4
    if not show:
        plt.close(fig)

    compare_keys = [
        ("B1 Vote→Equal", "b1_vote_modal_equal", reference_rows, "olive"),
        ("Fan-η-equal", "fan_eta_equal", reference_rows, "darkorange"),
        ("Fan-ηρ-equal", "fan_eta_rho_equal", ablation_rows, "saddlebrown"),
        ("MRC-PCA-η-linear", "mrc_pca_eta_linear", ablation_rows, "firebrick"),
    ]
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = [c[0] for c in compare_keys]
    xdom_vals = []
    for _lbl, key, rows, _c in compare_keys:
        found = next((r["cross_domain_mean"] for r in rows if r.get("method_key") == key), np.nan)
        xdom_vals.append(found)
    colors = [c[3] for c in compare_keys]
    ax.barh(np.arange(len(labels)), xdom_vals, color=colors, alpha=0.85)
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("Cross-domain mean BPM err %")
    ax.set_title("A1/A2 ablation vs reference")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    p5 = figures_dir / "wifi_mrc_diagnosis_ablation_leaderboard.png"
    if save:
        fig.savefig(p5, dpi=150, bbox_inches="tight")
    paths["ablation_leaderboard"] = p5
    if not show:
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    decomp = [r for r in ablation_rows if r["method_key"].startswith("_")]
    if decomp:
        dl = [r["label"] for r in decomp]
        dv = [r["cross_domain_mean"] for r in decomp]
        ax.barh(np.arange(len(dl)), dv, color=[r["color"] for r in decomp], alpha=0.85)
        ax.set_yticks(np.arange(len(dl)))
        ax.set_yticklabels(dl, fontsize=9)
        ax.invert_yaxis()
        ax.set_xlabel("Contribution to B1 advantage over Fan-η-equal (pp)")
        ax.set_title("Ablation decomposition")
        ax.axvline(0, color="k", lw=0.8)
        ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    p6 = figures_dir / "wifi_mrc_diagnosis_ablation_decomposition.png"
    if save:
        fig.savefig(p6, dpi=150, bbox_inches="tight")
    paths["ablation_decomposition"] = p6
    if not show:
        plt.close(fig)

    return paths
