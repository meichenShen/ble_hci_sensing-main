"""B2 Coherent-MRC waveform fusion for BLE CS breathing BPM estimation.

Implements ``docs/plans/b2_coherent_mrc_waveform_fusion_plan.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np
from scipy.signal import find_peaks, hilbert, welch

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
    modal_fusion_from_spectra,
    per_modal_voting_spectrum,
)
from ble_analysis.voting_fusion import (
    MODAL_VOTING_VARIABLES,
    VotingConfig,
    run_voting_fusion_benchmark,
)
from ble_analysis.wifi_mrc import (
    WIFI_MRC_METHOD_SPECS,
    _collect_modal_window_matrix,
    _merge_baseline_results,
    compute_mrc_weights,
    estimate_bpm_from_waveform,
    mrc_pca_fusion,
)

PhaseMethod = Literal["pca_sign", "corr_sign", "hilbert", "fft_cross"]
WeightMode = Literal["eta_rho", "coherence_gated", "coherence_gated_sq"]
ModalWeightMode = Literal["equal", "eta", "eta_coherence", "shrink_to_equal"]

B2_PHASE1_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("B2-A0 PCA sign → equal modal", "b2_a0_pca_sign", "steelblue"),
    ("B2-A1 Corr sign → equal modal", "b2_a1_corr_sign", "royalblue"),
)

B2_ALL_SPECS: Tuple[Tuple[str, str, str], ...] = B2_PHASE1_SPECS + (
    ("B2-B Hilbert η·ρ → equal modal", "b2_b_hilbert", "teal"),
    ("B2-Bγ Hilbert coherence-gated → equal modal", "b2_b_gamma", "darkcyan"),
    ("B2-C FFT cross-spectrum → equal modal", "b2_c_fft_cross", "purple"),
    ("B2-D Two-level Hilbert-MRC", "b2_d_two_level", "crimson"),
    ("B2-D-eq Two-level equal modal", "b2_d_eq", "indianred"),
    ("B2-A0-D PCA sign → two-level Hilbert modal align", "b2_a0_d_two_level", "darkorange"),
    ("B2-A1-D Corr sign → two-level Hilbert modal align", "b2_a1_d_two_level", "orange"),
)

B2_METHOD_KEYS: Tuple[str, ...] = tuple(key for _l, key, _c in B2_ALL_SPECS)

MODAL_SHORT = {
    "remote_amplitudes": "remote",
    "local_amplitudes": "local",
    "phases": "phase",
}

__all__ = [
    "B2_PHASE1_SPECS",
    "B2_ALL_SPECS",
    "B2_METHOD_KEYS",
    "estimate_phase_corr_sign",
    "estimate_phase_hilbert",
    "estimate_phase_fft_cross_spectrum",
    "coherent_mrc_fuse_tones",
    "coherent_mrc_fuse_modals",
    "estimate_bpm_from_waveform_multi",
    "estimate_b2_segment",
    "run_b2_benchmark",
    "compute_b2_cross_domain",
    "plot_b2_figures",
    "plot_b2_achievement_figures",
]


def _quality_weights(
    eta: np.ndarray,
    rho: np.ndarray,
    eps: float = 1e-12,
) -> np.ndarray:
    q = np.asarray(eta, dtype=float) * np.clip(np.asarray(rho, dtype=float), 0.0, None)
    total = float(np.sum(q))
    if total <= eps:
        n = len(q)
        return np.full(n, 1.0 / n) if n else q
    return q / total


def _select_ref_idx(quality: np.ndarray, ref_idx: Optional[int] = None) -> int:
    q = np.asarray(quality, dtype=float)
    if ref_idx is not None and 0 <= ref_idx < len(q):
        return int(ref_idx)
    return int(np.argmax(q))


def estimate_phase_corr_sign(
    X: np.ndarray,
    quality: np.ndarray,
    ref_idx: int | None = None,
    eps: float = 1e-12,
) -> Tuple[np.ndarray, np.ndarray, dict]:
    """A1: Pairwise correlation sign correction."""
    X_arr = np.asarray(X, dtype=float)
    n_tones, _t = X_arr.shape
    q = np.asarray(quality, dtype=float)
    q = q / (float(np.sum(q)) + eps)

    ref = _select_ref_idx(q, ref_idx)
    x_ref = X_arr[ref]
    signs = np.ones(n_tones, dtype=float)
    for i in range(n_tones):
        if i == ref:
            continue
        xi = X_arr[i]
        mask = np.isfinite(xi) & np.isfinite(x_ref)
        if np.sum(mask) < 3:
            signs[i] = 1.0
            continue
        r = np.corrcoef(xi[mask], x_ref[mask])[0, 1]
        if not np.isfinite(r):
            signs[i] = 1.0
        else:
            s = np.sign(r)
            signs[i] = 1.0 if s == 0 else s

    w = signs * q
    w_sum = float(np.sum(np.abs(w)))
    if w_sum > eps:
        w = w / w_sum
    y = np.sum(w[:, None] * X_arr, axis=0)
    mu = float(np.mean(y))
    sd = float(np.std(y))
    y = (y - mu) / sd if sd > eps else (y - mu)
    return y, w, {"signs": signs, "ref_idx": ref, "phase_offsets": signs * np.pi}


def _apply_coherence_weights(
    base_w: np.ndarray,
    coherences: np.ndarray,
    weight_mode: WeightMode,
    min_coherence: float,
) -> np.ndarray:
    w = np.asarray(base_w, dtype=float).copy()
    gamma = np.clip(np.asarray(coherences, dtype=float), 0.0, 1.0)
    if weight_mode == "coherence_gated_sq":
        w = w * (gamma ** 2)
    elif weight_mode == "coherence_gated":
        w = w * gamma
    if min_coherence > 0:
        w = np.where(gamma >= min_coherence, w, 0.0)
    total = float(np.sum(w))
    if total <= 1e-12:
        return base_w / (float(np.sum(base_w)) + 1e-12)
    return w / total


def estimate_phase_hilbert(
    X: np.ndarray,
    quality: np.ndarray,
    ref_idx: int | None = None,
    min_coherence: float = 0.0,
    coherence_power: float = 1.0,
    eps: float = 1e-12,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """B: Hilbert analytic-signal phase alignment + optional coherence gating."""
    X_arr = np.asarray(X, dtype=float)
    n_tones, _t = X_arr.shape
    q = np.asarray(quality, dtype=float)
    q = q / (float(np.sum(q)) + eps)

    ref = _select_ref_idx(q, ref_idx)
    z_ref = hilbert(X_arr[ref])
    phases = np.zeros(n_tones, dtype=float)
    coherences = np.zeros(n_tones, dtype=float)

    for i in range(n_tones):
        z_i = hilbert(X_arr[i])
        cross = np.sum(z_i * np.conj(z_ref))
        phases[i] = float(np.angle(cross))
        denom = np.sqrt(np.sum(np.abs(z_i) ** 2) * np.sum(np.abs(z_ref) ** 2))
        coherences[i] = float(np.abs(cross) / denom) if denom > eps else 0.0

    coherences[ref] = 1.0
    phases[ref] = 0.0

    z_fused = np.zeros(_t, dtype=complex)
    w = q.copy()
    if coherence_power != 1.0:
        w = w * (coherences ** coherence_power)
    if min_coherence > 0:
        w = np.where(coherences >= min_coherence, w, 0.0)
    w_sum = float(np.sum(w))
    if w_sum <= eps:
        w = q
        w_sum = float(np.sum(w))
    w = w / w_sum

    for i in range(n_tones):
        z_i = hilbert(X_arr[i]) * np.exp(-1j * phases[i])
        z_fused += w[i] * z_i

    y = np.real(z_fused)
    mu = float(np.mean(y))
    sd = float(np.std(y))
    y = (y - mu) / sd if sd > eps else (y - mu)
    return y, phases, coherences, {"ref_idx": ref, "weights": w}


def estimate_phase_fft_cross_spectrum(
    X: np.ndarray,
    quality: np.ndarray,
    fs: float,
    f0: float,
    ref_idx: int | None = None,
    half_width_hz: float = 0.02,
    min_coherence: float = 0.0,
    eps: float = 1e-12,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """C: FFT cross-spectrum phase estimation around f0."""
    X_arr = np.asarray(X, dtype=float)
    n_tones, t_len = X_arr.shape
    q = np.asarray(quality, dtype=float)
    q = q / (float(np.sum(q)) + eps)
    ref = _select_ref_idx(q, ref_idx)

    nfft = int(2 ** np.ceil(np.log2(max(t_len, 4))))
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band = (freqs >= max(f0 - half_width_hz, 0.0)) & (freqs <= f0 + half_width_hz)
    if not np.any(band):
        return estimate_phase_hilbert(
            X_arr, q, ref_idx=ref, min_coherence=min_coherence, eps=eps
        )[:4]

    R = np.fft.rfft(X_arr[ref], n=nfft)
    phases = np.zeros(n_tones, dtype=float)
    coherences = np.zeros(n_tones, dtype=float)

    ref_power = float(np.sum(np.abs(R[band]) ** 2))
    for i in range(n_tones):
        Xi = np.fft.rfft(X_arr[i], n=nfft)
        cross_band = Xi[band] * np.conj(R[band])
        C_i = np.sum(cross_band)
        phases[i] = float(np.angle(C_i))
        num = float(np.abs(C_i))
        denom = np.sqrt(float(np.sum(np.abs(Xi[band]) ** 2)) * ref_power + eps)
        coherences[i] = num / denom if denom > eps else 0.0

    coherences[ref] = 1.0
    phases[ref] = 0.0

    z_fused = np.zeros(t_len, dtype=complex)
    w = _apply_coherence_weights(q, coherences, "coherence_gated", min_coherence)
    for i in range(n_tones):
        z_i = hilbert(X_arr[i]) * np.exp(-1j * phases[i])
        z_fused += w[i] * z_i

    y = np.real(z_fused)
    mu = float(np.mean(y))
    sd = float(np.std(y))
    y = (y - mu) / sd if sd > eps else (y - mu)
    return y, phases, coherences, {"ref_idx": ref, "weights": w, "f0": f0}


def coherent_mrc_fuse_tones(
    X: np.ndarray,
    eta: np.ndarray,
    rho: np.ndarray,
    *,
    phase_method: PhaseMethod = "hilbert",
    weight_mode: WeightMode = "eta_rho",
    ref_idx: int | None = None,
    f0: float | None = None,
    fs: float = 2.0,
    min_coherence: float = 0.0,
    pca_top_k: int = 36,
    eps: float = 1e-12,
) -> Tuple[np.ndarray, dict]:
    """Tone-level coherent MRC: 72 tones → 1 modal waveform."""
    X_arr = np.asarray(X, dtype=float)
    eta_arr = np.asarray(eta, dtype=float)
    rho_arr = np.asarray(rho, dtype=float)
    quality = eta_arr * np.clip(rho_arr, 0.0, None)
    info: dict = {"phase_method": phase_method, "weight_mode": weight_mode}

    if phase_method == "pca_sign":
        y, pca_info = mrc_pca_fusion(
            X_arr,
            eta_arr,
            weight_mode="eta_rho",
            use_pca_sign=True,
            top_k=pca_top_k,
            rho=rho_arr,
            eps=eps,
        )
        info.update(pca_info)
        return y, info

    if phase_method == "corr_sign":
        y, w, corr_info = estimate_phase_corr_sign(X_arr, quality, ref_idx=ref_idx, eps=eps)
        info.update(corr_info)
        info["weights"] = w
        return y, info

    if phase_method == "fft_cross":
        if f0 is None or not np.isfinite(f0) or f0 <= 0:
            f0 = 0.2
        y, phases, coherences, fft_info = estimate_phase_fft_cross_spectrum(
            X_arr,
            quality,
            fs=fs,
            f0=f0,
            ref_idx=ref_idx,
            min_coherence=min_coherence if weight_mode != "eta_rho" else 0.0,
        )
        info.update(fft_info)
        info["phase_offsets"] = phases
        info["coherences"] = coherences
        return y, info

    # hilbert
    use_gamma = weight_mode in ("coherence_gated", "coherence_gated_sq")
    power = 2.0 if weight_mode == "coherence_gated_sq" else 1.0
    y, phases, coherences, hil_info = estimate_phase_hilbert(
        X_arr,
        quality,
        ref_idx=ref_idx,
        min_coherence=min_coherence if use_gamma else 0.0,
        coherence_power=power if use_gamma else 1.0,
        eps=eps,
    )
    if use_gamma and min_coherence <= 0:
        base_q = quality / (float(np.sum(quality)) + eps)
        w = _apply_coherence_weights(base_q, coherences, weight_mode, 0.0)
        z_fused = np.zeros(X_arr.shape[1], dtype=complex)
        for i in range(X_arr.shape[0]):
            z_i = hilbert(X_arr[i]) * np.exp(-1j * phases[i])
            z_fused += w[i] * z_i
        y = np.real(z_fused)
        mu = float(np.mean(y))
        sd = float(np.std(y))
        y = (y - mu) / sd if sd > eps else (y - mu)
        hil_info["weights"] = w

    info.update(hil_info)
    info["phase_offsets"] = phases
    info["coherences"] = coherences
    return y, info


def coherent_mrc_fuse_modals(
    waveforms: Dict[str, np.ndarray],
    modal_etas: Dict[str, float],
    modal_weight_mode: ModalWeightMode = "equal",
    use_phase_align: bool = True,
    shrink_lambda: float = 0.5,
    eps: float = 1e-12,
) -> Tuple[np.ndarray, dict]:
    """Modal-level coherent fusion: 3 modal waveforms → 1 final waveform."""
    keys = [k for k in waveforms if waveforms[k] is not None and len(waveforms[k]) > 0]
    if not keys:
        return np.array([]), {}

    if not use_phase_align or len(keys) == 1:
        ys = [np.asarray(waveforms[k], dtype=float) for k in keys]
        y = np.mean(ys, axis=0)
        return y, {"modal_keys": keys, "phase_aligned": False}

    etas = {k: float(modal_etas.get(k, 0.0)) for k in keys}
    ref_key = max(etas, key=lambda k: etas[k])
    z_ref = hilbert(waveforms[ref_key])
    phases: Dict[str, float] = {}
    coherences: Dict[str, float] = {}
    for k in keys:
        z_k = hilbert(waveforms[k])
        cross = np.sum(z_k * np.conj(z_ref))
        phases[k] = float(np.angle(cross))
        denom = np.sqrt(np.sum(np.abs(z_k) ** 2) * np.sum(np.abs(z_ref) ** 2))
        coherences[k] = float(np.abs(cross) / denom) if denom > eps else 0.0

    if modal_weight_mode == "equal":
        raw_w = {k: 1.0 for k in keys}
    elif modal_weight_mode == "eta":
        raw_w = {k: max(etas[k], 0.0) for k in keys}
    elif modal_weight_mode == "eta_coherence":
        raw_w = {k: max(etas[k], 0.0) * coherences[k] for k in keys}
    else:  # shrink_to_equal
        scores = np.array([max(etas[k], 0.0) * coherences[k] for k in keys], dtype=float)
        s_sum = float(np.sum(scores))
        equal = 1.0 / len(keys)
        if s_sum <= eps:
            raw_w = {k: equal for k in keys}
        else:
            raw_w = {
                k: (1.0 - shrink_lambda) * equal + shrink_lambda * (scores[i] / s_sum)
                for i, k in enumerate(keys)
            }

    w_sum = float(sum(raw_w.values()))
    weights = {k: raw_w[k] / w_sum for k in keys}

    t_len = len(waveforms[keys[0]])
    z_fused = np.zeros(t_len, dtype=complex)
    for k in keys:
        z_k = hilbert(waveforms[k]) * np.exp(-1j * phases[k])
        z_fused += weights[k] * z_k
    y = np.real(z_fused)
    mu = float(np.mean(y))
    sd = float(np.std(y))
    y = (y - mu) / sd if sd > eps else (y - mu)
    return y, {
        "modal_keys": keys,
        "ref_modal": ref_key,
        "phases": phases,
        "coherences": coherences,
        "weights": weights,
        "phase_aligned": True,
    }


def estimate_bpm_from_waveform_multi(
    y: np.ndarray,
    fs: float,
    breath_band: Tuple[float, float] = (0.1, 0.35),
    cfg: Optional[ChFusionConfig] = None,
) -> dict:
    """Estimate BPM via PSD + ACF + peak-interval."""
    cfg = cfg or ChFusionConfig()
    sig = np.asarray(y, dtype=float)
    out: dict = {}
    bpm_psd, f_peak, freqs, pxx = estimate_bpm_from_waveform(sig, fs, breath_band, cfg=cfg)
    out["bpm_psd"] = bpm_psd
    out["f_peak"] = f_peak

    if len(sig) < 4 or not np.all(np.isfinite(sig)):
        out["bpm_acf"] = float("nan")
        out["bpm_peak"] = float("nan")
        out["bpm_consensus"] = bpm_psd
        return out

    sig0 = sig - np.mean(sig)
    acf = np.correlate(sig0, sig0, mode="full")
    acf = acf[len(acf) // 2 :]
    acf = acf / (acf[0] + cfg.eps)

    min_lag = int(max(1, fs / breath_band[1]))
    max_lag = int(min(len(acf) - 1, fs / breath_band[0]))
    if max_lag <= min_lag:
        out["bpm_acf"] = float("nan")
    else:
        segment = acf[min_lag : max_lag + 1]
        k = int(np.argmax(segment))
        lag = min_lag + k
        out["bpm_acf"] = float(60.0 * fs / lag)

    peaks, _props = find_peaks(sig0, distance=max(1, int(fs / breath_band[1])))
    if len(peaks) >= 2:
        intervals = np.diff(peaks) / fs
        med_interval = float(np.median(intervals))
        out["bpm_peak"] = float(60.0 / med_interval) if med_interval > cfg.eps else float("nan")
    else:
        out["bpm_peak"] = float("nan")

    candidates = [bpm_psd, out.get("bpm_acf", float("nan")), out.get("bpm_peak", float("nan"))]
    valid = [b for b in candidates if np.isfinite(b) and b > 0]
    out["bpm_consensus"] = float(np.median(valid)) if valid else bpm_psd
    return out


def _b1_f0_per_window(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    starts: Sequence[int],
    win_len: int,
    fs: float,
    cfg: ChFusionConfig,
    vcfg: VotingConfig,
) -> List[float]:
    """Per-window coarse f0 from B1 Vote→Equal pipeline."""
    ref_seg = multichannel_by_var["phases"].get(seg_name)
    if ref_seg is None:
        return [0.2] * len(starts)

    active_vars = list(MODAL_VOTING_VARIABLES)
    seg_maps: Dict[str, Dict[Any, dict]] = {}
    ch_lists: Dict[str, List[Any]] = {}
    for var in active_vars:
        seg = multichannel_by_var.get(var, {}).get(seg_name)
        if seg is None:
            return [0.2] * len(starts)
        seg_maps[var] = seg["channels"]
        ch_lists[var] = sorted(
            seg["channels"].keys(), key=lambda c: (isinstance(c, str), str(c))
        )

    nfft = cfg.nfft or int(2 ** np.ceil(np.log2(max(4 * win_len, 8))))
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
    band_freqs = freqs[band_mask]
    hann = np.hanning(win_len)

    f0_list: List[float] = []
    for st in starts:
        end = st + win_len
        spectra_by_var: Dict[str, np.ndarray] = {}
        scores_by_var: Dict[str, float] = {}
        for var in active_vars:
            spec, _bpm, info = per_modal_voting_spectrum(
                ch_lists[var],
                seg_maps[var],
                var,
                st,
                end,
                fs,
                cfg,
                vcfg,
                nfft,
                band_mask,
                band_freqs,
                hann,
            )
            short = MODAL_SHORT[var]
            spectra_by_var[short] = spec
            scores_by_var[short] = info["score"]
        bpm, _sel = modal_fusion_from_spectra(
            spectra_by_var, scores_by_var, "equal", band_freqs, cfg
        )
        f0_list.append(float(bpm / 60.0) if np.isfinite(bpm) and bpm > 0 else 0.2)
    return f0_list


def _window_b2_bpms(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    ch_list: Sequence[Any],
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    *,
    phase_method: PhaseMethod,
    weight_mode: WeightMode,
    modal_weight_mode: ModalWeightMode,
    use_two_level: bool,
    use_modal_phase_align: bool,
    f0: float | None,
    min_coherence: float,
    pca_top_k: int,
) -> Tuple[float, dict]:
    modal_waveforms: Dict[str, np.ndarray] = {}
    modal_etas: Dict[str, float] = {}
    tone_info: Dict[str, dict] = {}

    for variable in MODAL_VOTING_VARIABLES:
        ref_seg = multichannel_by_var[variable].get(seg_name)
        if ref_seg is None:
            continue
        ch_map = ref_seg["channels"]
        X, eta, rho = _collect_modal_window_matrix(ch_list, ch_map, variable, st, end, fs, cfg)
        y, info = coherent_mrc_fuse_tones(
            X,
            eta,
            rho,
            phase_method=phase_method,
            weight_mode=weight_mode,
            f0=f0,
            fs=fs,
            min_coherence=min_coherence,
            pca_top_k=pca_top_k,
        )
        short = MODAL_SHORT[variable]
        modal_waveforms[short] = y
        modal_etas[short] = _energy_ratio(y, fs, cfg)
        tone_info[short] = info

    if not modal_waveforms:
        return float("nan"), {}

    if use_two_level:
        y_final, modal_info = coherent_mrc_fuse_modals(
            modal_waveforms,
            modal_etas,
            modal_weight_mode=modal_weight_mode,
            use_phase_align=use_modal_phase_align,
        )
    else:
        ys = list(modal_waveforms.values())
        y_final = np.mean(ys, axis=0)
        modal_info = {"modal_keys": list(modal_waveforms.keys()), "phase_aligned": False}

    bpm_out = estimate_bpm_from_waveform_multi(y_final, fs, cfg=cfg)
    diag = {
        "modal_etas": modal_etas,
        "tone_info": tone_info,
        "modal_info": modal_info,
        "eta_fused": _energy_ratio(y_final, fs, cfg),
        **bpm_out,
    }
    return bpm_out["bpm_psd"], diag


def estimate_b2_segment(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    *,
    methods: Optional[Sequence[str]] = None,
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    vcfg: Optional[VotingConfig] = None,
    pca_top_k: int = 36,
    min_coherence: float = 0.2,
    verbose: bool = False,
) -> Optional[dict]:
    """Per-segment B2 estimation for configured method keys."""
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()
    vcfg = vcfg or VotingConfig(voting_strategy="eta_rho_weighted")

    method_configs: Dict[str, dict] = {
        "b2_a0_pca_sign": {
            "phase_method": "pca_sign",
            "weight_mode": "eta_rho",
            "use_two_level": False,
            "use_modal_phase_align": False,
            "f0_from_b1": False,
        },
        "b2_a1_corr_sign": {
            "phase_method": "corr_sign",
            "weight_mode": "eta_rho",
            "use_two_level": False,
            "use_modal_phase_align": False,
            "f0_from_b1": False,
        },
        "b2_b_hilbert": {
            "phase_method": "hilbert",
            "weight_mode": "eta_rho",
            "use_two_level": False,
            "use_modal_phase_align": False,
            "f0_from_b1": False,
        },
        "b2_b_gamma": {
            "phase_method": "hilbert",
            "weight_mode": "coherence_gated",
            "use_two_level": False,
            "use_modal_phase_align": False,
            "f0_from_b1": False,
            "min_coherence": min_coherence,
        },
        "b2_c_fft_cross": {
            "phase_method": "fft_cross",
            "weight_mode": "coherence_gated",
            "use_two_level": False,
            "use_modal_phase_align": False,
            "f0_from_b1": True,
            "min_coherence": 0.0,
        },
        "b2_d_two_level": {
            "phase_method": "hilbert",
            "weight_mode": "coherence_gated",
            "use_two_level": True,
            "use_modal_phase_align": True,
            "modal_weight_mode": "eta_coherence",
            "f0_from_b1": False,
            "min_coherence": min_coherence,
        },
        "b2_d_eq": {
            "phase_method": "hilbert",
            "weight_mode": "coherence_gated",
            "use_two_level": True,
            "use_modal_phase_align": False,
            "modal_weight_mode": "equal",
            "f0_from_b1": False,
            "min_coherence": min_coherence,
        },
        "b2_a0_d_two_level": {
            "phase_method": "pca_sign",
            "weight_mode": "eta_rho",
            "use_two_level": True,
            "use_modal_phase_align": True,
            "modal_weight_mode": "eta_coherence",
            "f0_from_b1": False,
        },
        "b2_a1_d_two_level": {
            "phase_method": "corr_sign",
            "weight_mode": "eta_rho",
            "use_two_level": True,
            "use_modal_phase_align": True,
            "modal_weight_mode": "eta_coherence",
            "f0_from_b1": False,
        },
    }

    active_methods = list(methods) if methods else list(method_configs.keys())
    for m in active_methods:
        if m not in method_configs:
            raise ValueError(f"Unknown B2 method key: {m}")

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
    f0_windows: Optional[List[float]] = None
    if any(method_configs[m].get("f0_from_b1") for m in active_methods):
        f0_windows = _b1_f0_per_window(
            multichannel_by_var, seg_name, starts, win_len, fs, cfg, vcfg
        )

    per_method_bpms: Dict[str, List[float]] = {m: [] for m in active_methods}
    for wi, st in enumerate(starts):
        end = st + win_len
        f0 = f0_windows[wi] if f0_windows is not None else None
        for m in active_methods:
            mc = method_configs[m]
            bpm, _diag = _window_b2_bpms(
                multichannel_by_var,
                seg_name,
                ch_list,
                st,
                end,
                fs,
                cfg,
                phase_method=mc["phase_method"],
                weight_mode=mc["weight_mode"],
                modal_weight_mode=mc.get("modal_weight_mode", "equal"),
                use_two_level=mc["use_two_level"],
                use_modal_phase_align=mc["use_modal_phase_align"],
                f0=f0 if mc.get("f0_from_b1") else None,
                min_coherence=mc.get("min_coherence", 0.0),
                pca_top_k=pca_top_k,
            )
            per_method_bpms[m].append(bpm)

    row: dict = {
        "segment": seg_name,
        "bpm_gt": bpm_gt,
        "metadata": metadata,
    }
    for m in active_methods:
        row[m] = _seg_bpm_stats(np.asarray(per_method_bpms[m]), bpm_gt, len(starts))
    return row


def run_b2_benchmark(
    frames,
    segment_config: Dict[str, dict],
    *,
    filter_params: Optional[FilterParams] = None,
    metric_params: Optional[BreathMetricParams] = None,
    config: Optional[ChFusionConfig] = None,
    plan2_config: Optional[Plan2Config] = None,
    methods: Optional[Sequence[str]] = None,
    include_baselines: bool = True,
    verbose: bool = True,
    cache_dir: Optional[str] = None,
    multichannel_by_var: Optional[Dict[str, Dict[str, Optional[dict]]]] = None,
    pca_top_k: int = 36,
    phase: str = "all",
) -> dict:
    """Run B2 methods plus required baselines for one scenario."""
    cfg = config or ChFusionConfig()
    fp = filter_params or FilterParams()
    mp = metric_params or BreathMetricParams()
    p2 = plan2_config or Plan2Config(channel_metric="energy_ratio")
    vcfg = VotingConfig(voting_strategy="eta_rho_weighted")

    if phase == "1":
        method_keys = [s[1] for s in B2_PHASE1_SPECS]
    elif methods:
        method_keys = list(methods)
    else:
        method_keys = list(B2_METHOD_KEYS)

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
        print(f"\n--- B2 Coherent-MRC methods ({', '.join(method_keys)}) ---")
    for seg_name in seg_names:
        row = estimate_b2_segment(
            multichannel_by_var,
            seg_name,
            methods=method_keys,
            config=cfg,
            metric_params=mp,
            vcfg=vcfg,
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
        for key in method_keys:
            merged[seg_name][key] = row[key]
        if verbose:
            stats = _overall_rel_error({seg_name: row}, method_keys[0])
            print(f"  {seg_name} {method_keys[0]} {stats['mean_rel_err_pct']:.2f}%")

    if include_baselines:
        if verbose:
            print("\n--- Baselines (B0 / Uniform / Modal top2 / B1 / MRC-PCA) ---")
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

        from ble_analysis.wifi_mrc import estimate_wifi_mrc_segment

        mrc_partial: Dict[str, Optional[dict]] = {}
        for seg_name in seg_names:
            mrc_row = estimate_wifi_mrc_segment(
                multichannel_by_var,
                seg_name,
                config=cfg,
                metric_params=mp,
                pca_top_k=pca_top_k,
                verbose=False,
            )
            mrc_partial[seg_name] = mrc_row
        _merge_baseline_results(
            merged, mrc_partial, "mrc_pca_eta_equal", "mrc_pca_eta_equal"
        )

    specs = B2_ALL_SPECS + tuple(
        (label, key, color)
        for label, key, color in WIFI_MRC_METHOD_SPECS
        if key in ("b0_single_remote", "b1_uniform_remote", "b2_modal_top2_equal", "b1_vote_modal_equal", "mrc_pca_eta_equal")
    )

    if verbose:
        for label, key, _ in specs:
            if key not in method_keys and key not in (
                "b0_single_remote",
                "b1_uniform_remote",
                "b2_modal_top2_equal",
                "b1_vote_modal_equal",
                "mrc_pca_eta_equal",
            ):
                continue
            stats = _overall_rel_error(merged, key)
            if np.isfinite(stats["mean_rel_err_pct"]):
                print(f"✓ [{key}] {label} | mean err {stats['mean_rel_err_pct']:.2f}%")

    return {
        "results": merged,
        "multichannel_by_var": multichannel_by_var,
        "method_specs": specs,
        "method_keys": method_keys,
    }


def compute_b2_cross_domain(
    results_by_scenario: Dict[str, dict],
    method_specs: Optional[Sequence[Tuple[str, str, str]]] = None,
) -> List[dict]:
    """Aggregate cross-domain leaderboard rows."""
    specs = method_specs or B2_ALL_SPECS
    agg: List[dict] = []
    seen: set = set()
    for label, key, color in specs:
        if key in seen:
            continue
        seen.add(key)
        per_scenario: Dict[str, float] = {}
        for sid, bench in results_by_scenario.items():
            results = bench["results"] if isinstance(bench, dict) and "results" in bench else bench
            stats = _overall_rel_error(results, key)
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


def plot_b2_figures(
    results_by_scenario: Dict[str, dict],
    cross_domain: List[dict],
    *,
    figures_dir,
    scenario_ids: Sequence[str],
    prefix: str = "b2_coherent_mrc",
    show: bool = False,
    save: bool = True,
) -> dict:
    """Generate B2 leaderboard and ablation figures."""
    import matplotlib.pyplot as plt

    figures_dir = Path(figures_dir)
    paths: dict = {}

    fig, ax = plt.subplots(figsize=(12, 8))
    labels = [r["label"] for r in cross_domain]
    means = [r["cross_domain_mean"] for r in cross_domain]
    colors = [r["color"] for r in cross_domain]
    y_pos = np.arange(len(labels))
    ax.barh(y_pos, means, color=colors, alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Cross-domain mean BPM err %")
    ax.set_title("B2 Coherent-MRC — cross-domain leaderboard")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    lb_path = figures_dir / f"{prefix}_leaderboard.png"
    if save:
        fig.savefig(lb_path, dpi=150, bbox_inches="tight")
    paths["leaderboard"] = lb_path
    if not show:
        plt.close(fig)

    b2_keys = [k for k in B2_METHOD_KEYS]
    fig2, ax2 = plt.subplots(figsize=(10, 5))
    x = np.arange(len(scenario_ids))
    width = 0.8 / max(len(b2_keys), 1)
    for i, key in enumerate(b2_keys):
        ys = []
        for sid in scenario_ids:
            bench = results_by_scenario[sid]
            results = bench["results"] if "results" in bench else bench
            stats = _overall_rel_error(results, key)
            ys.append(stats["mean_rel_err_pct"])
        label = next((s[0] for s in B2_ALL_SPECS if s[1] == key), key)
        ax2.bar(x + i * width, ys, width, label=label, alpha=0.85)
    ax2.set_xticks(x + width * (len(b2_keys) - 1) / 2)
    ax2.set_xticklabels([s.replace("cs_", "") for s in scenario_ids])
    ax2.set_ylabel("Mean BPM err %")
    ax2.set_title("B2 phase / two-level ablation by scenario")
    ax2.legend(fontsize=6, loc="upper right")
    ax2.grid(True, axis="y", alpha=0.3)
    fig2.tight_layout()
    ab_path = figures_dir / f"{prefix}_phase_method_ablation.png"
    if save:
        fig2.savefig(ab_path, dpi=150, bbox_inches="tight")
    paths["phase_method_ablation"] = ab_path
    if not show:
        plt.close(fig2)

    fig3, axes = plt.subplots(1, len(scenario_ids), figsize=(5 * len(scenario_ids), 6), sharey=True)
    if len(scenario_ids) == 1:
        axes = [axes]
    for ax_i, sid in zip(axes, scenario_ids):
        bench = results_by_scenario[sid]
        results = bench["results"] if "results" in bench else bench
        vals, lbls, cols = [], [], []
        for row in cross_domain:
            stats = _overall_rel_error(results, row["method_key"])
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
        ax_i.set_yticklabels(lbls, fontsize=6)
        ax_i.invert_yaxis()
        ax_i.set_title(sid.replace("cs_", ""))
        ax_i.set_xlabel("Mean BPM err %")
        ax_i.grid(True, axis="x", alpha=0.3)
    fig3.suptitle("B2 Coherent-MRC — per-scenario comparison", y=1.02)
    fig3.tight_layout()
    sum_path = figures_dir / f"{prefix}_cross_domain_summary.png"
    if save:
        fig3.savefig(sum_path, dpi=150, bbox_inches="tight")
    paths["cross_domain_summary"] = sum_path
    if not show:
        plt.close(fig3)

    return paths


def plot_b2_achievement_figures(
    cross_domain: List[dict],
    *,
    figures_dir,
    scenario_ids: Sequence[str] = ("cs_091339", "cs_095806", "cs_102621"),
    prefix: str = "b2_coherent_mrc",
    show: bool = False,
    save: bool = True,
) -> dict:
    """Generate achievement-report figures: two-level contribution + waterfall."""
    import matplotlib.pyplot as plt

    figures_dir = Path(figures_dir)
    paths: dict = {}

    def _lookup(key: str) -> dict:
        for row in cross_domain:
            if row["method_key"] == key:
                return row
        raise KeyError(f"Method key not in cross_domain: {key}")

    # --- Figure 1: two-level contribution (Bγ / D-eq / D) ---
    contrib_keys = ("b2_b_gamma", "b2_d_eq", "b2_d_two_level")
    contrib_labels = [
        "B2-Bγ\n(single-level)",
        "B2-D-eq\n(two-level, no align)",
        "B2-D\n(two-level, Hilbert+ηγ)",
    ]
    contrib_colors = ["darkcyan", "lightblue", "crimson"]
    panel_ids = list(scenario_ids) + ["cross_domain"]

    fig1, axes1 = plt.subplots(1, len(panel_ids), figsize=(4 * len(panel_ids), 5), sharey=True)
    if len(panel_ids) == 1:
        axes1 = [axes1]

    for ax, panel in zip(axes1, panel_ids):
        vals = []
        for key in contrib_keys:
            row = _lookup(key)
            if panel == "cross_domain":
                vals.append(row["cross_domain_mean"])
            else:
                vals.append(row["per_scenario"][panel])
        x = np.arange(len(contrib_keys))
        bars = ax.bar(x, vals, color=contrib_colors, alpha=0.85, width=0.65)
        ax.set_xticks(x)
        ax.set_xticklabels(contrib_labels, fontsize=7)
        title = "cross-domain" if panel == "cross_domain" else panel.replace("cs_", "")
        ax.set_title(title)
        ax.set_ylabel("BPM err %")
        ax.grid(True, axis="y", alpha=0.3)
        if panel == "cross_domain":
            ax.text(
                bars[-1].get_x() + bars[-1].get_width() / 2,
                bars[-1].get_height() + 0.15,
                f"{vals[-1]:.2f}%",
                ha="center",
                va="bottom",
                fontsize=8,
                fontweight="bold",
            )
        delta = vals[-1] - vals[0]
        ax.annotate(
            f"Δ={delta:+.2f}pp",
            xy=(x[-1], vals[-1]),
            xytext=(x[-1] + 0.35, (vals[-1] + vals[0]) / 2),
            fontsize=7,
            arrowprops=dict(arrowstyle="->", color="gray", lw=0.8),
        )

    fig1.suptitle("B2 second-level contribution: Bγ → D-eq → D", y=1.02)
    fig1.tight_layout()
    p1 = figures_dir / f"{prefix}_two_level_contribution.png"
    if save:
        fig1.savefig(p1, dpi=150, bbox_inches="tight")
    paths["two_level_contribution"] = p1
    if not show:
        plt.close(fig1)

    # --- Figure 2: waterfall A0 → A1 → B → Bγ → D ---
    steps = [
        ("A0\nPCA sign", "b2_a0_pca_sign"),
        ("A1\nCorr sign", "b2_a1_corr_sign"),
        ("B\nHilbert η·ρ", "b2_b_hilbert"),
        ("Bγ\n+coherence gate", "b2_b_gamma"),
        ("D\n+modal Hilbert align", "b2_d_two_level"),
    ]
    values = [_lookup(key)["cross_domain_mean"] for _, key in steps]
    deltas = [None] + [values[i] - values[i - 1] for i in range(1, len(values))]

    fig2, ax2 = plt.subplots(figsize=(10, 6))
    b1_ref = _lookup("b1_vote_modal_equal")["cross_domain_mean"]
    ax2.axhline(b1_ref, color="olive", linestyle="--", linewidth=1.2, label=f"B1 ref {b1_ref:.2f}%")

    running = values[0]
    for i, ((label, _key), val, delta) in enumerate(zip(steps, values, deltas)):
        if i == 0:
            color = "steelblue"
            bottom = 0
            height = val
            ax2.bar(i, height, bottom=bottom, color=color, alpha=0.85, width=0.55)
            ax2.text(i, val + 0.15, f"{val:.2f}%", ha="center", fontsize=9)
        else:
            color = "#2ca02c" if delta < -0.05 else ("#d62728" if delta > 0.05 else "#aaaaaa")
            if delta >= 0:
                bottom = running
                height = delta
            else:
                bottom = val
                height = -delta
            ax2.bar(i, height, bottom=bottom, color=color, alpha=0.85, width=0.55)
            ax2.text(
                i,
                val + (0.2 if delta <= 0 else 0.2),
                f"{val:.2f}%\nΔ{delta:+.2f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )
            running = val

    ax2.set_xticks(range(len(steps)))
    ax2.set_xticklabels([s[0] for s in steps], fontsize=9)
    ax2.set_ylabel("Cross-domain mean BPM err %")
    ax2.set_title(f"B2 improvement path (A0→D total {values[-1] - values[0]:+.2f} pp)")
    ax2.legend(loc="upper right")
    ax2.grid(True, axis="y", alpha=0.3)
    fig2.tight_layout()
    p2 = figures_dir / f"{prefix}_waterfall_decomposition.png"
    if save:
        fig2.savefig(p2, dpi=150, bbox_inches="tight")
    paths["waterfall_decomposition"] = p2
    if not show:
        plt.close(fig2)

    return paths
