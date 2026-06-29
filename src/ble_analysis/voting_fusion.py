"""Per-tone BPM voting fusion for BLE CS multi-channel breathing estimation.

Implements Deng et al. (2024) style per-subcarrier BPM estimation + histogram
voting, adapted to BLE CS 72-tone data. See ``docs/plans/voting_fusion_plan.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np

from ble_analysis.chfusion import (
    ChFusionConfig,
    Plan2Config,
    _energy_ratio,
    _find_best_channel,
    _overall_rel_error,
    _parabolic_peak_freq,
    _peak_prominence,
    _seg_bpm_stats,
    _weighted_median,
    run_multichannel_segment_filtering,
    run_modal_fusion_benchmark,
)
from ble_analysis.segments import BreathMetricParams, FilterParams, _sliding_window_indices

VotingStrategy = Literal["simple", "eta_weighted", "eta_rho_weighted"]

MODAL_VOTING_VARIABLES: Tuple[str, ...] = (
    "remote_amplitudes",
    "local_amplitudes",
    "phases",
)

VOTING_METHOD_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("B0 Single Remote", "b0_single_remote", "steelblue"),
    ("B1 Uniform Remote", "b1_uniform_remote", "seagreen"),
    ("B2 Modal top2 equal", "b2_modal_top2_equal", "mediumpurple"),
    ("B3 Modal η-weight", "b3_modal_eta_weight", "darkorange"),
    ("T0-V1 Per-Tone simple", "t0_v1_simple", "coral"),
    ("T0-V2 Per-Tone η-weight", "t0_v2_eta_weighted", "tomato"),
    ("T0-V3 Per-Tone η·ρ-weight", "t0_v3_eta_rho_weighted", "indianred"),
    ("T1-K4 η-vote", "t1_k4_v2", "dodgerblue"),
    ("T1-K8 η-vote", "t1_k8_v2", "deepskyblue"),
    ("T1-K16 η-vote", "t1_k16_v2", "royalblue"),
    ("T2 Cross-Modal median", "t2_cross_modal_median", "goldenrod"),
    ("T3 Voting+Modal hybrid", "t3_voting_modal_hybrid", "crimson"),
)

# Methods overlaid on diagnostic panel 1 (label, result_key, color, linestyle)
DIAGNOSTIC_METHOD_OVERLAYS: Tuple[Tuple[str, str, str, str], ...] = (
    ("T0-V2 η-vote", "t0_v2_eta_weighted", "red", "-"),
    ("T0-V3 η·ρ-vote", "t0_v3_eta_rho_weighted", "darkorange", "-"),
    ("Modal top2", "b2_modal_top2_equal", "steelblue", "--"),
    ("Single Remote", "b0_single_remote", "seagreen", "--"),
    ("T3 hybrid", "t3_voting_modal_hybrid", "mediumpurple", "-."),
)

__all__ = [
    "VotingConfig",
    "VotingStrategy",
    "MODAL_VOTING_VARIABLES",
    "VOTING_METHOD_SPECS",
    "estimate_bpm_per_tone",
    "vote_bpm_histogram",
    "vote_bpm_weighted_histogram",
    "estimate_voting_segment_methods",
    "run_voting_fusion_benchmark",
    "build_voting_leaderboard_rows",
    "compute_cross_domain_aggregate",
    "plot_voting_diagnostics",
    "DIAGNOSTIC_METHOD_OVERLAYS",
]


@dataclass
class VotingConfig:
    """Voting fusion configuration."""

    variable: str = "remote_amplitudes"
    voting_strategy: VotingStrategy = "eta_weighted"
    top_k: Optional[int] = None
    vote_threshold: float = 0.3
    bin_resolution_bpm: float = 1.0
    bpm_bin_low: float = 6.0
    bpm_bin_high: float = 30.0
    breath_freq_low: float = 0.1
    breath_freq_high: float = 0.35


def _bpm_from_waveform(
    bandpass_seg: np.ndarray,
    fs: float,
    cfg: ChFusionConfig,
) -> float:
    """FFT peak BPM with parabolic refinement on one tone window."""
    if len(bandpass_seg) < 4 or not np.all(np.isfinite(bandpass_seg)):
        return float("nan")
    windowed = (bandpass_seg - np.mean(bandpass_seg)) * np.hanning(len(bandpass_seg))
    nfft = max(len(windowed), 256)
    fft_power = np.abs(np.fft.rfft(windowed, n=nfft)) ** 2
    fft_freq = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band_mask = (fft_freq >= cfg.breath_freq_low) & (fft_freq <= cfg.breath_freq_high)
    if not np.any(band_mask):
        return float("nan")
    band_freqs = fft_freq[band_mask]
    power_band = fft_power[band_mask]
    k = int(np.argmax(power_band))
    f_hat = _parabolic_peak_freq(band_freqs, power_band, k, cfg.eps)
    return float(60.0 * f_hat)


def _vote_weights(
    eta: np.ndarray,
    rho: np.ndarray,
    strategy: VotingStrategy,
    eps: float = 1e-12,
) -> np.ndarray:
    eta = np.maximum(np.asarray(eta, dtype=float), 0.0)
    rho = np.maximum(np.asarray(rho, dtype=float), 0.0)
    if strategy == "simple":
        return np.ones_like(eta)
    if strategy == "eta_weighted":
        return eta
    return eta * rho + eps


def _histogram_bin_edges(config: VotingConfig) -> np.ndarray:
    step = config.bin_resolution_bpm
    return np.arange(
        config.bpm_bin_low - step / 2.0,
        config.bpm_bin_high + step,
        step,
    )


def vote_bpm_histogram(
    bpm_per_tone: np.ndarray,
    config: VotingConfig,
) -> Tuple[float, bool, float]:
    """Simple (unweighted) histogram voting."""
    weights = np.ones_like(np.asarray(bpm_per_tone, dtype=float))
    return vote_bpm_weighted_histogram(bpm_per_tone, weights, config)


def vote_bpm_weighted_histogram(
    bpm_per_tone: np.ndarray,
    weights: np.ndarray,
    config: VotingConfig,
) -> Tuple[float, bool, float]:
    """Weighted histogram voting over per-tone BPM estimates.

    Returns
    -------
    final_bpm, confident, winning_mass
        ``winning_mass`` is vote count (simple) or weight sum in winning bin.
    """
    bpms = np.asarray(bpm_per_tone, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask = np.isfinite(bpms) & np.isfinite(w) & (w > 0)
    if not np.any(mask):
        return float("nan"), False, 0.0

    bpms = bpms[mask]
    w = w[mask]
    edges = _histogram_bin_edges(config)
    centers = (edges[:-1] + edges[1:]) / 2.0
    bin_idx = np.clip(np.digitize(bpms, edges) - 1, 0, len(centers) - 1)

    bin_weights = np.zeros(len(centers), dtype=float)
    np.add.at(bin_weights, bin_idx, w)
    best = int(np.argmax(bin_weights))
    winning_mass = float(bin_weights[best])
    threshold = config.vote_threshold * float(np.sum(w))
    confident = winning_mass >= threshold
    return float(centers[best]), confident, winning_mass


def estimate_bpm_per_tone(
    window_data: np.ndarray,
    eta_per_tone: np.ndarray,
    rho_per_tone: Optional[np.ndarray],
    config: VotingConfig,
    fs: float,
    chfusion_config: ChFusionConfig,
) -> Tuple[np.ndarray, np.ndarray]:
    """Independent BPM estimate for each tone in one window."""
    data = np.asarray(window_data, dtype=float)
    eta = np.asarray(eta_per_tone, dtype=float)
    rho = (
        np.asarray(rho_per_tone, dtype=float)
        if rho_per_tone is not None
        else np.ones_like(eta)
    )
    n_tones = data.shape[1] if data.ndim == 2 else len(data)
    bpm_out = np.full(n_tones, np.nan, dtype=float)
    quality = _vote_weights(eta, rho, config.voting_strategy, chfusion_config.eps)

    for i in range(n_tones):
        col = data[:, i] if data.ndim == 2 else data[i]
        bpm_out[i] = _bpm_from_waveform(col, fs, chfusion_config)

    return bpm_out, quality


def _select_top_k_indices(eta: np.ndarray, top_k: Optional[int]) -> np.ndarray:
    if top_k is None or top_k >= len(eta):
        return np.arange(len(eta))
    order = np.argsort(eta)
    return order[-top_k:]


def _vote_one_window(
    ch_list: Sequence[Any],
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    vcfg: VotingConfig,
) -> Tuple[float, bool, np.ndarray, np.ndarray, np.ndarray]:
    """Per-tone BPM + voting for one sliding window."""
    eta_list: List[float] = []
    rho_list: List[float] = []
    bp_cols: List[np.ndarray] = []

    for ch in ch_list:
        ch_data = ch_map[ch][variable]
        bp = ch_data["bandpass_filtered"]
        hp = ch_data["highpass_filtered"]
        if len(bp) < end or len(hp) < end:
            eta_list.append(0.0)
            rho_list.append(0.0)
            bp_cols.append(np.full(end - st, np.nan))
            continue
        bp_slice = bp[st:end]
        hp_slice = hp[st:end]
        eta_list.append(_energy_ratio(hp_slice, fs, cfg))
        rho_list.append(_peak_prominence(bp_slice, fs, cfg))
        bp_cols.append(bp_slice)

    eta = np.asarray(eta_list, dtype=float)
    rho = np.asarray(rho_list, dtype=float)
    data_matrix = np.column_stack(bp_cols)

    sel = _select_top_k_indices(eta, vcfg.top_k)
    data_sel = data_matrix[:, sel]
    eta_sel = eta[sel]
    rho_sel = rho[sel]

    bpm_per_tone, weights = estimate_bpm_per_tone(
        data_sel,
        eta_sel,
        rho_sel,
        vcfg,
        fs,
        cfg,
    )
    if vcfg.voting_strategy == "simple":
        final_bpm, confident, _ = vote_bpm_histogram(bpm_per_tone, vcfg)
    else:
        final_bpm, confident, _ = vote_bpm_weighted_histogram(
            bpm_per_tone, weights, vcfg
        )
    return final_bpm, confident, bpm_per_tone, eta_sel, rho_sel


def estimate_voting_segment_methods(
    multichannel_segments: Dict[str, Optional[dict]],
    *,
    variable: str = "remote_amplitudes",
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    voting_config: Optional[VotingConfig] = None,
    method_key: str = "voting",
    verbose: bool = False,
) -> Dict[str, Optional[dict]]:
    """Run per-tone voting BPM for one method configuration across segments."""
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()
    vcfg = voting_config or VotingConfig(variable=variable)
    vcfg = VotingConfig(
        variable=variable,
        voting_strategy=vcfg.voting_strategy,
        top_k=vcfg.top_k,
        vote_threshold=vcfg.vote_threshold,
        bin_resolution_bpm=vcfg.bin_resolution_bpm,
        bpm_bin_low=vcfg.bpm_bin_low,
        bpm_bin_high=vcfg.bpm_bin_high,
        breath_freq_low=cfg.breath_freq_low,
        breath_freq_high=cfg.breath_freq_high,
    )
    results: Dict[str, Optional[dict]] = {}

    for seg_name in sorted(multichannel_segments.keys()):
        seg = multichannel_segments[seg_name]
        if seg is None:
            results[seg_name] = None
            continue
        metadata = seg["metadata"]
        if metadata.get("segment_type") == "apnea":
            results[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]
        ch_map = seg["channels"]
        if not ch_map:
            results[seg_name] = None
            continue

        ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
        ref_len = max(len(ch_map[c][variable]["bandpass_filtered"]) for c in ch_list)
        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            if verbose:
                print(f"⚠️  {seg_name}: length {ref_len} < window {win_len}, skip")
            results[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        bpms: List[float] = []
        confident_flags: List[bool] = []
        tone_bpms_all: List[np.ndarray] = []

        for st in starts:
            end = st + win_len
            bpm, conf, tone_bpms, _eta, _rho = _vote_one_window(
                ch_list, ch_map, variable, st, end, fs, cfg, vcfg
            )
            bpms.append(bpm)
            confident_flags.append(conf)
            tone_bpms_all.append(tone_bpms)

        n_conf = int(np.sum(confident_flags))
        results[seg_name] = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "variable": variable,
            "metadata": metadata,
            method_key: {
                **_seg_bpm_stats(np.asarray(bpms), bpm_gt, len(starts)),
                "confident_per_window": confident_flags,
                "low_confidence_frac": 1.0 - n_conf / max(len(starts), 1),
                "bpm_per_tone_per_window": tone_bpms_all,
                "tone_channel_ids": list(ch_list),
            },
        }

    return results


def _merge_segment_results(
    base: Dict[str, Optional[dict]],
    partial: Dict[str, Optional[dict]],
    method_key: str,
) -> None:
    for seg_name, row in partial.items():
        if row is None:
            base.setdefault(seg_name, None)
            continue
        if base.get(seg_name) is None:
            base[seg_name] = {
                "segment": seg_name,
                "bpm_gt": row["bpm_gt"],
                "metadata": row["metadata"],
            }
        base[seg_name][method_key] = row[method_key]


def _estimate_t2_cross_modal(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    plan2_config: Plan2Config,
    method_key: str = "t2_cross_modal_median",
) -> Dict[str, Optional[dict]]:
    """Cross-modal voting: max-η tone BPM per modality → median."""
    mp = metric_params
    cfg = config
    p2 = plan2_config
    ref_var = "remote_amplitudes"
    ref_mc = multichannel_by_var[ref_var]
    merged: Dict[str, Optional[dict]] = {}

    for seg_name in sorted(ref_mc.keys()):
        ref_seg = ref_mc[seg_name]
        if ref_seg is None:
            merged[seg_name] = None
            continue
        metadata = ref_seg["metadata"]
        if metadata.get("segment_type") == "apnea":
            merged[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]
        ref_len = max(
            len(c[ref_var]["bandpass_filtered"])
            for c in ref_seg["channels"].values()
        )
        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            merged[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        bpms: List[float] = []

        for st in starts:
            end = st + win_len
            modal_bpms: List[float] = []
            for var in MODAL_VOTING_VARIABLES:
                seg = multichannel_by_var.get(var, {}).get(seg_name)
                if seg is None:
                    continue
                ch_map = seg["channels"]
                best_ch, _ = _find_best_channel(
                    ch_map, var, st, end, fs, cfg, metric=p2.channel_metric
                )
                if best_ch is None:
                    continue
                bp_slice = ch_map[best_ch][var]["bandpass_filtered"][st:end]
                modal_bpms.append(_bpm_from_waveform(bp_slice, fs, cfg))

            if modal_bpms:
                bpms.append(float(np.nanmedian(modal_bpms)))
            else:
                bpms.append(float("nan"))

        merged[seg_name] = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "metadata": metadata,
            method_key: _seg_bpm_stats(np.asarray(bpms), bpm_gt, len(starts)),
        }

    return merged


def _estimate_t3_hybrid(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    method_key: str = "t3_voting_modal_hybrid",
) -> Dict[str, Optional[dict]]:
    """Per-modality V2 voting → η-weighted median across modalities."""
    mp = metric_params
    cfg = config
    ref_var = "remote_amplitudes"
    ref_mc = multichannel_by_var[ref_var]
    vcfg = VotingConfig(voting_strategy="eta_weighted")
    merged: Dict[str, Optional[dict]] = {}

    for seg_name in sorted(ref_mc.keys()):
        ref_seg = ref_mc[seg_name]
        if ref_seg is None:
            merged[seg_name] = None
            continue
        metadata = ref_seg["metadata"]
        if metadata.get("segment_type") == "apnea":
            merged[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]
        ref_len = max(
            len(c[ref_var]["bandpass_filtered"])
            for c in ref_seg["channels"].values()
        )
        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            merged[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        bpms: List[float] = []
        confident_flags: List[bool] = []

        for st in starts:
            end = st + win_len
            modal_bpms: List[float] = []
            modal_weights: List[float] = []

            for var in MODAL_VOTING_VARIABLES:
                seg = multichannel_by_var.get(var, {}).get(seg_name)
                if seg is None:
                    continue
                ch_map = seg["channels"]
                ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
                vcfg_var = VotingConfig(variable=var, voting_strategy="eta_weighted")
                bpm, conf, _tone_bpms, eta_sel, _rho = _vote_one_window(
                    ch_list, ch_map, var, st, end, fs, cfg, vcfg_var
                )
                if np.isfinite(bpm):
                    modal_bpms.append(bpm)
                    modal_weights.append(float(np.max(eta_sel)) if len(eta_sel) else 0.0)
                confident_flags.append(conf)

            if modal_bpms:
                bpms.append(_weighted_median(np.asarray(modal_bpms), np.asarray(modal_weights)))
            else:
                bpms.append(float("nan"))

        n_conf = int(np.sum(confident_flags))
        merged[seg_name] = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "metadata": metadata,
            method_key: {
                **_seg_bpm_stats(np.asarray(bpms), bpm_gt, len(starts)),
                "low_confidence_frac": 1.0 - n_conf / max(len(confident_flags), 1),
            },
        }

    return merged


def run_voting_fusion_benchmark(
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
    """End-to-end voting fusion benchmark with Plan2 baselines."""
    from ble_analysis.chfusion import estimate_segment_bpm_methods

    cfg = config or ChFusionConfig()
    fp = filter_params or FilterParams()
    mp = metric_params or BreathMetricParams()
    p2 = plan2_config or Plan2Config(channel_metric="energy_ratio")

    if multichannel_by_var is None:
        multichannel_by_var = {}
        fs = None
        for variable in MODAL_VOTING_VARIABLES:
            mc, fs = run_multichannel_segment_filtering(
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
        fs = None
        for var_mc in multichannel_by_var.values():
            for seg in var_mc.values():
                if seg is not None:
                    fs = seg["metadata"]["sampling_rate"]
                    break
            if fs is not None:
                break

    remote_mc = multichannel_by_var["remote_amplitudes"]
    baselines_remote = estimate_segment_bpm_methods(
        remote_mc,
        variable="remote_amplitudes",
        config=cfg,
        metric_params=mp,
        methods=("single", "uniform"),
        single_channel_metric=p2.channel_metric,
        verbose=False,
    )
    modal_benchmark = run_modal_fusion_benchmark(
        multichannel_by_var,
        config=cfg,
        metric_params=mp,
        plan2_config=p2,
        verbose=verbose,
    )

    merged: Dict[str, Optional[dict]] = {}
    for seg_name, row in baselines_remote.items():
        if row is None:
            merged[seg_name] = None
            continue
        merged[seg_name] = {
            "segment": seg_name,
            "bpm_gt": row["bpm_gt"],
            "metadata": row["metadata"],
            "b0_single_remote": row["fft_single_max_energy"],
            "b1_uniform_remote": row["fft_uniform_fusion"],
        }

    modal_results = modal_benchmark["results"]
    for seg_name, row in modal_results.items():
        if row is None:
            continue
        if merged.get(seg_name) is None:
            merged[seg_name] = {
                "segment": seg_name,
                "bpm_gt": row["bpm_gt"],
                "metadata": row["metadata"],
            }
        merged[seg_name]["b2_modal_top2_equal"] = row.get("modal_top2_equal_fusion")
        merged[seg_name]["b3_modal_eta_weight"] = row.get("modal_energy_ratio_fusion")

    voting_jobs: List[Tuple[str, VotingConfig]] = [
        ("t0_v1_simple", VotingConfig(voting_strategy="simple")),
        ("t0_v2_eta_weighted", VotingConfig(voting_strategy="eta_weighted")),
        ("t0_v3_eta_rho_weighted", VotingConfig(voting_strategy="eta_rho_weighted")),
        ("t1_k4_v2", VotingConfig(voting_strategy="eta_weighted", top_k=4)),
        ("t1_k8_v2", VotingConfig(voting_strategy="eta_weighted", top_k=8)),
        ("t1_k16_v2", VotingConfig(voting_strategy="eta_weighted", top_k=16)),
    ]

    for method_key, vcfg in voting_jobs:
        partial = estimate_voting_segment_methods(
            remote_mc,
            variable="remote_amplitudes",
            config=cfg,
            metric_params=mp,
            voting_config=vcfg,
            method_key=method_key,
            verbose=False,
        )
        _merge_segment_results(merged, partial, method_key)
        if verbose:
            stats = _overall_rel_error(partial, method_key)
            print(
                f"✓ [{method_key}] mean err {stats['mean_rel_err_pct']:.2f}% "
                f"± {stats['std_rel_err_pct']:.2f}%"
            )

    t2 = _estimate_t2_cross_modal(
        multichannel_by_var,
        config=cfg,
        metric_params=mp,
        plan2_config=p2,
    )
    _merge_segment_results(merged, t2, "t2_cross_modal_median")
    if verbose:
        stats = _overall_rel_error(t2, "t2_cross_modal_median")
        print(f"✓ [t2_cross_modal_median] mean err {stats['mean_rel_err_pct']:.2f}%")

    t3 = _estimate_t3_hybrid(
        multichannel_by_var,
        config=cfg,
        metric_params=mp,
    )
    _merge_segment_results(merged, t3, "t3_voting_modal_hybrid")
    if verbose:
        stats = _overall_rel_error(t3, "t3_voting_modal_hybrid")
        print(f"✓ [t3_voting_modal_hybrid] mean err {stats['mean_rel_err_pct']:.2f}%")

    return {
        "results": merged,
        "multichannel_by_var": multichannel_by_var,
        "baselines_remote": baselines_remote,
        "modal_benchmark": modal_benchmark,
        "plan2_config": p2,
        "sampling_rate": fs,
        "segment_config": segment_config,
    }


def build_voting_leaderboard_rows(benchmark: dict) -> List[dict]:
    """Overall mean relative BPM error per method, sorted ascending."""
    results = benchmark["results"]
    rows: List[dict] = []
    for label, key, color in VOTING_METHOD_SPECS:
        stats = _overall_rel_error(results, key)
        if not np.isfinite(stats["mean_rel_err_pct"]):
            continue
        rows.append({"label": label, "method_key": key, "color": color, **stats})
    rows.sort(key=lambda r: r["mean_rel_err_pct"])
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def compute_cross_domain_aggregate(
    results_by_scenario: Dict[str, dict],
) -> List[dict]:
    """Mean of per-scenario mean err% for each method."""
    agg: List[dict] = []
    for label, key, color in VOTING_METHOD_SPECS:
        means = []
        for _sid, bench in results_by_scenario.items():
            stats = _overall_rel_error(bench["results"], key)
            if np.isfinite(stats["mean_rel_err_pct"]):
                means.append(stats["mean_rel_err_pct"])
        if not means:
            continue
        agg.append(
            {
                "label": label,
                "method_key": key,
                "color": color,
                "cross_domain_mean": float(np.mean(means)),
                "cross_domain_std": float(np.std(means, ddof=1)) if len(means) > 1 else 0.0,
                "n_scenarios": len(means),
                "per_scenario": means,
            }
        )
    agg.sort(key=lambda r: r["cross_domain_mean"])
    for rank, row in enumerate(agg, start=1):
        row["rank"] = rank
    return agg


def _segment_method_bpm_series(segment_row: dict, method_key: str) -> Optional[np.ndarray]:
    """Window-level BPM array for one method on one segment."""
    block = segment_row.get(method_key)
    if not isinstance(block, dict):
        return None
    arr = block.get("bpm_per_window")
    if arr is None:
        return None
    return np.asarray(arr, dtype=float)


def plot_voting_diagnostics(
    segment_row: dict,
    *,
    seg_name: str,
    gt: float,
    tone_channel_ids: Sequence[Any],
    figures_dir,
    scenario_tag: str = "091339",
    per_tone_method_key: str = "t0_v2_eta_weighted",
    overlay_methods: Optional[Sequence[Tuple[str, str, str, str]]] = None,
    show: bool = False,
    save: bool = True,
):
    """Three-panel voting diagnostics.

    Panel 1 scatter: per-tone BPM from ``per_tone_method_key`` (default T0-V2).
    Colored lines: window-level BPM trajectories for ``overlay_methods``.
    """
    import matplotlib.pyplot as plt
    from pathlib import Path

    block = segment_row.get(per_tone_method_key, {})
    if not isinstance(block, dict):
        block = segment_row

    tone_bpms = block.get("bpm_per_tone_per_window", [])
    overlays = overlay_methods or DIAGNOSTIC_METHOD_OVERLAYS
    ch_ids = list(tone_channel_ids)
    n_ch = len(ch_ids)
    cmap = plt.cm.twilight
    norm = plt.Normalize(vmin=0, vmax=max(n_ch - 1, 1))

    n_win = len(tone_bpms)
    fig = plt.figure(figsize=(17, 5.5))
    gs = fig.add_gridspec(1, 3, width_ratios=[2.4, 0.85, 1.0], wspace=0.30)
    ax0 = fig.add_subplot(gs[0, 0])
    ax1 = fig.add_subplot(gs[0, 1])
    ax2 = fig.add_subplot(gs[0, 2])

    # --- Panel 1: per-tone scatter (T0-V2) + multi-method BPM trajectories ---
    bpm_matrix = np.full((n_win, n_ch), np.nan, dtype=float)
    for wi, tb in enumerate(tone_bpms):
        tb = np.asarray(tb, dtype=float)
        n = min(len(tb), n_ch)
        bpm_matrix[wi, :n] = tb[:n]

    for ci in range(n_ch):
        color = cmap(norm(ci))
        ys = bpm_matrix[:, ci]
        xs = np.arange(n_win, dtype=float)
        valid = np.isfinite(ys)
        if np.sum(valid) == 0:
            continue
        ax0.scatter(xs[valid], ys[valid], c=[color], s=8, alpha=0.55, linewidths=0)
        for wi in range(n_win - 1):
            if np.isfinite(ys[wi]) and np.isfinite(ys[wi + 1]):
                ax0.plot(
                    [wi, wi + 1],
                    [ys[wi], ys[wi + 1]],
                    color=color,
                    alpha=0.10,
                    linewidth=0.5,
                    zorder=0,
                )

    last_window_bpms: List[Tuple[str, float, str]] = []
    for label, key, color, ls in overlays:
        series = _segment_method_bpm_series(segment_row, key)
        if series is None or len(series) == 0:
            continue
        win_x = np.arange(len(series))
        valid = np.isfinite(series)
        if np.any(valid):
            ax0.plot(
                win_x[valid],
                series[valid],
                color=color,
                linewidth=1.6 if key == per_tone_method_key else 1.3,
                linestyle=ls,
                alpha=0.92,
                label=label,
                zorder=6,
            )
        if len(series) and np.isfinite(series[-1]):
            last_window_bpms.append((label, float(series[-1]), color))

    ax0.axhline(gt, color="black", linewidth=2, label=f"GT={gt:.2f}", zorder=7)
    ax0.set_xlabel("Sliding window index")
    ax0.set_ylabel("BPM")
    ax0.set_title(
        f"Per-tone BPM (scatter, {per_tone_method_key}) + method trajectories\n"
        f"seg {seg_name}: {n_win} windows × {n_ch} tones | color = tone index"
    )
    ax0.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=7, framealpha=0.9)
    ax0.grid(True, alpha=0.2)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax0, fraction=0.022, pad=0.18)
    cbar.set_label("Tone index")

    # --- Panel 2: T0-V2 voting confidence ---
    conf_block = segment_row.get(per_tone_method_key, block)
    conf_frac = 1.0 - conf_block.get("low_confidence_frac", 0.0)
    ax1.bar(["confident", "low-conf"], [conf_frac, 1 - conf_frac], color=["green", "orange"])
    ax1.set_ylabel("Fraction of windows")
    ax1.set_title("Voting confidence\n(T0-V2 only)")
    ax1.set_ylim(0, 1)

    # --- Panel 3: T0-V2 per-tone histogram + all methods last-window BPM ---
    if tone_bpms:
        tb = np.asarray(tone_bpms[-1], dtype=float)
        valid = tb[np.isfinite(tb)]
        ax2.hist(valid, bins=np.arange(5.5, 31.5, 1.0), edgecolor="black", alpha=0.65, label="T0-V2 tones")
        ax2.axvline(gt, color="black", linestyle="-", linewidth=2, label=f"GT={gt:.2f}")
        for label, bpm, color in last_window_bpms:
            ax2.axvline(
                bpm,
                color=color,
                linestyle="--",
                linewidth=1.2,
                alpha=0.85,
                label=f"{label}={bpm:.1f}",
            )
        ax2.set_xlabel("BPM")
        ax2.set_ylabel("Tone count")
        ax2.set_title("Last window: tone histogram + method BPM")
        ax2.legend(fontsize=6.5, loc="upper right")

    fig.suptitle(
        f"Voting diagnostics — cs_{scenario_tag} / seg {seg_name}",
        fontsize=11,
        y=1.01,
    )
    fig.subplots_adjust(top=0.90, wspace=0.38, right=0.88)

    diag_path = Path(figures_dir) / "voting_fusion_diagnostics.pdf"
    if save:
        fig.savefig(diag_path, bbox_inches="tight")
        print(f"Saved: {diag_path}")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return diag_path


def compute_channel_bpm_persistence(
    block: dict,
    tone_channel_ids: Sequence[Any],
) -> dict:
    """Per-channel BPM stability across consecutive windows (L1 step mean)."""
    tone_bpms = block.get("bpm_per_tone_per_window", [])
    n_ch = len(tone_channel_ids)
    n_win = len(tone_bpms)
    if n_win < 2 or n_ch == 0:
        return {"mean_step_l1": np.nan, "per_channel_mean_step": []}

    matrix = np.full((n_win, n_ch), np.nan)
    for wi, tb in enumerate(tone_bpms):
        tb = np.asarray(tb, dtype=float)
        n = min(len(tb), n_ch)
        matrix[wi, :n] = tb[:n]

    per_ch_steps: List[float] = []
    for ci in range(n_ch):
        ys = matrix[:, ci]
        diffs = np.abs(np.diff(ys))
        valid = diffs[np.isfinite(diffs)]
        if valid.size:
            per_ch_steps.append(float(np.mean(valid)))

    return {
        "mean_step_l1": float(np.mean(per_ch_steps)) if per_ch_steps else np.nan,
        "per_channel_mean_step": per_ch_steps,
        "n_windows": n_win,
        "n_channels": n_ch,
    }
