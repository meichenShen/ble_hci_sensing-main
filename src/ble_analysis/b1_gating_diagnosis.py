"""B1 joint gating and Vote→Equal mechanism diagnostics.

See ``docs/plans/b1_gating_and_diagnosis_plan.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np

from ble_analysis.chfusion import (
    ChFusionConfig,
    Plan2Config,
    _bpm_from_fused_spectrum,
    _channel_spectrum_and_q,
    _energy_ratio,
    _find_best_channel,
    _is_phase_variable,
    _next_pow2,
    _overall_rel_error,
    _seg_bpm_stats,
)
from ble_analysis.consensus_gating import (
    collect_segment_window_signals,
    compute_bimodality_score,
    gate_three_candidates,
    run_gating_benchmark,
)
from ble_analysis.segments import BreathMetricParams, FilterParams, _sliding_window_indices
from ble_analysis.systematic_fusion import (
    VAR_SHORT,
    _collect_channel_window_data,
    _weighted_spectrum_average,
    modal_fusion_from_spectra,
)
from ble_analysis.voting_fusion import (
    MODAL_VOTING_VARIABLES,
    VotingConfig,
    _vote_weights,
    vote_bpm_weighted_histogram,
)

SpectrumMode = Literal["conf_weighted", "winning_bin", "top_k"]
G4B1Variant = Literal["v1", "v2", "v3", "v4"]

G4_B1_METHOD_SPECS: Tuple[Tuple[str, str, str, G4B1Variant], ...] = (
    ("G4-B1-v1 Triple consensus", "g4_b1_v1", "darkgreen", "v1"),
    ("G4-B1-v2 Top2 consensus", "g4_b1_v2", "seagreen", "v2"),
    ("G4-B1-v3 B1 fallback", "g4_b1_v3", "olive", "v3"),
    ("G4-B1-v4 B1 vs Modal", "g4_b1_v4", "forestgreen", "v4"),
)

D3_METHOD_SPECS: Tuple[Tuple[str, str, str, SpectrumMode, str], ...] = (
    ("D3-B conf B1 Equal", "b1_vote_modal_equal", "olive", "conf_weighted", "equal"),
    ("D3-B conf B3 Top2", "b3_vote_modal_top2", "seagreen", "conf_weighted", "top2"),
    ("D3-A B1 Equal", "d3_a_b1", "darkorange", "winning_bin", "equal"),
    ("D3-A B3 Top2", "d3_a_b3", "coral", "winning_bin", "top2"),
    ("D3-C16 B1 Equal", "d3_c16_b1", "royalblue", "top_k", "equal"),
    ("D3-C16 B3 Top2", "d3_c16_b3", "dodgerblue", "top_k", "top2"),
    ("D3-C24 B1 Equal", "d3_c24_b1", "mediumpurple", "top_k", "equal"),
    ("D3-C24 B3 Top2", "d3_c24_b3", "orchid", "top_k", "top2"),
)

BASELINE_KEYS: Tuple[Tuple[str, str], ...] = (
    ("B1 Vote→Equal", "b1_vote_modal_equal"),
    ("G4 Single fallback", "g4_single_fallback"),
    ("G5 Bimodality", "g5_bimodality"),
    ("T0-V3", "t0_v3_eta_rho_weighted"),
    ("Modal top2", "b2_modal_top2_equal"),
)

__all__ = [
    "G4_B1_METHOD_SPECS",
    "D3_METHOD_SPECS",
    "compute_modal_spectral_similarity",
    "compute_voting_bimodality_per_modal",
    "per_modal_voting_spectrum_variant",
    "run_b1_gating_diagnosis_benchmark",
    "compute_b1_cross_domain_aggregate",
    "plot_b1_gating_figures",
]


def compute_modal_spectral_similarity(spectra: Dict[str, np.ndarray]) -> float:
    """Mean pairwise cosine similarity of normalized breath-band spectra."""
    keys = [k for k, s in spectra.items() if s is not None and np.sum(s) > 0]
    if len(keys) < 2:
        return float("nan")
    sims: List[float] = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a = np.asarray(spectra[keys[i]], dtype=float)
            b = np.asarray(spectra[keys[j]], dtype=float)
            na, nb = np.linalg.norm(a), np.linalg.norm(b)
            if na <= 0 or nb <= 0:
                continue
            sims.append(float(np.dot(a, b) / (na * nb)))
    return float(np.mean(sims)) if sims else float("nan")


def compute_voting_bimodality_per_modal(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    vcfg: VotingConfig,
    nfft: int,
    band_mask: np.ndarray,
    band_freqs: np.ndarray,
    hann: np.ndarray,
) -> Dict[str, float]:
    """Per-modal bimodality score from tone BPM histograms in one window."""
    scores: Dict[str, float] = {}
    for var in MODAL_VOTING_VARIABLES:
        seg = multichannel_by_var.get(var, {}).get(seg_name)
        if seg is None:
            continue
        ch_map = seg["channels"]
        ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
        eta, rho, bpm_per_tone, _spectra = _collect_channel_window_data(
            ch_list, ch_map, var, st, end, fs, cfg, nfft, band_mask, band_freqs, hann
        )
        weights = _vote_weights(eta, rho, vcfg.voting_strategy, cfg.eps)
        score, *_rest = compute_bimodality_score(bpm_per_tone, weights, vcfg)
        scores[VAR_SHORT[var]] = float(score)
    return scores


def per_modal_single_best_spectrum(
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    plan2: Plan2Config,
    nfft: int,
    band_mask: np.ndarray,
    band_freqs: np.ndarray,
    hann: np.ndarray,
) -> Tuple[np.ndarray, float]:
    """Single-best-channel spectrum for one modal variable (Modal top2 path)."""
    best_ch, _ = _find_best_channel(
        ch_map, variable, st, end, fs, cfg, metric=plan2.channel_metric
    )
    if best_ch is None:
        return np.zeros_like(band_freqs), 0.0
    ch_data = ch_map[best_ch][variable]
    bp = ch_data["bandpass_filtered"]
    hp = ch_data["highpass_filtered"]
    raw = ch_data["original"]
    if len(bp) < end:
        return np.zeros_like(band_freqs), 0.0
    bp_slice = bp[st:end]
    hp_slice = hp[st:end]
    ref_slice = raw[st:end] if len(raw) >= end else bp_slice
    eta = _energy_ratio(hp_slice, fs, cfg)
    p_norm, *_ = _channel_spectrum_and_q(
        bp_slice,
        ref_slice,
        fs,
        cfg,
        nfft,
        band_mask,
        band_freqs,
        hann,
        q_weight_mode="compact",
        compute_q_phi=_is_phase_variable(variable),
    )
    return p_norm, eta


def per_modal_voting_spectrum_variant(
    ch_list: Sequence[Any],
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    vcfg: VotingConfig,
    nfft: int,
    band_mask: np.ndarray,
    band_freqs: np.ndarray,
    hann: np.ndarray,
    *,
    spectrum_mode: SpectrumMode = "conf_weighted",
    top_k: int = 16,
    winning_bin_half_width_bpm: float = 2.0,
) -> Tuple[np.ndarray, float, dict]:
    """Per-modal voting spectrum with selectable construction (D3 ablation)."""
    eta, rho, bpm_per_tone, spectra = _collect_channel_window_data(
        ch_list, ch_map, variable, st, end, fs, cfg, nfft, band_mask, band_freqs, hann
    )
    weights = _vote_weights(eta, rho, vcfg.voting_strategy, cfg.eps)
    mask = np.isfinite(bpm_per_tone) & (weights > 0)
    if not np.any(mask):
        zero = np.zeros_like(band_freqs)
        return zero, float("nan"), {"conf": 0.0, "score": 0.0}

    bpms = bpm_per_tone[mask]
    w_vote = weights[mask]
    bpm, _conf_flag, win_mass = vote_bpm_weighted_histogram(bpms, w_vote, vcfg)
    total_w = float(np.sum(w_vote))
    conf = win_mass / total_w if total_w > 0 else 0.0

    spec_mask = mask.copy()
    if spectrum_mode == "winning_bin" and np.isfinite(bpm):
        spec_mask = mask & (np.abs(bpm_per_tone - bpm) <= winning_bin_half_width_bpm)
        if not np.any(spec_mask):
            spec_mask = mask
    elif spectrum_mode == "top_k":
        idx = np.where(mask)[0]
        order = idx[np.argsort(weights[idx])[::-1]]
        keep = order[: min(top_k, len(order))]
        spec_mask = np.zeros_like(mask, dtype=bool)
        spec_mask[keep] = True

    if spectrum_mode == "top_k":
        spec_weights = spec_mask.astype(float)
    else:
        spec_weights = weights * spec_mask.astype(float)

    fused = _weighted_spectrum_average(spectra, spec_weights, band_freqs, cfg.eps)
    mean_eta = float(np.mean(eta[spec_mask])) if np.any(spec_mask) else 0.0
    return fused, bpm, {
        "conf": conf,
        "score": conf if spectrum_mode != "top_k" else mean_eta,
        "mean_eta": mean_eta,
        "spectrum_mode": spectrum_mode,
    }


def _compute_window_modal_bpm(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    vcfg: VotingConfig,
    plan2: Plan2Config,
    metric_params: BreathMetricParams,
    *,
    channel_strategy: str = "vote",
    modal_weight_mode: Literal["equal", "energy_ratio", "top2_equal"] = "equal",
    spectrum_mode: SpectrumMode = "conf_weighted",
    top_k: int = 16,
) -> Tuple[float, Dict[str, np.ndarray], List[str]]:
    """One-window B1/B3-style modal fusion BPM + per-modal spectra."""
    win_len = int(round(metric_params.window_length_sec * fs))
    nfft = cfg.nfft or _next_pow2(4 * win_len)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
    band_freqs = freqs[band_mask]
    hann = np.hanning(win_len)

    spectra_by_var: Dict[str, np.ndarray] = {}
    scores_by_var: Dict[str, float] = {}

    for var in MODAL_VOTING_VARIABLES:
        seg = multichannel_by_var.get(var, {}).get(seg_name)
        if seg is None:
            continue
        ch_map = seg["channels"]
        ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
        short = VAR_SHORT[var]
        if channel_strategy == "single_best":
            spec, eta = per_modal_single_best_spectrum(
                ch_map, var, st, end, fs, cfg, plan2, nfft, band_mask, band_freqs, hann
            )
            spectra_by_var[short] = spec
            scores_by_var[short] = eta
        else:
            spec, _bpm, info = per_modal_voting_spectrum_variant(
                ch_list,
                ch_map,
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
                spectrum_mode=spectrum_mode,
                top_k=top_k,
            )
            spectra_by_var[short] = spec
            scores_by_var[short] = info["score"]

    if not spectra_by_var:
        return float("nan"), {}, []

    bpm, selected = modal_fusion_from_spectra(
        spectra_by_var, scores_by_var, modal_weight_mode, band_freqs, cfg
    )
    return bpm, spectra_by_var, selected


def _apply_g5_b1_window(
    bpm_b1: float,
    bpm_single: float,
    bimodality_by_modal: Dict[str, float],
    spectra_by_var: Dict[str, np.ndarray],
    scores_by_var: Dict[str, float],
    band_freqs: np.ndarray,
    cfg: ChFusionConfig,
    threshold: float = 0.5,
) -> Tuple[float, str]:
    """B1 + bimodality gating (091339专项)."""
    if not bimodality_by_modal:
        return bpm_b1, "b1_default"

    unimodal = [k for k, s in bimodality_by_modal.items() if s < threshold]
    bimodal = [k for k, s in bimodality_by_modal.items() if s >= threshold]

    if len(unimodal) == 3:
        return bpm_b1, "b1_all_unimodal"
    if len(unimodal) >= 2:
        sub_spec = {k: spectra_by_var[k] for k in unimodal if k in spectra_by_var}
        sub_scores = {k: scores_by_var.get(k, cfg.eps) for k in unimodal}
        bpm, _sel = modal_fusion_from_spectra(
            sub_spec, sub_scores, "equal", band_freqs, cfg
        )
        return bpm, "equal_unimodal_only"
    return float(bpm_single), "fallback_single"


def _segment_from_window_bpms(
    seg_name: str,
    bpm_gt: Optional[float],
    metadata: dict,
    window_bpms: List[float],
    method_key: str,
    extra: Optional[dict] = None,
) -> dict:
    bpm_arr = np.asarray(window_bpms, dtype=float)
    stats = _seg_bpm_stats(bpm_arr, bpm_gt, len(window_bpms))
    out = {
        "segment": seg_name,
        "bpm_gt": bpm_gt,
        "metadata": metadata,
        method_key: {**stats, **(extra or {})},
    }
    return out


def run_b1_gating_diagnosis_benchmark(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    segment_config: Dict[str, dict],
    *,
    filter_params: Optional[FilterParams] = None,
    metric_params: Optional[BreathMetricParams] = None,
    config: Optional[ChFusionConfig] = None,
    plan2_config: Optional[Plan2Config] = None,
    verbose: bool = True,
    include_g5_b1: bool = True,
) -> dict:
    """Run G4-B1 gating, D1–D3 diagnostics, and optional G5-B1."""
    _ = filter_params
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()
    p2 = plan2_config or Plan2Config(channel_metric="energy_ratio")
    vcfg = VotingConfig(voting_strategy="eta_rho_weighted")

    gating_bench = run_gating_benchmark(
        None,
        segment_config,
        filter_params=FilterParams(),
        metric_params=mp,
        config=cfg,
        plan2_config=p2,
        verbose=False,
        multichannel_by_var=multichannel_by_var,
    )
    merged = dict(gating_bench["results"])
    window_signals_by_seg = gating_bench["window_signals_by_seg"]

    remote_mc = multichannel_by_var["remote_amplitudes"]
    _ = remote_mc
    from ble_analysis.systematic_fusion import estimate_systematic_fusion_segment

    systematic_rows: Dict[str, Optional[dict]] = {}
    for seg_name in sorted(segment_config.keys()):
        for ch_strat, modal_strat, key in (
            ("vote", "equal", "b1_vote_modal_equal"),
            ("vote", "top2", "b3_vote_modal_top2"),
        ):
            row = estimate_systematic_fusion_segment(
                multichannel_by_var,
                seg_name,
                channel_strategy=ch_strat,
                modal_strategy=modal_strat,
                config=cfg,
                metric_params=mp,
                vcfg=vcfg,
                verbose=False,
            )
            if row is None:
                continue
            systematic_rows.setdefault(seg_name, {
                "segment": seg_name,
                "bpm_gt": row["bpm_gt"],
                "metadata": row["metadata"],
            })
            systematic_rows[seg_name][key] = row[key]

    for seg_name, row in systematic_rows.items():
        if merged.get(seg_name) is None:
            merged[seg_name] = row
        else:
            merged[seg_name].update({k: v for k, v in row.items() if k not in merged[seg_name]})

    # Diagnostics accumulators
    d1_voting_sims: List[float] = []
    d1_modal_single_sims: List[float] = []
    d2_bimodal_errors: List[float] = []
    d2_unimodal_errors: List[float] = []

    g4_b1_decisions: Dict[str, Dict[str, int]] = {spec[1]: {} for spec in G4_B1_METHOD_SPECS}
    g4_b1_partial: Dict[str, Dict[str, Optional[dict]]] = {spec[1]: {} for spec in G4_B1_METHOD_SPECS}
    d3_partial: Dict[str, Dict[str, Optional[dict]]] = {}
    g5_b1_partial: Dict[str, Optional[dict]] = {}

    d3_specs = [
        ("d3_a_b1", "winning_bin", "equal", 16),
        ("d3_a_b3", "winning_bin", "top2", 16),
        ("d3_c16_b1", "top_k", "equal", 16),
        ("d3_c16_b3", "top_k", "top2", 16),
        ("d3_c24_b1", "top_k", "equal", 24),
        ("d3_c24_b3", "top_k", "top2", 24),
    ]
    d3_window_store: Dict[str, Dict[str, List[float]]] = {k: {} for k, *_ in d3_specs}

    for seg_name, signals in window_signals_by_seg.items():
        row = merged.get(seg_name)
        if row is None:
            continue
        bpm_gt = row["bpm_gt"]
        metadata = row["metadata"]
        fs = metadata["sampling_rate"]
        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        remote_seg = multichannel_by_var["remote_amplitudes"].get(seg_name)
        if remote_seg is None:
            continue
        ch_map = remote_seg["channels"]
        ref_len = max(
            len(ch_map[c]["remote_amplitudes"]["bandpass_filtered"]) for c in ch_map
        )
        starts = _sliding_window_indices(ref_len, win_len, step_len)
        nfft = cfg.nfft or _next_pow2(4 * win_len)
        freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
        band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
        band_freqs = freqs[band_mask]
        hann = np.hanning(win_len)

        g4_window_bpms: Dict[str, List[float]] = {spec[1]: [] for spec in G4_B1_METHOD_SPECS}
        g4_decision_lists: Dict[str, List[str]] = {spec[1]: [] for spec in G4_B1_METHOD_SPECS}
        g5_bpms: List[float] = []
        g5_tags: List[str] = []

        for wi, ws in enumerate(signals):
            if wi >= len(starts):
                break
            st = int(starts[wi])
            end = st + win_len

            bpm_b1, vote_spectra, _sel = _compute_window_modal_bpm(
                multichannel_by_var,
                seg_name,
                st,
                end,
                fs,
                cfg,
                vcfg,
                p2,
                mp,
                channel_strategy="vote",
                modal_weight_mode="equal",
                spectrum_mode="conf_weighted",
            )
            bpm_b3, top2_spectra, _sel3 = _compute_window_modal_bpm(
                multichannel_by_var,
                seg_name,
                st,
                end,
                fs,
                cfg,
                vcfg,
                p2,
                mp,
                channel_strategy="vote",
                modal_weight_mode="top2_equal",
                spectrum_mode="conf_weighted",
            )
            _, single_spectra, _ = _compute_window_modal_bpm(
                multichannel_by_var,
                seg_name,
                st,
                end,
                fs,
                cfg,
                vcfg,
                p2,
                mp,
                channel_strategy="single_best",
                modal_weight_mode="top2_equal",
                spectrum_mode="conf_weighted",
            )

            sim_vote = compute_modal_spectral_similarity(vote_spectra)
            sim_single = compute_modal_spectral_similarity(single_spectra)
            sim_top2 = compute_modal_spectral_similarity(top2_spectra)
            if np.isfinite(sim_vote):
                d1_voting_sims.append(sim_vote)
            if np.isfinite(sim_single):
                d1_modal_single_sims.append(sim_single)
            _ = sim_top2

            bpm_vote = ws["bpm_vote"]
            bpm_modal = ws["bpm_modal"]
            bpm_single = ws["bpm_single"]

            for _label, key, _color, variant in G4_B1_METHOD_SPECS:
                bpm_g, tag = gate_three_candidates(
                    bpm_b1,
                    bpm_vote,
                    bpm_modal,
                    bpm_single,
                    delta=3.0,
                    variant=variant,
                )
                g4_window_bpms[key].append(bpm_g)
                g4_decision_lists[key].append(tag)

            bimodality = compute_voting_bimodality_per_modal(
                multichannel_by_var,
                seg_name,
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
            any_bimodal = any(s >= 0.5 for s in bimodality.values())
            if np.isfinite(bpm_b1) and bpm_gt and bpm_gt > 0:
                err = abs(bpm_b1 - bpm_gt) / bpm_gt * 100.0
                if any_bimodal:
                    d2_bimodal_errors.append(err)
                else:
                    d2_unimodal_errors.append(err)

            if include_g5_b1:
                scores = {k: 1.0 for k in vote_spectra}
                bpm_g5, g5_tag = _apply_g5_b1_window(
                    bpm_b1,
                    bpm_single,
                    bimodality,
                    vote_spectra,
                    scores,
                    band_freqs,
                    cfg,
                )
                g5_bpms.append(bpm_g5)
                g5_tags.append(g5_tag)

            for d3_key, spec_mode, modal_mode, top_k in d3_specs:
                weight_mode: Literal["equal", "top2_equal"] = (
                    "equal" if modal_mode == "equal" else "top2_equal"
                )
                bpm_d3, _, _ = _compute_window_modal_bpm(
                    multichannel_by_var,
                    seg_name,
                    st,
                    end,
                    fs,
                    cfg,
                    vcfg,
                    p2,
                    mp,
                    channel_strategy="vote",
                    modal_weight_mode=weight_mode,
                    spectrum_mode=spec_mode,
                    top_k=top_k,
                )
                d3_window_store[d3_key].setdefault(seg_name, []).append(bpm_d3)

        for _label, key, _color, _variant in G4_B1_METHOD_SPECS:
            gated = _segment_from_window_bpms(
                seg_name,
                bpm_gt,
                metadata,
                g4_window_bpms[key],
                key,
                extra={"decision_tags": g4_decision_lists[key]},
            )
            g4_b1_partial[key][seg_name] = gated
            for tag in g4_decision_lists[key]:
                g4_b1_decisions[key][tag] = g4_b1_decisions[key].get(tag, 0) + 1

        if include_g5_b1 and g5_bpms:
            g5_b1_partial[seg_name] = _segment_from_window_bpms(
                seg_name, bpm_gt, metadata, g5_bpms, "g5_b1", extra={"decision_tags": g5_tags}
            )

    for _label, key, _color, _variant in G4_B1_METHOD_SPECS:
        for seg_name, grow in g4_b1_partial[key].items():
            if merged.get(seg_name) is None:
                merged[seg_name] = grow
            else:
                merged[seg_name][key] = grow[key]
        if verbose:
            stats = _overall_rel_error(g4_b1_partial[key], key)
            print(
                f"✓ [{key}] mean err {stats['mean_rel_err_pct']:.2f}% "
                f"± {stats['std_rel_err_pct']:.2f}%"
            )

    for d3_key, _mode, _modal, _k in d3_specs:
        partial: Dict[str, Optional[dict]] = {}
        for seg_name, bpms in d3_window_store[d3_key].items():
            row = merged.get(seg_name)
            if row is None:
                continue
            partial[seg_name] = _segment_from_window_bpms(
                seg_name, row["bpm_gt"], row["metadata"], bpms, d3_key
            )
        d3_partial[d3_key] = partial
        for seg_name, grow in partial.items():
            if merged.get(seg_name) is None:
                merged[seg_name] = grow
            else:
                merged[seg_name][d3_key] = grow[d3_key]

    if include_g5_b1:
        for seg_name, grow in g5_b1_partial.items():
            if merged.get(seg_name) is None:
                merged[seg_name] = grow
            else:
                merged[seg_name]["g5_b1"] = grow["g5_b1"]

    diagnostics = {
        "d1_voting_spectral_similarity": np.asarray(d1_voting_sims, dtype=float),
        "d1_modal_single_spectral_similarity": np.asarray(d1_modal_single_sims, dtype=float),
        "d2_bimodal_b1_errors_pct": np.asarray(d2_bimodal_errors, dtype=float),
        "d2_unimodal_b1_errors_pct": np.asarray(d2_unimodal_errors, dtype=float),
        "g4_b1_decision_counts": g4_b1_decisions,
    }

    return {
        "results": merged,
        "multichannel_by_var": multichannel_by_var,
        "diagnostics": diagnostics,
        "gating_benchmark": gating_bench,
        "systematic_rows": systematic_rows,
        "d3_partial": d3_partial,
        "g4_b1_partial": g4_b1_partial,
        "g5_b1_partial": g5_b1_partial,
    }


def compute_b1_cross_domain_aggregate(
    results_by_scenario: Dict[str, dict],
    method_specs: Sequence[Tuple[str, ...]],
) -> List[dict]:
    """Cross-domain mean for arbitrary method spec tuples ``(label, key, color, ...)``."""
    rows: List[dict] = []
    for spec in method_specs:
        label, key = spec[0], spec[1]
        color = spec[2] if len(spec) > 2 else "gray"
        per_scenario: List[float] = []
        for _sid, bench in results_by_scenario.items():
            stats = _overall_rel_error(bench["results"], key)
            if np.isfinite(stats["mean_rel_err_pct"]):
                per_scenario.append(stats["mean_rel_err_pct"])
        if not per_scenario:
            continue
        rows.append(
            {
                "label": label,
                "method_key": key,
                "color": color,
                "cross_domain_mean": float(np.mean(per_scenario)),
                "cross_domain_std": float(np.std(per_scenario, ddof=1))
                if len(per_scenario) > 1
                else 0.0,
                "per_scenario": per_scenario,
            }
        )
    rows.sort(key=lambda r: r["cross_domain_mean"])
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def plot_b1_gating_figures(
    results_by_scenario: Dict[str, dict],
    cross_domain: List[dict],
    diagnostics_by_scenario: Dict[str, dict],
    *,
    figures_dir,
    scenario_ids: Sequence[str],
    save: bool = True,
    show: bool = False,
) -> Dict[str, str]:
    """Generate PNG figures for B1 gating and diagnostics."""
    figures_dir = Path(figures_dir)
    figures_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, str] = {}

    # Leaderboard
    fig, ax = plt.subplots(figsize=(12, 7))
    labels = [r["label"] for r in cross_domain[:12]]
    means = [r["cross_domain_mean"] for r in cross_domain[:12]]
    stds = [r["cross_domain_std"] for r in cross_domain[:12]]
    colors = [r["color"] for r in cross_domain[:12]]
    y = np.arange(len(labels))
    ax.barh(y, means, xerr=stds, color=colors, alpha=0.85, capsize=3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Mean BPM relative error (%)")
    ax.set_title("B1 Gating & Diagnosis — cross-domain leaderboard")
    ax.axvline(8.45, color="gray", linestyle="--", linewidth=1, label="B1 ref 8.45%")
    ax.legend(loc="lower right")
    ax.grid(True, axis="x", alpha=0.3)
    plt.tight_layout()
    p_leader = figures_dir / "b1_gating_leaderboard.png"
    fig.savefig(p_leader, bbox_inches="tight", dpi=150)
    paths["leaderboard"] = str(p_leader)
    if show:
        plt.show()
    plt.close(fig)

    # D1 spectral similarity
    fig, ax = plt.subplots(figsize=(8, 5))
    vote_all = np.concatenate(
        [diagnostics_by_scenario[s]["d1_voting_spectral_similarity"] for s in scenario_ids]
    )
    single_all = np.concatenate(
        [diagnostics_by_scenario[s]["d1_modal_single_spectral_similarity"] for s in scenario_ids]
    )
    vote_all = vote_all[np.isfinite(vote_all)]
    single_all = single_all[np.isfinite(single_all)]
    ax.hist(vote_all, bins=30, alpha=0.6, label="Vote spectrum (B1 path)", color="olive")
    ax.hist(single_all, bins=30, alpha=0.6, label="Single-best spectrum (Modal path)", color="steelblue")
    ax.set_xlabel("Mean pairwise spectral cosine similarity")
    ax.set_ylabel("Window count")
    ax.set_title("D1: Modal spectral similarity (voting vs single-best)")
    ax.legend()
    plt.tight_layout()
    p_d1 = figures_dir / "b1_diag_spectral_similarity.png"
    fig.savefig(p_d1, bbox_inches="tight", dpi=150)
    paths["d1_similarity"] = str(p_d1)
    if show:
        plt.show()
    plt.close(fig)

    # D2 bimodal error (091339)
    diag_091339 = diagnostics_by_scenario.get("cs_091339", {})
    bi = diag_091339.get("d2_bimodal_b1_errors_pct", np.array([]))
    uni = diag_091339.get("d2_unimodal_b1_errors_pct", np.array([]))
    if bi.size or uni.size:
        fig, ax = plt.subplots(figsize=(7, 5))
        data = []
        labels_box = []
        if uni.size:
            data.append(uni)
            labels_box.append("Unimodal")
        if bi.size:
            data.append(bi)
            labels_box.append("Bimodal")
        ax.boxplot(data, labels=labels_box)
        ax.set_ylabel("B1 window BPM error (%)")
        ax.set_title("D2: B1 error on 091339 — bimodal vs unimodal windows")
        plt.tight_layout()
        p_d2 = figures_dir / "b1_diag_bimodal_error.png"
        fig.savefig(p_d2, bbox_inches="tight", dpi=150)
        paths["d2_bimodal"] = str(p_d2)
        if show:
            plt.show()
        plt.close(fig)

    # D3 spectrum mode ablation
    d3_keys = [
        ("b1_vote_modal_equal", "conf B1"),
        ("b3_vote_modal_top2", "conf B3"),
        ("d3_a_b1", "win-bin B1"),
        ("d3_a_b3", "win-bin B3"),
        ("d3_c16_b1", "top16 B1"),
        ("d3_c16_b3", "top16 B3"),
    ]
    d3_means = []
    d3_labels = []
    for key, lab in d3_keys:
        vals = []
        for sid in scenario_ids:
            stats = _overall_rel_error(results_by_scenario[sid]["results"], key)
            if np.isfinite(stats["mean_rel_err_pct"]):
                vals.append(stats["mean_rel_err_pct"])
        if vals:
            d3_means.append(float(np.mean(vals)))
            d3_labels.append(lab)
    if d3_means:
        fig, ax = plt.subplots(figsize=(10, 5))
        x = np.arange(len(d3_labels))
        ax.bar(x, d3_means, color="teal", alpha=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(d3_labels, rotation=30, ha="right")
        ax.set_ylabel("Cross-domain mean err%")
        ax.set_title("D3: Spectrum construction ablation")
        plt.tight_layout()
        p_d3 = figures_dir / "b1_diag_spectrum_mode.png"
        fig.savefig(p_d3, bbox_inches="tight", dpi=150)
        paths["d3_spectrum"] = str(p_d3)
        if show:
            plt.show()
        plt.close(fig)

    # G4-B1 decision pie (aggregate v1)
    decision_counts: Dict[str, int] = {}
    for sid in scenario_ids:
        dc = diagnostics_by_scenario[sid].get("g4_b1_decision_counts", {}).get("g4_b1_v1", {})
        for tag, cnt in dc.items():
            decision_counts[tag] = decision_counts.get(tag, 0) + cnt
    if decision_counts:
        fig, ax = plt.subplots(figsize=(7, 7))
        tags = list(decision_counts.keys())
        sizes = [decision_counts[t] for t in tags]
        ax.pie(sizes, labels=tags, autopct="%1.1f%%", startangle=90)
        ax.set_title("G4-B1-v1 window decision distribution (all scenarios)")
        plt.tight_layout()
        p_pie = figures_dir / "b1_gating_decision_pie.png"
        fig.savefig(p_pie, bbox_inches="tight", dpi=150)
        paths["decision_pie"] = str(p_pie)
        if show:
            plt.show()
        plt.close(fig)

    if not save:
        for p in list(paths.values()):
            Path(p).unlink(missing_ok=True)
    return paths
