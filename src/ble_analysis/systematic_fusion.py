"""Systematic modal × channel fusion grid (2D strategy validation).

See ``docs/plans/systematic_modal_channel_fusion_plan.md``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np

from ble_analysis.chfusion import (
    ChFusionConfig,
    MODAL_FUSION_VARIABLES,
    Plan2Config,
    _bpm_from_fused_spectrum,
    _channel_spectrum_and_q,
    _energy_ratio,
    _is_phase_variable,
    _next_pow2,
    _overall_rel_error,
    _peak_prominence,
    _seg_bpm_stats,
    estimate_modal_best_channel_fusion,
    estimate_segment_bpm_methods,
    run_modal_fusion_benchmark,
    run_multichannel_segment_filtering,
)
from ble_analysis.consensus_gating import compute_tone_persistence, run_gating_benchmark
from ble_analysis.segments import BreathMetricParams, FilterParams, _sliding_window_indices
from ble_analysis.voting_fusion import (
    MODAL_VOTING_VARIABLES,
    VotingConfig,
    _bpm_from_waveform,
    _vote_weights,
    compute_channel_bpm_persistence,
    estimate_voting_segment_methods,
    run_voting_fusion_benchmark,
    vote_bpm_weighted_histogram,
)

ChannelStrategy = Literal["vote", "votep", "uniform"]
ModalStrategy = Literal["phase_only", "equal", "eta", "top2"]
ModalFusionWeightMode = Literal["equal", "energy_ratio", "top2_equal"]

VAR_SHORT = {
    "remote_amplitudes": "remote",
    "local_amplitudes": "local",
    "phases": "phase",
}

SYSTEMATIC_NEW_METHOD_SPECS: Tuple[Tuple[str, str, str, ChannelStrategy, ModalStrategy], ...] = (
    ("A1 Phase η·ρ voting", "a1_phase_vote", "teal", "vote", "phase_only"),
    ("A2 Phase persistence voting", "a2_phase_votep", "darkcyan", "votep", "phase_only"),
    ("B1 Vote→Equal modal", "b1_vote_modal_equal", "olive", "vote", "equal"),
    ("B2 Vote→η modal", "b2_vote_modal_eta", "darkolivegreen", "vote", "eta"),
    ("B3 Vote→Top2 modal", "b3_vote_modal_top2", "seagreen", "vote", "top2"),
    ("B4 VoteP→Top2 modal", "b4_votep_modal_top2", "forestgreen", "votep", "top2"),
    ("C1 Uniform→Top2 modal", "c1_uniform_modal_top2", "mediumpurple", "uniform", "top2"),
    ("C2 Uniform→η modal", "c2_uniform_modal_eta", "slateblue", "uniform", "eta"),
)

BASELINE_METHOD_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("B0 Single Remote", "b0_single_remote", "steelblue"),
    ("B1 Uniform Remote", "b1_uniform_remote", "seagreen"),
    ("B2 Modal top2 equal", "b2_modal_top2_equal", "mediumpurple"),
    ("B3 Modal η-weight", "b3_modal_eta_weight", "darkorange"),
    ("T0-V3 Per-Tone η·ρ", "t0_v3_eta_rho_weighted", "indianred"),
    ("T3 Voting+Modal hybrid", "t3_voting_modal_hybrid", "crimson"),
    ("G4 Single fallback", "g4_single_fallback", "slateblue"),
    ("Single Phase", "single_phase", "cadetblue"),
    ("Uniform Phase", "uniform_phase", "lightseagreen"),
)

ALL_METHOD_SPECS: Tuple[Tuple[str, str, str], ...] = (
    *[(label, key, color) for label, key, color, _c, _m in SYSTEMATIC_NEW_METHOD_SPECS],
    *BASELINE_METHOD_SPECS,
)

__all__ = [
    "SYSTEMATIC_NEW_METHOD_SPECS",
    "BASELINE_METHOD_SPECS",
    "ALL_METHOD_SPECS",
    "per_modal_voting_spectrum",
    "per_modal_uniform_spectrum",
    "modal_fusion_from_spectra",
    "run_systematic_fusion_benchmark",
    "build_systematic_leaderboard_rows",
    "compute_systematic_cross_domain",
    "plot_systematic_fusion_figures",
]


def _modal_weight_mode(modal_strategy: ModalStrategy) -> ModalFusionWeightMode:
    if modal_strategy == "equal":
        return "equal"
    if modal_strategy == "eta":
        return "energy_ratio"
    return "top2_equal"


def _active_modal_vars(modal_strategy: ModalStrategy) -> Tuple[str, ...]:
    if modal_strategy == "phase_only":
        return ("phases",)
    return MODAL_VOTING_VARIABLES


def _collect_channel_window_data(
    ch_list: Sequence[Any],
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    nfft: int,
    band_mask: np.ndarray,
    band_freqs: np.ndarray,
    hann: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[np.ndarray]]:
    """Per-channel η, ρ, BPM, normalized spectrum for one window."""
    eta_list: List[float] = []
    rho_list: List[float] = []
    bpm_list: List[float] = []
    spectra: List[np.ndarray] = []

    for ch in ch_list:
        ch_data = ch_map[ch][variable]
        bp = ch_data["bandpass_filtered"]
        hp = ch_data["highpass_filtered"]
        raw = ch_data["original"]
        if len(bp) < end or len(hp) < end:
            eta_list.append(0.0)
            rho_list.append(0.0)
            bpm_list.append(float("nan"))
            spectra.append(np.zeros_like(band_freqs))
            continue

        bp_slice = bp[st:end]
        hp_slice = hp[st:end]
        ref_slice = raw[st:end] if len(raw) >= end else bp_slice
        eta_list.append(_energy_ratio(hp_slice, fs, cfg))
        rho_list.append(_peak_prominence(bp_slice, fs, cfg))
        bpm_list.append(_bpm_from_waveform(bp_slice, fs, cfg))
        p_norm, _qc, _fp, _det = _channel_spectrum_and_q(
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
        spectra.append(p_norm)

    return (
        np.asarray(eta_list, dtype=float),
        np.asarray(rho_list, dtype=float),
        np.asarray(bpm_list, dtype=float),
        spectra,
    )


def _weighted_spectrum_average(
    spectra: Sequence[np.ndarray],
    weights: np.ndarray,
    band_freqs: np.ndarray,
    eps: float,
) -> np.ndarray:
    w = np.asarray(weights, dtype=float)
    valid = np.isfinite(w) & (w > 0)
    if not np.any(valid):
        return np.zeros_like(band_freqs)
    w = w[valid]
    specs = np.vstack([spectra[i] for i in range(len(spectra)) if valid[i]])
    if specs.size == 0:
        return np.zeros_like(band_freqs)
    w = w / (np.sum(w) + eps)
    return np.sum(w[:, None] * specs, axis=0)


def per_modal_uniform_spectrum(
    ch_list: Sequence[Any],
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    nfft: int,
    band_mask: np.ndarray,
    band_freqs: np.ndarray,
    hann: np.ndarray,
) -> Tuple[np.ndarray, float, dict]:
    """Uniform average of all channel spectra for one modal variable."""
    eta, rho, _bpms, spectra = _collect_channel_window_data(
        ch_list, ch_map, variable, st, end, fs, cfg, nfft, band_mask, band_freqs, hann
    )
    valid = np.array([np.sum(s) > cfg.eps for s in spectra], dtype=bool)
    if not np.any(valid):
        fused = np.zeros_like(band_freqs)
    else:
        fused = np.mean(np.vstack([spectra[i] for i in range(len(spectra)) if valid[i]]), axis=0)
    bpm = _bpm_from_fused_spectrum(fused, band_freqs, cfg)
    mean_eta = float(np.mean(eta[valid])) if np.any(valid) else 0.0
    return fused, bpm, {"score": mean_eta, "mean_eta": mean_eta, "n_channels": int(np.sum(valid))}


def per_modal_voting_spectrum(
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
    stable_mask: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, float, dict]:
    """Conf-weighted tone spectrum average + histogram voting BPM."""
    eta, rho, bpm_per_tone, spectra = _collect_channel_window_data(
        ch_list, ch_map, variable, st, end, fs, cfg, nfft, band_mask, band_freqs, hann
    )
    weights = _vote_weights(eta, rho, vcfg.voting_strategy, cfg.eps)
    mask = np.isfinite(bpm_per_tone) & (weights > 0)
    if stable_mask is not None and len(stable_mask) == len(mask):
        mask = mask & stable_mask

    if not np.any(mask):
        zero = np.zeros_like(band_freqs)
        return zero, float("nan"), {
            "conf": 0.0,
            "mean_eta": 0.0,
            "score": 0.0,
            "n_effective_tones": 0,
        }

    bpms = bpm_per_tone[mask]
    w_vote = weights[mask]
    bpm, _conf_flag, win_mass = vote_bpm_weighted_histogram(bpms, w_vote, vcfg)
    total_w = float(np.sum(w_vote))
    conf = win_mass / total_w if total_w > 0 else 0.0

    spec_weights = weights * mask.astype(float)
    fused = _weighted_spectrum_average(spectra, spec_weights, band_freqs, cfg.eps)
    mean_eta = float(np.mean(eta[mask])) if np.any(mask) else 0.0

    return fused, bpm, {
        "conf": conf,
        "mean_eta": mean_eta,
        "score": conf,
        "n_effective_tones": int(np.sum(mask)),
        "winning_mass": win_mass,
    }


def modal_fusion_from_spectra(
    spectra: Dict[str, np.ndarray],
    scores: Dict[str, float],
    weight_mode: ModalFusionWeightMode,
    band_freqs: np.ndarray,
    cfg: ChFusionConfig,
) -> Tuple[float, List[str]]:
    """Fuse per-modal spectra; returns BPM and selected modal keys (for top2)."""
    if not spectra:
        return float("nan"), []

    entries = [(k, spectra[k], max(scores.get(k, 0.0), cfg.eps)) for k in spectra]
    if weight_mode == "top2_equal":
        ranked = sorted(entries, key=lambda e: e[2], reverse=True)
        use = ranked[:2]
        w_arr = np.ones(len(use), dtype=float) / max(len(use), 1)
        fused = np.sum(w_arr[:, None] * np.vstack([e[1] for e in use]), axis=0)
        return _bpm_from_fused_spectrum(fused, band_freqs, cfg), [e[0] for e in use]

    w_list = []
    spec_list = []
    for _k, spec, score in entries:
        spec_list.append(spec)
        if weight_mode == "equal":
            w_list.append(1.0)
        else:
            w_list.append(score)
    w_arr = np.asarray(w_list, dtype=float)
    if np.sum(w_arr) <= cfg.eps:
        return float("nan"), list(spectra.keys())
    w_arr = w_arr / np.sum(w_arr)
    fused = np.sum(w_arr[:, None] * np.vstack(spec_list), axis=0)
    return _bpm_from_fused_spectrum(fused, band_freqs, cfg), list(spectra.keys())


def _compute_persistence_masks_by_var(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    *,
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    vcfg: VotingConfig,
) -> Dict[str, np.ndarray]:
    """Per-modal tone persistence (mean |ΔBPM| across windows) for one segment."""
    masks: Dict[str, np.ndarray] = {}
    for var in MODAL_VOTING_VARIABLES:
        seg = multichannel_by_var.get(var, {}).get(seg_name)
        if seg is None:
            continue
        partial = estimate_voting_segment_methods(
            {seg_name: seg},
            variable=var,
            config=config,
            metric_params=metric_params,
            voting_config=vcfg,
            method_key="_persistence_probe",
            verbose=False,
        )
        row = partial.get(seg_name)
        if row is None:
            continue
        block = row["_persistence_probe"]
        tone_bpms = block.get("bpm_per_tone_per_window", [])
        if not tone_bpms:
            continue
        persistence = compute_tone_persistence(tone_bpms)
        masks[var] = persistence
    return masks


def estimate_systematic_fusion_segment(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    *,
    channel_strategy: ChannelStrategy,
    modal_strategy: ModalStrategy,
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    vcfg: VotingConfig,
    persistence_masks: Optional[Dict[str, np.ndarray]] = None,
    persistence_threshold: float = 2.0,
    verbose: bool = False,
) -> Optional[dict]:
    """Run one (channel × modal) strategy on a single breath segment."""
    ref_seg = multichannel_by_var["phases"].get(seg_name)
    if ref_seg is None:
        return None
    metadata = ref_seg["metadata"]
    if metadata.get("segment_type") == "apnea":
        return None

    bpm_gt = metadata.get("bpm_gt")
    fs = metadata["sampling_rate"]
    active_vars = _active_modal_vars(modal_strategy)
    weight_mode = _modal_weight_mode(modal_strategy)

    seg_maps: Dict[str, Dict[Any, dict]] = {}
    ch_lists: Dict[str, List[Any]] = {}
    ref_len = 0
    for var in active_vars:
        seg = multichannel_by_var.get(var, {}).get(seg_name)
        if seg is None or not seg["channels"]:
            return None
        seg_maps[var] = seg["channels"]
        ch_lists[var] = sorted(
            seg["channels"].keys(), key=lambda c: (isinstance(c, str), str(c))
        )
        ref_len = max(
            ref_len,
            max(len(c[var]["bandpass_filtered"]) for c in seg["channels"].values()),
        )

    win_len = int(round(metric_params.window_length_sec * fs))
    step_len = int(round(metric_params.step_length_sec * fs))
    if ref_len < win_len:
        return None

    cfg = config
    nfft = cfg.nfft or _next_pow2(4 * win_len)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
    band_freqs = freqs[band_mask]
    hann = np.hanning(win_len)
    starts = _sliding_window_indices(ref_len, win_len, step_len)

    bpms: List[float] = []
    modal_selections: List[List[str]] = []

    for st in starts:
        end = st + win_len
        spectra_by_var: Dict[str, np.ndarray] = {}
        scores_by_var: Dict[str, float] = {}

        for var in active_vars:
            ch_list = ch_lists[var]
            ch_map = seg_maps[var]
            short = VAR_SHORT[var]

            if channel_strategy == "uniform":
                spec, _bpm, info = per_modal_uniform_spectrum(
                    ch_list, ch_map, var, st, end, fs, cfg, nfft, band_mask, band_freqs, hann
                )
                spectra_by_var[short] = spec
                scores_by_var[short] = info["score"]
                continue

            stable_mask = None
            if channel_strategy == "votep" and persistence_masks is not None:
                pers = persistence_masks.get(var)
                if pers is not None and len(pers) == len(ch_list):
                    stable_mask = pers <= persistence_threshold

            spec, _bpm, info = per_modal_voting_spectrum(
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
                stable_mask=stable_mask,
            )
            spectra_by_var[short] = spec
            scores_by_var[short] = info["score"]

        if modal_strategy == "phase_only":
            bpm = _bpm_from_fused_spectrum(spectra_by_var["phase"], band_freqs, cfg)
            selected = ["phase"]
        else:
            bpm, selected = modal_fusion_from_spectra(
                spectra_by_var, scores_by_var, weight_mode, band_freqs, cfg
            )
        bpms.append(bpm)
        modal_selections.append(selected)

    method_key = _method_key_for(channel_strategy, modal_strategy)
    return {
        "segment": seg_name,
        "bpm_gt": bpm_gt,
        "metadata": metadata,
        method_key: {
            **_seg_bpm_stats(np.asarray(bpms), bpm_gt, len(starts)),
            "modal_selections": modal_selections,
        },
    }


def _method_key_for(channel_strategy: ChannelStrategy, modal_strategy: ModalStrategy) -> str:
    for _label, key, _color, ch, mod in SYSTEMATIC_NEW_METHOD_SPECS:
        if ch == channel_strategy and mod == modal_strategy:
            return key
    return f"{channel_strategy}_{modal_strategy}"


def _run_new_systematic_methods(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    vcfg: VotingConfig,
    verbose: bool = True,
) -> Dict[str, Optional[dict]]:
    """Compute Block A/B/C new methods across all segments."""
    merged: Dict[str, Optional[dict]] = {}
    seg_names = sorted(multichannel_by_var["phases"].keys())

    persistence_cache: Dict[str, Dict[str, np.ndarray]] = {}
    for seg_name in seg_names:
        ref = multichannel_by_var["phases"].get(seg_name)
        if ref is None or ref["metadata"].get("segment_type") == "apnea":
            continue
        persistence_cache[seg_name] = _compute_persistence_masks_by_var(
            multichannel_by_var,
            seg_name,
            config=config,
            metric_params=metric_params,
            vcfg=vcfg,
        )

    for label, method_key, _color, ch_strat, mod_strat in SYSTEMATIC_NEW_METHOD_SPECS:
        partial: Dict[str, Optional[dict]] = {}
        for seg_name in seg_names:
            pers = persistence_cache.get(seg_name) if ch_strat == "votep" else None
            row = estimate_systematic_fusion_segment(
                multichannel_by_var,
                seg_name,
                channel_strategy=ch_strat,
                modal_strategy=mod_strat,
                config=config,
                metric_params=metric_params,
                vcfg=vcfg,
                persistence_masks=pers,
                verbose=False,
            )
            partial[seg_name] = row

        for seg_name, row in partial.items():
            if row is None:
                merged.setdefault(seg_name, None)
                continue
            if merged.get(seg_name) is None:
                merged[seg_name] = {
                    "segment": seg_name,
                    "bpm_gt": row["bpm_gt"],
                    "metadata": row["metadata"],
                }
            if method_key in row:
                merged[seg_name][method_key] = row[method_key]

        if verbose:
            stats = _overall_rel_error(partial, method_key)
            print(
                f"✓ [{method_key}] {label} | mean err {stats['mean_rel_err_pct']:.2f}% "
                f"± {stats['std_rel_err_pct']:.2f}%"
            )

    return merged


def _merge_baseline_results(
    merged: Dict[str, Optional[dict]],
    voting_bench: dict,
    gating_bench: dict,
    modal_bench: dict,
    phase_baselines: Dict[str, Optional[dict]],
) -> None:
    """Attach baseline method blocks from prior benchmarks."""
    voting_results = voting_bench["results"]
    gating_results = gating_bench["results"]
    modal_results = modal_bench["results"]

    all_seg_names = set()
    for src in (voting_results, gating_results, modal_results, phase_baselines):
        all_seg_names.update(src.keys())

    baseline_keys = {
        "b0_single_remote": ("voting", "b0_single_remote"),
        "b1_uniform_remote": ("voting", "b1_uniform_remote"),
        "b2_modal_top2_equal": ("modal", "modal_top2_equal_fusion"),
        "b3_modal_eta_weight": ("modal", "modal_energy_ratio_fusion"),
        "t0_v3_eta_rho_weighted": ("voting", "t0_v3_eta_rho_weighted"),
        "t3_voting_modal_hybrid": ("voting", "t3_voting_modal_hybrid"),
        "g4_single_fallback": ("gating", "g4_single_fallback"),
        "single_phase": ("phase", "fft_single_max_energy"),
        "uniform_phase": ("phase", "fft_uniform_fusion"),
    }

    for seg_name in sorted(all_seg_names):
        for out_key, (source, src_key) in baseline_keys.items():
            block = None
            if source == "voting":
                row = voting_results.get(seg_name)
                block = row.get(src_key) if row else None
            elif source == "gating":
                row = gating_results.get(seg_name)
                block = row.get(src_key) if row else None
            elif source == "modal":
                row = modal_results.get(seg_name)
                block = row.get(src_key) if row else None
            elif source == "phase":
                row = phase_baselines.get(seg_name)
                block = row.get(src_key) if row else None
            if block is None:
                continue
            if merged.get(seg_name) is None:
                src_row = (
                    voting_results.get(seg_name)
                    or gating_results.get(seg_name)
                    or modal_results.get(seg_name)
                    or phase_baselines.get(seg_name)
                )
                if src_row is None:
                    continue
                merged[seg_name] = {
                    "segment": seg_name,
                    "bpm_gt": src_row.get("bpm_gt"),
                    "metadata": src_row.get("metadata"),
                }
            merged[seg_name][out_key] = block


def run_systematic_fusion_benchmark(
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
) -> dict:
    """Full systematic fusion benchmark: new methods + baselines."""
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

    if verbose:
        print("\n--- New systematic methods (Block A/B/C) ---")
    merged = _run_new_systematic_methods(
        multichannel_by_var,
        config=cfg,
        metric_params=mp,
        vcfg=vcfg,
        verbose=verbose,
    )

    if verbose:
        print("\n--- Baselines (voting / modal / gating / phase) ---")
    voting_bench = run_voting_fusion_benchmark(
        frames,
        segment_config,
        filter_params=fp,
        metric_params=mp,
        config=cfg,
        plan2_config=p2,
        verbose=verbose,
        cache_dir=cache_dir,
        multichannel_by_var=multichannel_by_var,
    )
    gating_bench = run_gating_benchmark(
        frames,
        segment_config,
        filter_params=fp,
        metric_params=mp,
        config=cfg,
        plan2_config=p2,
        verbose=verbose,
        cache_dir=cache_dir,
        multichannel_by_var=multichannel_by_var,
    )
    phase_baselines = estimate_segment_bpm_methods(
        multichannel_by_var["phases"],
        variable="phases",
        config=cfg,
        metric_params=mp,
        methods=("single", "uniform"),
        single_channel_metric=p2.channel_metric,
        verbose=False,
    )

    modal_bench = {"results": {}}
    for label, key, _ in (
        ("Modal top2", "modal_top2_equal_fusion", ""),
        ("Modal η", "modal_energy_ratio_fusion", ""),
    ):
        mode = "top2_equal" if key == "modal_top2_equal_fusion" else "energy_ratio"
        partial = estimate_modal_best_channel_fusion(
            multichannel_by_var,
            weight_mode=mode,
            config=cfg,
            metric_params=mp,
            plan2_config=p2,
            verbose=False,
        )
        for seg_name, row in partial.items():
            if row is None:
                modal_bench["results"].setdefault(seg_name, None)
                continue
            if modal_bench["results"].get(seg_name) is None:
                modal_bench["results"][seg_name] = {
                    "segment": seg_name,
                    "bpm_gt": row["bpm_gt"],
                    "metadata": row["metadata"],
                }
            modal_bench["results"][seg_name][key] = row[key]
        if verbose:
            stats = _overall_rel_error(partial, key)
            print(f"✓ [baseline {key}] mean err {stats['mean_rel_err_pct']:.2f}%")

    _merge_baseline_results(
        merged, voting_bench, gating_bench, modal_bench, phase_baselines
    )

    return {
        "results": merged,
        "multichannel_by_var": multichannel_by_var,
        "voting_benchmark": voting_bench,
        "gating_benchmark": gating_bench,
        "plan2_config": p2,
        "segment_config": segment_config,
    }


def build_systematic_leaderboard_rows(benchmark: dict) -> List[dict]:
    results = benchmark["results"]
    rows: List[dict] = []
    for label, key, color in ALL_METHOD_SPECS:
        stats = _overall_rel_error(results, key)
        if not np.isfinite(stats["mean_rel_err_pct"]):
            continue
        rows.append({"label": label, "method_key": key, "color": color, **stats})
    rows.sort(key=lambda r: r["mean_rel_err_pct"])
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def compute_systematic_cross_domain(
    results_by_scenario: Dict[str, dict],
) -> List[dict]:
    agg: List[dict] = []
    for label, key, color in ALL_METHOD_SPECS:
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


def _heatmap_grid_value(cross_domain: List[dict], method_key: str) -> float:
    for row in cross_domain:
        if row["method_key"] == method_key:
            return row["cross_domain_mean"]
    return np.nan


def plot_systematic_fusion_figures(
    results_by_scenario: Dict[str, dict],
    cross_domain: List[dict],
    *,
    figures_dir,
    scenario_ids: Sequence[str],
    show: bool = False,
    save: bool = True,
) -> dict:
    """Leaderboard, 2D heatmap, ablation waterfall, modal selection comparison."""
    import matplotlib.pyplot as plt
    from pathlib import Path

    figures_dir = Path(figures_dir)
    paths: dict = {}

    # --- Leaderboard ---
    fig, ax = plt.subplots(figsize=(13, 8))
    labels = [r["label"] for r in cross_domain]
    means = [r["cross_domain_mean"] for r in cross_domain]
    colors = [r["color"] for r in cross_domain]
    y_pos = np.arange(len(labels))
    ax.barh(y_pos, means, color=colors, alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Cross-domain mean BPM err %")
    ax.set_title("Systematic modal×channel fusion — cross-domain leaderboard")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    lb_path = figures_dir / "systematic_fusion_leaderboard.png"
    if save:
        fig.savefig(lb_path, dpi=150, bbox_inches="tight")
    paths["leaderboard"] = lb_path
    if not show:
        plt.close(fig)

    # --- 2D heatmap ---
    channel_rows = ["Single", "Uniform", "Vote", "VoteP"]
    modal_cols = ["Remote", "Phase", "Equal", "η-weight", "Top2"]
    cell_keys = {
        ("Single", "Remote"): "b0_single_remote",
        ("Uniform", "Remote"): "b1_uniform_remote",
        ("Single", "Top2"): "b2_modal_top2_equal",
        ("Vote", "Remote"): "t0_v3_eta_rho_weighted",
        ("Vote", "Phase"): "a1_phase_vote",
        ("VoteP", "Phase"): "a2_phase_votep",
        ("Vote", "Equal"): "b1_vote_modal_equal",
        ("Vote", "η-weight"): "b2_vote_modal_eta",
        ("Vote", "Top2"): "b3_vote_modal_top2",
        ("VoteP", "Top2"): "b4_votep_modal_top2",
        ("Uniform", "Top2"): "c1_uniform_modal_top2",
        ("Uniform", "η-weight"): "c2_uniform_modal_eta",
    }
    matrix = np.full((len(channel_rows), len(modal_cols)), np.nan)
    for (ch, mod), key in cell_keys.items():
        i = channel_rows.index(ch)
        j = modal_cols.index(mod)
        matrix[i, j] = _heatmap_grid_value(cross_domain, key)

    fig, ax = plt.subplots(figsize=(9, 5))
    im = ax.imshow(matrix, aspect="auto", cmap="RdYlGn_r", vmin=6, vmax=14)
    ax.set_xticks(np.arange(len(modal_cols)))
    ax.set_xticklabels(modal_cols)
    ax.set_yticks(np.arange(len(channel_rows)))
    ax.set_yticklabels(channel_rows)
    ax.set_title("Channel × Modal strategy grid (cross-domain mean err %)")
    for i in range(len(channel_rows)):
        for j in range(len(modal_cols)):
            val = matrix[i, j]
            if np.isfinite(val):
                ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=9, color="black")
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label="mean err %")
    fig.tight_layout()
    hm_path = figures_dir / "systematic_fusion_2d_heatmap.png"
    if save:
        fig.savefig(hm_path, dpi=150, bbox_inches="tight")
    paths["heatmap"] = hm_path
    if not show:
        plt.close(fig)

    # --- Ablation waterfall ---
    ablation_steps = [
        ("B0 Single Remote", "b0_single_remote"),
        ("A1 Phase voting", "a1_phase_vote"),
        ("T0-V3 Remote voting", "t0_v3_eta_rho_weighted"),
        ("B2 Modal top2", "b2_modal_top2_equal"),
        ("B3 Vote→Top2", "b3_vote_modal_top2"),
        ("G4 Gating", "g4_single_fallback"),
    ]
    step_vals = [_heatmap_grid_value(cross_domain, k) for _, k in ablation_steps]
    deltas = [0.0]
    for i in range(1, len(step_vals)):
        if np.isfinite(step_vals[i]) and np.isfinite(step_vals[i - 1]):
            deltas.append(step_vals[i] - step_vals[i - 1])
        else:
            deltas.append(0.0)

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(ablation_steps))
    bottoms = np.zeros(len(ablation_steps))
    for i in range(len(ablation_steps)):
        if i == 0:
            ax.bar(i, step_vals[i], color="steelblue", alpha=0.8)
        else:
            color = "seagreen" if deltas[i] < 0 else "indianred"
            ax.bar(i, deltas[i], bottom=step_vals[i - 1], color=color, alpha=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([s[0] for s in ablation_steps], rotation=25, ha="right", fontsize=8)
    ax.set_ylabel("Cross-domain mean err %")
    ax.set_title("Ablation waterfall (cumulative strategy steps)")
    ax.axhline(y=9.45, color="gray", linestyle="--", alpha=0.5, label="Modal top2 9.45%")
    ax.legend()
    fig.tight_layout()
    wf_path = figures_dir / "systematic_fusion_ablation_waterfall.png"
    if save:
        fig.savefig(wf_path, dpi=150, bbox_inches="tight")
    paths["waterfall"] = wf_path
    if not show:
        plt.close(fig)

    # --- Modal selection comparison (B3 vs B2) ---
    primary_sid = scenario_ids[0] if scenario_ids else next(iter(results_by_scenario))
    bench = results_by_scenario[primary_sid]
    results = bench["results"]
    b3_counts: Dict[str, int] = {}
    b2_counts: Dict[str, int] = {}
    for row in results.values():
        if row is None:
            continue
        b3 = row.get("b3_vote_modal_top2")
        b2 = row.get("b2_modal_top2_equal")
        if b3 and "modal_selections" in b3:
            for sel in b3["modal_selections"]:
                key = "+".join(sorted(sel)) if sel else "none"
                b3_counts[key] = b3_counts.get(key, 0) + 1
        if b2:
            b2_counts["single-best top2"] = b2_counts.get("single-best top2", 0) + int(
                b2.get("n_windows", 0)
            )

    if b3_counts:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        labels3 = list(b3_counts.keys())
        sizes3 = [b3_counts[k] for k in labels3]
        axes[0].pie(sizes3, labels=labels3, autopct="%1.1f%%", startangle=90)
        axes[0].set_title(f"B3 Vote→Top2 modal pairs ({primary_sid})")
        axes[1].bar(["B3 vote-top2", "B2 single-top2"], [sum(sizes3), sum(b2_counts.values()) or 0])
        axes[1].set_ylabel("Window count")
        axes[1].set_title("Modal fusion window coverage")
        fig.tight_layout()
        ms_path = figures_dir / "systematic_fusion_modal_selection.png"
        if save:
            fig.savefig(ms_path, dpi=150, bbox_inches="tight")
        paths["modal_selection"] = ms_path
        if not show:
            plt.close(fig)

    return paths
