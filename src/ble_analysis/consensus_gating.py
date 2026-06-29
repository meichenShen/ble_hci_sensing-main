"""Window-level consensus gating between voting and modal fusion.

See ``docs/plans/voting_gating_plan.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np

from ble_analysis.chfusion import (
    ChFusionConfig,
    Plan2Config,
    _energy_ratio,
    _find_best_channel,
    _overall_rel_error,
    _seg_bpm_stats,
    estimate_segment_bpm_methods,
    run_modal_fusion_benchmark,
    run_multichannel_segment_filtering,
)
from ble_analysis.segments import BreathMetricParams, FilterParams, _sliding_window_indices
from ble_analysis.voting_fusion import (
    MODAL_VOTING_VARIABLES,
    VotingConfig,
    _vote_one_window,
    _vote_weights,
    compute_channel_bpm_persistence,
    vote_bpm_weighted_histogram,
)

GatingStrategyKind = Literal[
    "consensus",
    "single_fallback",
    "bimodality",
    "persistence",
]

__all__ = [
    "GatingConfig",
    "GatingStrategyKind",
    "GatingDecision",
    "GATING_METHOD_SPECS",
    "compute_bimodality_score",
    "compute_tone_persistence",
    "compute_gating_signals",
    "compute_triplet_consensus_score",
    "compute_per_tone_eta_stats",
    "gate_three_candidates",
    "apply_gating_segment",
    "run_gating_benchmark",
    "build_gating_leaderboard_rows",
    "compute_gating_cross_domain_aggregate",
    "compute_oracle_selection_stats",
    "plot_gating_figures",
]


class GatingDecision(str, Enum):
    CONSENSUS_HIGH = "consensus_high"
    CONSENSUS_LOW = "consensus_low"
    VOTE_HIGH_CONF = "vote_high_conf"
    FALLBACK = "fallback"
    BIMODAL_VOTE = "bimodal_vote"
    BIMODAL_MODAL = "bimodal_modal"
    PERSISTENCE_VOTE = "persistence_vote"
    PERSISTENCE_MODAL = "persistence_modal"


@dataclass
class GatingConfig:
    """Window-level consensus gating configuration."""

    strategy: GatingStrategyKind = "consensus"
    delta_bpm: float = 3.0
    tau_hi: float = 0.30
    fallback_method: str = "single"
    consensus_weighting: str = "conf"
    min_eta_for_gating: float = 0.02
    adaptive_delta: bool = False
    delta_bpm_low_eta: float = 5.0
    delta_bpm_high_eta: float = 2.0
    eta_scale_ref: float = 0.15
    disagreement_mode: str = "standard"
    bimodality_threshold: float = 0.5
    peak1_mass_min: float = 0.25
    persistence_threshold: float = 2.0
    min_stable_tones: int = 12
    method_key: str = "gating"
    label: str = "Gating"


GATING_METHOD_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("B0 Single Remote", "b0_single_remote", "steelblue"),
    ("B1 Uniform Remote", "b1_uniform_remote", "seagreen"),
    ("B2 Modal top2 equal", "b2_modal_top2_equal", "mediumpurple"),
    ("B3 Modal η-weight", "b3_modal_eta_weight", "darkorange"),
    ("T0-V3 Per-Tone η·ρ-weight", "t0_v3_eta_rho_weighted", "indianred"),
    ("G1 Simple consensus", "g1_simple_consensus", "teal"),
    ("G2 Conf priority", "g2_conf_priority", "cadetblue"),
    ("G3 Adaptive δ", "g3_adaptive", "darkcyan"),
    ("G4 Single fallback", "g4_single_fallback", "slateblue"),
    ("G5 Bimodality gating", "g5_bimodality", "olive"),
    ("G6 Persistence voting", "g6_persistence", "saddlebrown"),
)

GATING_STRATEGY_PRESETS: Dict[str, GatingConfig] = {
    "g1_simple_consensus": GatingConfig(
        strategy="consensus",
        delta_bpm=3.0,
        tau_hi=0.30,
        method_key="g1_simple_consensus",
        label="G1 Simple consensus",
    ),
    "g2_conf_priority": GatingConfig(
        strategy="consensus",
        delta_bpm=2.0,
        tau_hi=0.35,
        disagreement_mode="conf_priority",
        method_key="g2_conf_priority",
        label="G2 Conf priority",
    ),
    "g3_adaptive": GatingConfig(
        strategy="consensus",
        delta_bpm=3.0,
        tau_hi=0.30,
        adaptive_delta=True,
        method_key="g3_adaptive",
        label="G3 Adaptive δ",
    ),
    "g4_single_fallback": GatingConfig(
        strategy="single_fallback",
        delta_bpm=3.0,
        method_key="g4_single_fallback",
        label="G4 Single fallback",
    ),
    "g5_bimodality": GatingConfig(
        strategy="bimodality",
        method_key="g5_bimodality",
        label="G5 Bimodality gating",
    ),
    "g6_persistence": GatingConfig(
        strategy="persistence",
        method_key="g6_persistence",
        label="G6 Persistence voting",
    ),
}


def _weighted_consensus_bpm(
    bpm_vote: float,
    bpm_modal: float,
    conf_vote: float,
    eta_vote_max: float,
    weighting: str,
) -> float:
    if weighting == "equal":
        w_vote = 1.0
    else:
        w_vote = conf_vote * max(eta_vote_max, 0.05)
    w_modal = 1.0
    return float((w_vote * bpm_vote + w_modal * bpm_modal) / (w_vote + w_modal))


def _adaptive_delta(config: GatingConfig, eta_vote: float, eta_modal: float) -> float:
    eta_ref = max(float(eta_vote), float(eta_modal), 0.0)
    scale = min(eta_ref / max(config.eta_scale_ref, 1e-9), 1.0)
    return float(
        config.delta_bpm_high_eta
        + (config.delta_bpm_low_eta - config.delta_bpm_high_eta) * (1.0 - scale)
    )


def compute_triplet_consensus_score(
    bpm_vote: float,
    bpm_modal: float,
    bpm_b1: float,
) -> float:
    """Triplet consistency score in [0, 1]; high = one close pair, low = all dispersed."""
    candidates = {
        "vote": float(bpm_vote),
        "modal": float(bpm_modal),
        "b1": float(bpm_b1),
    }
    finite = {k: v for k, v in candidates.items() if np.isfinite(v)}
    if len(finite) < 2:
        return 0.0
    keys = list(finite.keys())
    diffs = sorted(
        abs(finite[keys[i]] - finite[keys[j]])
        for i in range(len(keys))
        for j in range(i + 1, len(keys))
    )
    if not diffs:
        return 0.0
    return float(diffs[0] / (diffs[-1] + 1e-6))


def compute_per_tone_eta_stats(
    ch_list: Sequence[Any],
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
) -> Dict[str, float]:
    """Per-window η statistics over 72 tones for one modal variable."""
    etas: List[float] = []
    for ch in ch_list:
        ch_data = ch_map[ch][variable]
        hp = ch_data["highpass_filtered"]
        if len(hp) < end:
            continue
        etas.append(_energy_ratio(hp[st:end], fs, cfg))
    arr = np.asarray(etas, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {
            "mean": 0.0,
            "std": 0.0,
            "cv": float("inf"),
            "p10": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "n_tones": 0,
        }
    mean = float(np.mean(arr))
    std = float(np.std(arr))
    cv = float(std / (mean + cfg.eps)) if mean > cfg.eps else float("inf")
    return {
        "mean": mean,
        "std": std,
        "cv": cv,
        "p10": float(np.percentile(arr, 10)),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "n_tones": int(arr.size),
    }


def gate_three_candidates(
    bpm_b1: float,
    bpm_vote: float,
    bpm_modal: float,
    bpm_single: float,
    *,
    delta: float = 3.0,
    variant: str = "v1",
) -> Tuple[float, str]:
    """Three-candidate gating (B1, T0-V3 vote, Modal top2) with Single fallback.

    Returns ``(bpm, decision_tag)``.
    """
    candidates = {
        "vote": float(bpm_vote),
        "modal": float(bpm_modal),
        "b1": float(bpm_b1),
    }
    finite = {k: v for k, v in candidates.items() if np.isfinite(v)}

    if variant == "v4":
        a, b = finite.get("b1"), finite.get("modal")
        if a is None and b is None:
            return float(bpm_single), "fallback_single"
        if a is None:
            return b, "modal_only"
        if b is None:
            return a, "b1_only"
        if abs(a - b) <= delta:
            return (a + b) / 2.0, "b1_modal_consensus"
        return float(bpm_single), "fallback_single"

    if len(finite) == 0:
        return float(bpm_single), "fallback_single"
    if len(finite) == 1:
        key = next(iter(finite))
        return finite[key], f"{key}_only"

    keys = list(finite.keys())
    pairs: List[Tuple[str, str, float]] = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            ki, kj = keys[i], keys[j]
            pairs.append((ki, kj, abs(finite[ki] - finite[kj])))

    if variant == "v2":
        pairs.sort(key=lambda x: x[2])
        k1, k2, dist = pairs[0]
        if dist <= delta:
            return (finite[k1] + finite[k2]) / 2.0, f"{k1}_{k2}_top2"
        return float(bpm_single), "fallback_single"

    # v1: full G4-style three-candidate rules; v3: fallback to B1 instead of Single
    all_close = len(finite) == 3 and all(p[2] <= delta for p in pairs)
    if all_close:
        return (
            (finite["vote"] + finite["modal"] + finite["b1"]) / 3.0,
            "triple_consensus",
        )

    for k1, k2, dist in sorted(pairs, key=lambda x: (x[2], x[0])):
        if dist <= delta:
            return (finite[k1] + finite[k2]) / 2.0, f"{k1}_{k2}_consensus"

    if variant == "v3" and np.isfinite(bpm_b1):
        return float(bpm_b1), "b1_fallback"
    return float(bpm_single), "fallback_single"


def compute_bimodality_score(
    bpm_per_tone: np.ndarray,
    weights: np.ndarray,
    config: VotingConfig,
    min_bin_separation: int = 2,
) -> Tuple[float, float, float, float, int, int]:
    """Return bimodality score and histogram peak metadata."""
    bpms = np.asarray(bpm_per_tone, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask = np.isfinite(bpms) & np.isfinite(w) & (w > 0)
    if not np.any(mask):
        return 1.0, float("nan"), 0.0, 0.0, -1, -1

    bpms = bpms[mask]
    w = w[mask]
    step = config.bin_resolution_bpm
    edges = np.arange(
        config.bpm_bin_low - step / 2.0,
        config.bpm_bin_high + step,
        step,
    )
    centers = (edges[:-1] + edges[1:]) / 2.0
    bin_idx = np.clip(np.digitize(bpms, edges) - 1, 0, len(centers) - 1)

    bin_weights = np.zeros(len(centers), dtype=float)
    np.add.at(bin_weights, bin_idx, w)
    total_mass = float(np.sum(bin_weights))
    if total_mass <= 0:
        return 1.0, float("nan"), 0.0, 0.0, -1, -1

    order = np.argsort(bin_weights)[::-1]
    peak1 = int(order[0])
    peak1_mass = float(bin_weights[peak1])
    peak2 = -1
    peak2_mass = 0.0
    for idx in order[1:]:
        if abs(idx - peak1) >= min_bin_separation:
            peak2 = int(idx)
            peak2_mass = float(bin_weights[peak2])
            break

    if peak2 < 0 or peak1_mass <= 0:
        return 0.0, float(centers[peak1]), peak1_mass / total_mass, 0.0, peak1, peak2

    score = peak2_mass / peak1_mass
    return score, float(centers[peak1]), peak1_mass / total_mass, peak2_mass / total_mass, peak1, peak2


def compute_tone_persistence(
    bpm_per_tone_per_window: Sequence[np.ndarray],
) -> np.ndarray:
    """Per-tone mean |ΔBPM| across consecutive windows."""
    if not bpm_per_tone_per_window:
        return np.array([], dtype=float)
    n_win = len(bpm_per_tone_per_window)
    n_ch = max(len(np.asarray(tb)) for tb in bpm_per_tone_per_window)
    matrix = np.full((n_win, n_ch), np.nan, dtype=float)
    for wi, tb in enumerate(bpm_per_tone_per_window):
        tb = np.asarray(tb, dtype=float)
        n = min(len(tb), n_ch)
        matrix[wi, :n] = tb[:n]

    per_ch: List[float] = []
    for ci in range(n_ch):
        ys = matrix[:, ci]
        diffs = np.abs(np.diff(ys))
        valid = diffs[np.isfinite(diffs)]
        per_ch.append(float(np.mean(valid)) if valid.size else float("inf"))
    return np.asarray(per_ch, dtype=float)


def compute_gating_signals(
    bpm_vote: float,
    bpm_modal: float,
    bpm_single: float,
    conf_vote: float,
    eta_vote_max: float,
    eta_modal_max: float,
    config: GatingConfig,
) -> Tuple[GatingDecision, float]:
    """G1–G4 consensus / single-fallback decision for one window."""
    if not np.isfinite(bpm_vote) and not np.isfinite(bpm_modal):
        fb = bpm_single if config.fallback_method == "single" else bpm_modal
        return GatingDecision.FALLBACK, float(fb)

    if max(eta_vote_max, eta_modal_max) < config.min_eta_for_gating:
        fb = bpm_single if config.fallback_method == "single" else bpm_modal
        return GatingDecision.FALLBACK, float(fb)

    delta = (
        _adaptive_delta(config, eta_vote_max, eta_modal_max)
        if config.adaptive_delta
        else config.delta_bpm
    )

    if config.strategy == "single_fallback":
        if np.isfinite(bpm_vote) and np.isfinite(bpm_modal):
            if abs(bpm_vote - bpm_modal) <= delta:
                return GatingDecision.CONSENSUS_HIGH, _weighted_consensus_bpm(
                    bpm_vote,
                    bpm_modal,
                    conf_vote,
                    eta_vote_max,
                    config.consensus_weighting,
                )
            return GatingDecision.FALLBACK, float(bpm_single)
        fb = bpm_single if np.isfinite(bpm_single) else bpm_modal
        return GatingDecision.FALLBACK, float(fb)

    peak_dist = abs(bpm_vote - bpm_modal) if np.isfinite(bpm_vote) and np.isfinite(bpm_modal) else float("inf")
    consensus = peak_dist <= delta

    if consensus and conf_vote >= config.tau_hi:
        return GatingDecision.CONSENSUS_HIGH, _weighted_consensus_bpm(
            bpm_vote,
            bpm_modal,
            conf_vote,
            eta_vote_max,
            config.consensus_weighting,
        )
    if consensus and conf_vote < config.tau_hi:
        return GatingDecision.CONSENSUS_LOW, float(bpm_modal)
    if not consensus and conf_vote >= config.tau_hi:
        if config.disagreement_mode == "conf_priority" and eta_modal_max > eta_vote_max:
            return GatingDecision.CONSENSUS_LOW, float(bpm_modal)
        return GatingDecision.VOTE_HIGH_CONF, float(bpm_vote)

    fb = bpm_single if config.fallback_method == "single" else bpm_modal
    return GatingDecision.FALLBACK, float(fb)


def _apply_bimodality_gating(
    bpm_vote: float,
    bpm_modal: float,
    bpm_single: float,
    bpm_per_tone: np.ndarray,
    weights: np.ndarray,
    vcfg: VotingConfig,
    config: GatingConfig,
) -> Tuple[GatingDecision, float, float]:
    score, peak1_center, peak1_frac, _peak2_frac, _p1, _p2 = compute_bimodality_score(
        bpm_per_tone, weights, vcfg
    )
    if score < config.bimodality_threshold:
        return GatingDecision.BIMODAL_VOTE, float(bpm_vote), score

    if score >= config.bimodality_threshold and peak1_frac > config.peak1_mass_min:
        if np.isfinite(peak1_center) and np.isfinite(bpm_modal) and abs(peak1_center - bpm_modal) <= 2.0:
            bpm = _weighted_consensus_bpm(
                peak1_center,
                bpm_modal,
                peak1_frac,
                peak1_frac,
                "conf",
            )
            return GatingDecision.BIMODAL_MODAL, bpm, score
        if np.isfinite(bpm_modal):
            return GatingDecision.BIMODAL_MODAL, float(bpm_modal), score

    return GatingDecision.FALLBACK, float(bpm_single), score


def _vote_filtered_tones(
    bpm_per_tone: np.ndarray,
    eta_per_tone: np.ndarray,
    rho_per_tone: np.ndarray,
    stable_mask: np.ndarray,
    vcfg: VotingConfig,
) -> Tuple[float, float, int]:
    mask = stable_mask & np.isfinite(bpm_per_tone)
    if not np.any(mask):
        return float("nan"), 0.0, 0
    bpms = bpm_per_tone[mask]
    weights = _vote_weights(
        eta_per_tone[mask],
        rho_per_tone[mask],
        vcfg.voting_strategy,
    )
    bpm, _conf, win_mass = vote_bpm_weighted_histogram(bpms, weights, vcfg)
    total = float(np.sum(weights))
    conf = win_mass / total if total > 0 else 0.0
    return bpm, conf, int(np.sum(mask))


def _collect_vote_window_detail(
    ch_list: Sequence[Any],
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    vcfg: VotingConfig,
) -> dict:
    bpm_vote, _conf_flag, bpm_per_tone, eta_sel, rho_sel = _vote_one_window(
        ch_list, ch_map, variable, st, end, fs, cfg, vcfg
    )
    weights = _vote_weights(eta_sel, rho_sel, vcfg.voting_strategy, cfg.eps)
    _bpm, _conf_flag2, win_mass = vote_bpm_weighted_histogram(bpm_per_tone, weights, vcfg)
    total_w = float(np.sum(weights[np.isfinite(bpm_per_tone) & (weights > 0)]))
    conf_vote = win_mass / total_w if total_w > 0 else 0.0
    eta_max = float(np.max(eta_sel)) if len(eta_sel) else 0.0
    rho_mean = float(np.mean(rho_sel)) if len(rho_sel) else 0.0
    bimodality, peak1_center, peak1_frac, _, _, _ = compute_bimodality_score(
        bpm_per_tone, weights, vcfg
    )
    return {
        "bpm_vote": float(bpm_vote),
        "conf_vote": conf_vote,
        "win_mass_vote": win_mass,
        "eta_vote_max": eta_max,
        "rho_vote_mean": rho_mean,
        "bpm_per_tone": np.asarray(bpm_per_tone, dtype=float),
        "eta_per_tone": np.asarray(eta_sel, dtype=float),
        "rho_per_tone": np.asarray(rho_sel, dtype=float),
        "weights": np.asarray(weights, dtype=float),
        "bimodality_score": bimodality,
        "peak1_center": peak1_center,
        "peak1_frac": peak1_frac,
    }


def _modal_window_eta(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    plan2_config: Plan2Config,
) -> Tuple[float, float]:
    etas: List[float] = []
    for var in MODAL_VOTING_VARIABLES:
        seg = multichannel_by_var.get(var, {}).get(seg_name)
        if seg is None:
            continue
        ch_map = seg["channels"]
        best_ch, _ = _find_best_channel(
            ch_map, var, st, end, fs, cfg, metric=plan2_config.channel_metric
        )
        if best_ch is None:
            continue
        hp = ch_map[best_ch][var]["highpass_filtered"]
        if len(hp) >= end:
            etas.append(_energy_ratio(hp[st:end], fs, cfg))
    if not etas:
        return 0.0, 0.0
    etas_sorted = sorted(etas, reverse=True)
    eta_max = float(etas_sorted[0])
    eta_gap = float(etas_sorted[0] - etas_sorted[1]) if len(etas_sorted) > 1 else eta_max
    return eta_max, eta_gap


def collect_segment_window_signals(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    *,
    baselines_remote: Dict[str, Optional[dict]],
    modal_results: Dict[str, Optional[dict]],
    voting_results: Dict[str, Optional[dict]],
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    plan2_config: Plan2Config,
    vcfg: VotingConfig,
) -> Optional[List[dict]]:
    remote_seg = multichannel_by_var["remote_amplitudes"].get(seg_name)
    base_row = baselines_remote.get(seg_name)
    modal_row = modal_results.get(seg_name)
    vote_row = voting_results.get(seg_name)
    if remote_seg is None or base_row is None or modal_row is None or vote_row is None:
        return None

    metadata = remote_seg["metadata"]
    if metadata.get("segment_type") == "apnea":
        return None

    fs = metadata["sampling_rate"]
    ch_map = remote_seg["channels"]
    ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
    ref_len = max(len(ch_map[c]["remote_amplitudes"]["bandpass_filtered"]) for c in ch_list)
    win_len = int(round(metric_params.window_length_sec * fs))
    step_len = int(round(metric_params.step_length_sec * fs))
    if ref_len < win_len:
        return None

    single_block = base_row["fft_single_max_energy"]
    modal_block = modal_row["modal_top2_equal_fusion"]
    vote_block = vote_row["t0_v3_eta_rho_weighted"]
    single_series = np.asarray(single_block["bpm_per_window"], dtype=float)
    modal_series = np.asarray(modal_block["bpm_per_window"], dtype=float)

    starts = _sliding_window_indices(ref_len, win_len, step_len)
    windows: List[dict] = []
    for wi, st in enumerate(starts):
        end = st + win_len
        detail = _collect_vote_window_detail(
            ch_list, ch_map, "remote_amplitudes", st, end, fs, config, vcfg
        )
        eta_modal, eta_gap = _modal_window_eta(
            multichannel_by_var, seg_name, st, end, fs, config, plan2_config
        )
        windows.append(
            {
                "window_index": wi,
                **detail,
                "bpm_modal": float(modal_series[wi]) if wi < len(modal_series) else float("nan"),
                "bpm_single": float(single_series[wi]) if wi < len(single_series) else float("nan"),
                "eta_modal_max": eta_modal,
                "modal_eta_gap": eta_gap,
            }
        )
    return windows


def apply_gating_segment(
    window_signals: Sequence[dict],
    bpm_gt: Optional[float],
    *,
    gating_config: GatingConfig,
    vcfg: VotingConfig,
    tone_persistence: Optional[np.ndarray] = None,
) -> dict:
    """Apply one gating strategy to precomputed per-window signals."""
    bpms: List[float] = []
    decisions: List[str] = []
    extras: List[dict] = []

    for wi, ws in enumerate(window_signals):
        bpm_vote = ws["bpm_vote"]
        bpm_modal = ws["bpm_modal"]
        bpm_single = ws["bpm_single"]
        conf_vote = ws["conf_vote"]
        eta_vote = ws["eta_vote_max"]
        eta_modal = ws["eta_modal_max"]

        if gating_config.strategy == "bimodality":
            decision, bpm_final, bimodality = _apply_bimodality_gating(
                bpm_vote,
                bpm_modal,
                bpm_single,
                ws["bpm_per_tone"],
                ws["weights"],
                vcfg,
                gating_config,
            )
            decisions.append(decision.value)
            bpms.append(bpm_final)
            extras.append({"bimodality_score": bimodality})
            continue

        if gating_config.strategy == "persistence":
            if tone_persistence is None or len(tone_persistence) != len(ws["bpm_per_tone"]):
                stable_mask = np.ones_like(ws["bpm_per_tone"], dtype=bool)
            else:
                stable_mask = tone_persistence <= gating_config.persistence_threshold
            bpm_f, conf_f, n_stable = _vote_filtered_tones(
                ws["bpm_per_tone"],
                ws["eta_per_tone"],
                ws["rho_per_tone"],
                stable_mask,
                vcfg,
            )
            if n_stable >= gating_config.min_stable_tones and np.isfinite(bpm_f):
                decisions.append(GatingDecision.PERSISTENCE_VOTE.value)
                bpms.append(bpm_f)
                extras.append({"n_stable_tones": n_stable, "conf_vote": conf_f})
            elif np.isfinite(bpm_modal):
                decisions.append(GatingDecision.PERSISTENCE_MODAL.value)
                bpms.append(float(bpm_modal))
                extras.append({"n_stable_tones": n_stable})
            else:
                decisions.append(GatingDecision.FALLBACK.value)
                bpms.append(float(bpm_single))
                extras.append({"n_stable_tones": n_stable})
            continue

        decision, bpm_final = compute_gating_signals(
            bpm_vote,
            bpm_modal,
            bpm_single,
            conf_vote,
            eta_vote,
            eta_modal,
            gating_config,
        )
        decisions.append(decision.value)
        bpms.append(bpm_final)
        extras.append(
            {
                "peak_dist": abs(bpm_vote - bpm_modal)
                if np.isfinite(bpm_vote) and np.isfinite(bpm_modal)
                else float("nan"),
                "conf_vote": conf_vote,
            }
        )

    bpm_arr = np.asarray(bpms, dtype=float)
    stats = _seg_bpm_stats(bpm_arr, bpm_gt, len(window_signals))
    decision_counts: Dict[str, int] = {}
    for d in decisions:
        decision_counts[d] = decision_counts.get(d, 0) + 1

    return {
        **stats,
        "decisions": decisions,
        "decision_counts": decision_counts,
        "window_extras": extras,
        "bpm_per_tone_per_window": [ws["bpm_per_tone"] for ws in window_signals],
    }


def _estimate_voting_t0_v3(
    multichannel_segments: Dict[str, Optional[dict]],
    *,
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    vcfg: VotingConfig,
) -> Dict[str, Optional[dict]]:
    from ble_analysis.voting_fusion import estimate_voting_segment_methods

    return estimate_voting_segment_methods(
        multichannel_segments,
        variable="remote_amplitudes",
        config=config,
        metric_params=metric_params,
        voting_config=vcfg,
        method_key="t0_v3_eta_rho_weighted",
        verbose=False,
    )


def run_gating_benchmark(
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
    """End-to-end gating benchmark: baselines + T0-V3 + G1–G6."""
    cfg = config or ChFusionConfig()
    fp = filter_params or FilterParams()
    mp = metric_params or BreathMetricParams()
    p2 = plan2_config or Plan2Config(channel_metric="energy_ratio")
    vcfg = VotingConfig(voting_strategy="eta_rho_weighted")

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
    voting_partial = _estimate_voting_t0_v3(
        remote_mc, config=cfg, metric_params=mp, vcfg=vcfg
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

    for seg_name, row in voting_partial.items():
        if row is None:
            continue
        if merged.get(seg_name) is None:
            merged[seg_name] = {
                "segment": seg_name,
                "bpm_gt": row["bpm_gt"],
                "metadata": row["metadata"],
            }
        merged[seg_name]["t0_v3_eta_rho_weighted"] = row["t0_v3_eta_rho_weighted"]

    window_signals_by_seg: Dict[str, List[dict]] = {}
    for seg_name in sorted(merged.keys()):
        row = merged[seg_name]
        if row is None:
            continue
        signals = collect_segment_window_signals(
            multichannel_by_var,
            seg_name,
            baselines_remote=baselines_remote,
            modal_results=modal_results,
            voting_results={seg_name: row},
            config=cfg,
            metric_params=mp,
            plan2_config=p2,
            vcfg=vcfg,
        )
        if signals is not None:
            window_signals_by_seg[seg_name] = signals

    gating_decision_log: Dict[str, Dict[str, dict]] = {}
    for preset_key, gcfg in GATING_STRATEGY_PRESETS.items():
        partial: Dict[str, Optional[dict]] = {}
        for seg_name, signals in window_signals_by_seg.items():
            row = merged[seg_name]
            if row is None:
                continue
            bpm_gt = row["bpm_gt"]
            tone_persistence = None
            if gcfg.strategy == "persistence":
                vote_block = row["t0_v3_eta_rho_weighted"]
                ch_ids = vote_block.get("tone_channel_ids", [])
                pers = compute_channel_bpm_persistence(vote_block, ch_ids)
                per_ch = pers.get("per_channel_mean_step", [])
                if per_ch:
                    tone_persistence = np.asarray(per_ch, dtype=float)

            gated = apply_gating_segment(
                signals,
                bpm_gt,
                gating_config=gcfg,
                vcfg=vcfg,
                tone_persistence=tone_persistence,
            )
            partial[seg_name] = {
                "segment": seg_name,
                "bpm_gt": bpm_gt,
                "metadata": row["metadata"],
                preset_key: gated,
            }
            gating_decision_log.setdefault(seg_name, {})[preset_key] = gated["decision_counts"]

        for seg_name, grow in partial.items():
            if merged.get(seg_name) is None:
                merged[seg_name] = grow
            else:
                merged[seg_name][preset_key] = grow[preset_key]

        if verbose:
            stats = _overall_rel_error(partial, preset_key)
            print(
                f"✓ [{preset_key}] mean err {stats['mean_rel_err_pct']:.2f}% "
                f"± {stats['std_rel_err_pct']:.2f}%"
            )

    return {
        "results": merged,
        "multichannel_by_var": multichannel_by_var,
        "window_signals_by_seg": window_signals_by_seg,
        "gating_decision_log": gating_decision_log,
        "plan2_config": p2,
        "sampling_rate": fs,
        "segment_config": segment_config,
    }


def build_gating_leaderboard_rows(benchmark: dict) -> List[dict]:
    results = benchmark["results"]
    rows: List[dict] = []
    for label, key, color in GATING_METHOD_SPECS:
        stats = _overall_rel_error(results, key)
        if not np.isfinite(stats["mean_rel_err_pct"]):
            continue
        rows.append({"label": label, "method_key": key, "color": color, **stats})
    rows.sort(key=lambda r: r["mean_rel_err_pct"])
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def compute_gating_cross_domain_aggregate(
    results_by_scenario: Dict[str, dict],
) -> List[dict]:
    agg: List[dict] = []
    for label, key, color in GATING_METHOD_SPECS:
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


def compute_oracle_selection_stats(
    benchmark: dict,
    gating_method_key: str = "g1_simple_consensus",
) -> dict:
    """Per-segment oracle method distribution and gating pick accuracy."""
    results = benchmark["results"]
    window_signals = benchmark.get("window_signals_by_seg", {})
    rows: List[dict] = []

    for seg_name, signals in window_signals.items():
        row = results.get(seg_name)
        if row is None or gating_method_key not in row:
            continue
        gated = row[gating_method_key]
        bpm_gt = row["bpm_gt"]
        if not bpm_gt or bpm_gt <= 0:
            continue

        oracle_counts = {"vote": 0, "modal": 0, "single": 0}
        n_correct = 0
        n_total = 0
        gated_bpms = np.asarray(gated["bpm_per_window"], dtype=float)

        for wi, ws in enumerate(signals):
            candidates = {
                "vote": ws["bpm_vote"],
                "modal": ws["bpm_modal"],
                "single": ws["bpm_single"],
            }
            valid = {k: v for k, v in candidates.items() if np.isfinite(v)}
            if not valid:
                continue
            oracle_key = min(valid, key=lambda k: abs(valid[k] - bpm_gt))
            oracle_counts[oracle_key] += 1
            oracle_bpm = valid[oracle_key]
            if wi < len(gated_bpms) and np.isfinite(gated_bpms[wi]):
                if abs(gated_bpms[wi] - oracle_bpm) <= 0.5:
                    n_correct += 1
            n_total += 1

        rows.append(
            {
                "segment": seg_name,
                "oracle_vote_frac": oracle_counts["vote"] / max(n_total, 1),
                "oracle_modal_frac": oracle_counts["modal"] / max(n_total, 1),
                "oracle_single_frac": oracle_counts["single"] / max(n_total, 1),
                "gating_correct_frac": n_correct / max(n_total, 1),
                "n_windows": n_total,
            }
        )

    return {"rows": rows, "method_key": gating_method_key}


def plot_gating_figures(
    results_by_scenario: Dict[str, dict],
    cross_domain: List[dict],
    benchmark_primary: dict,
    *,
    figures_dir,
    scenario_ids: Sequence[str],
    show: bool = False,
    save: bool = True,
):
    """Decision pie, comparison bars, oracle heatmap."""
    import matplotlib.pyplot as plt
    from pathlib import Path

    figures_dir = Path(figures_dir)

    # --- Decision distribution (aggregate G1 across all segments/scenarios) ---
    decision_totals: Dict[str, int] = {}
    for sid in scenario_ids:
        log = results_by_scenario[sid].get("gating_decision_log", {})
        for seg_log in log.values():
            g1_counts = seg_log.get("g1_simple_consensus", {})
            for k, v in g1_counts.items():
                decision_totals[k] = decision_totals.get(k, 0) + int(v)

    if decision_totals:
        fig, ax = plt.subplots(figsize=(7, 5))
        labels = list(decision_totals.keys())
        sizes = [decision_totals[k] for k in labels]
        ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)
        ax.set_title("G1 window-level gating decisions (all scenarios)")
        fig.tight_layout()
        pie_path = figures_dir / "voting_gating_decision_pie.png"
        if save:
            fig.savefig(pie_path, dpi=150, bbox_inches="tight")
        if not show:
            plt.close(fig)

    # --- Cross-domain comparison bars ---
    fig, ax = plt.subplots(figsize=(13, 6))
    labels = [r["label"] for r in cross_domain]
    means = [r["cross_domain_mean"] for r in cross_domain]
    colors = [r["color"] for r in cross_domain]
    y_pos = np.arange(len(labels))
    ax.barh(y_pos, means, color=colors, alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Cross-domain mean BPM err %")
    ax.set_title("Voting gating — cross-domain leaderboard")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    bars_path = figures_dir / "voting_gating_comparison_bars.png"
    if save:
        fig.savefig(bars_path, dpi=150, bbox_inches="tight")
    if not show:
        plt.close(fig)

    # --- Oracle heatmap: segment × gating method correct rate ---
    gating_keys = [k for k in GATING_STRATEGY_PRESETS if k.startswith("g")]
    seg_names: List[str] = []
    for sid in scenario_ids:
        for seg in sorted(results_by_scenario[sid]["results"].keys()):
            if seg not in seg_names and results_by_scenario[sid]["results"][seg] is not None:
                meta = results_by_scenario[sid]["results"][seg]["metadata"]
                if meta.get("segment_type") != "apnea":
                    seg_names.append(seg)

    matrix = np.full((len(seg_names), len(gating_keys)), np.nan)
    for j, gkey in enumerate(gating_keys):
        for sid in scenario_ids:
            bench = {
                "results": results_by_scenario[sid]["results"],
                "window_signals_by_seg": results_by_scenario[sid].get(
                    "window_signals_by_seg", {}
                ),
            }
            oracle = compute_oracle_selection_stats(bench, gating_method_key=gkey)
            for r in oracle["rows"]:
                if r["segment"] in seg_names:
                    i = seg_names.index(r["segment"])
                    matrix[i, j] = r["gating_correct_frac"] * 100.0

    fig, ax = plt.subplots(figsize=(10, max(4, len(seg_names) * 0.45)))
    im = ax.imshow(matrix, aspect="auto", cmap="YlGn", vmin=0, vmax=100)
    ax.set_xticks(np.arange(len(gating_keys)))
    ax.set_xticklabels([GATING_STRATEGY_PRESETS[k].label for k in gating_keys], rotation=35, ha="right")
    ax.set_yticks(np.arange(len(seg_names)))
    ax.set_yticklabels(seg_names)
    ax.set_title("Oracle pick accuracy (% windows within 0.5 BPM of best method)")
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label="%")
    fig.tight_layout()
    heat_path = figures_dir / "voting_gating_oracle_heatmap.png"
    if save:
        fig.savefig(heat_path, dpi=150, bbox_inches="tight")
    if not show:
        plt.close(fig)

    return {
        "decision_pie": figures_dir / "voting_gating_decision_pie.png",
        "comparison_bars": bars_path,
        "oracle_heatmap": heat_path,
    }
