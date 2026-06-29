"""Signal-level adaptive gating without hardcoded Remote fallback.

See ``docs/plans/signal_adaptive_gating_plan.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np

from ble_analysis.b1_gating_diagnosis import _compute_window_modal_bpm, _segment_from_window_bpms
from ble_analysis.chfusion import (
    ChFusionConfig,
    Plan2Config,
    _energy_ratio,
    _overall_rel_error,
    _peak_prominence,
    estimate_segment_bpm_methods,
)
from ble_analysis.consensus_gating import (
    compute_per_tone_eta_stats,
    compute_triplet_consensus_score,
    run_gating_benchmark,
)
from ble_analysis.segments import BreathMetricParams, FilterParams, _sliding_window_indices
from ble_analysis.systematic_fusion import (
    VAR_SHORT,
    estimate_systematic_fusion_segment,
    per_modal_voting_spectrum,
)
from ble_analysis.voting_fusion import (
    MODAL_VOTING_VARIABLES,
    VotingConfig,
    _bpm_from_waveform,
)

SAVariant = Literal["v1", "v1-noB1", "v2", "v1+SingleRemote"]

MODALITY_LABELS: Dict[str, str] = {
    "remote_amplitudes": "remote",
    "local_amplitudes": "local",
    "phases": "phase",
}

SA_METHOD_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("Single Remote", "single_remote", "steelblue"),
    ("Single Local", "single_local", "cadetblue"),
    ("Single Phase", "single_phase", "lightseagreen"),
    ("Best Single (η·ρ)", "best_single", "darkcyan"),
    ("B1 Vote→Equal", "b1_vote_modal_equal", "olive"),
    ("T0-V3", "t0_v3_eta_rho_weighted", "indianred"),
    ("Modal top2", "b2_modal_top2_equal", "mediumpurple"),
    ("SA-v1", "sa_v1", "seagreen"),
    ("SA-v1-noB1", "sa_v1_no_b1", "forestgreen"),
    ("SA-v2", "sa_v2", "darkgreen"),
    ("SA-v1+SingleRemote", "sa_v1_single_remote", "slategray"),
)

__all__ = [
    "SA_METHOD_SPECS",
    "compute_per_window_best_single",
    "compute_per_modal_voting_bpms",
    "gate_signal_adaptive",
    "calibrate_sa_v2_thresholds",
    "run_p1_b1_deviation_analysis",
    "run_signal_adaptive_gating_benchmark",
    "compute_sa_cross_domain_aggregate",
    "plot_signal_adaptive_figures",
]


def _single_best_bpm_eta_rho(
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
) -> Tuple[float, float]:
    """Single-channel BPM via max η·ρ selection for one modal variable."""
    best_score = -1.0
    best_bpm = float("nan")
    for ch in ch_map:
        ch_data = ch_map[ch][variable]
        hp = ch_data["highpass_filtered"]
        bp = ch_data["bandpass_filtered"]
        if len(hp) < end or len(bp) < end:
            continue
        eta = _energy_ratio(hp[st:end], fs, cfg)
        rho = _peak_prominence(bp[st:end], fs, cfg)
        score = eta * rho
        if score > best_score:
            best_score = score
            best_bpm = _bpm_from_waveform(bp[st:end], fs, cfg)
    return best_bpm, best_score


def compute_per_window_best_single(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
) -> Tuple[float, str, float]:
    """Return (bpm, modality_label, η·ρ score) for per-window best single channel."""
    best_bpm = float("nan")
    best_label = "none"
    best_score = -1.0
    for var in MODAL_VOTING_VARIABLES:
        seg = multichannel_by_var.get(var, {}).get(seg_name)
        if seg is None:
            continue
        bpm, score = _single_best_bpm_eta_rho(seg["channels"], var, st, end, fs, cfg)
        if score > best_score:
            best_score = score
            best_bpm = bpm
            best_label = MODALITY_LABELS[var]
    return best_bpm, best_label, best_score


def compute_per_modal_voting_bpms(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    vcfg: VotingConfig,
    metric_params: BreathMetricParams,
) -> Dict[str, float]:
    """Per-modal histogram-voting BPM from remote/local/phase."""
    from ble_analysis.chfusion import _next_pow2

    win_len = int(round(metric_params.window_length_sec * fs))
    nfft = cfg.nfft or _next_pow2(4 * win_len)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
    band_freqs = freqs[band_mask]
    hann = np.hanning(win_len)

    out: Dict[str, float] = {}
    for var in MODAL_VOTING_VARIABLES:
        seg = multichannel_by_var.get(var, {}).get(seg_name)
        if seg is None:
            out[VAR_SHORT[var]] = float("nan")
            continue
        ch_map = seg["channels"]
        ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
        _spec, bpm, _info = per_modal_voting_spectrum(
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
        )
        out[VAR_SHORT[var]] = float(bpm)
    return out


def _candidate_confidences(
    *,
    eta_vote: float,
    eta_modal: float,
    b1_mean_eta: float,
    best_single_score: float,
) -> Dict[str, float]:
    return {
        "vote": max(float(eta_vote), 0.0),
        "modal": max(float(eta_modal), 0.0),
        "b1": max(float(b1_mean_eta), 0.0),
        "best_single": max(float(best_single_score), 0.0),
    }


def _pick_highest_confidence(
    candidates: Dict[str, float],
    confidences: Dict[str, float],
) -> Tuple[float, str]:
    valid = {k: v for k, v in candidates.items() if np.isfinite(v)}
    if not valid:
        return float("nan"), "none"
    best_key = max(valid, key=lambda k: confidences.get(k, 0.0))
    return valid[best_key], best_key


def gate_signal_adaptive(
    bpm_vote: float,
    bpm_modal: float,
    bpm_b1: float,
    bpm_best_single: float,
    best_single_label: str,
    eta_stats: Dict[str, float],
    *,
    eta_vote: float = 0.0,
    eta_modal: float = 0.0,
    b1_mean_eta: float = 0.0,
    best_single_score: float = 0.0,
    bpm_single_remote: Optional[float] = None,
    delta: float = 3.0,
    consensus_threshold: float = 0.4,
    variant: SAVariant = "v1",
    tau_high: Optional[float] = None,
    tau_low: Optional[float] = None,
    cv_thresh: Optional[float] = None,
) -> Tuple[float, str, str]:
    """Signal-level adaptive gating; returns (bpm, decision_tag, fallback_modality)."""
    confidences = _candidate_confidences(
        eta_vote=eta_vote,
        eta_modal=eta_modal,
        b1_mean_eta=b1_mean_eta,
        best_single_score=best_single_score,
    )

    if variant == "v2" and tau_high is not None and tau_low is not None and cv_thresh is not None:
        mean_eta = float(eta_stats.get("mean", 0.0))
        eta_cv = float(eta_stats.get("cv", float("inf")))
        if mean_eta > tau_high and eta_cv < cv_thresh and np.isfinite(bpm_b1):
            return float(bpm_b1), "b1_direct", "b1"
        if mean_eta <= tau_low:
            if np.isfinite(bpm_best_single):
                return float(bpm_best_single), "best_single_low_eta", best_single_label
            return _pick_highest_confidence(
                {"vote": bpm_vote, "modal": bpm_modal, "b1": bpm_b1, "best_single": bpm_best_single},
                confidences,
            )[0], "best_conf_low_eta", best_single_label

    include_b1 = variant != "v1-noB1"
    candidates: Dict[str, float] = {
        "vote": float(bpm_vote),
        "modal": float(bpm_modal),
        "best_single": float(bpm_best_single),
    }
    if include_b1:
        candidates["b1"] = float(bpm_b1)

    finite = {k: v for k, v in candidates.items() if np.isfinite(v)}
    if not finite:
        fb = bpm_single_remote if variant == "v1+SingleRemote" and np.isfinite(bpm_single_remote) else bpm_best_single
        return float(fb), "empty_fallback", best_single_label

    if include_b1 and len(finite) >= 3:
        score = compute_triplet_consensus_score(bpm_vote, bpm_modal, bpm_b1)
    elif len(finite) >= 2:
        vals = list(finite.values())
        diffs = sorted(abs(vals[i] - vals[j]) for i in range(len(vals)) for j in range(i + 1, len(vals)))
        score = diffs[0] / (diffs[-1] + 1e-6) if diffs else 0.0
    else:
        key = next(iter(finite))
        return finite[key], f"{key}_only", best_single_label

    if score > consensus_threshold:
        pairs: List[Tuple[str, str, float]] = []
        keys = list(finite.keys())
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                ki, kj = keys[i], keys[j]
                pairs.append((ki, kj, abs(finite[ki] - finite[kj])))
        pairs.sort(key=lambda x: x[2])
        k1, k2, dist = pairs[0]
        if dist <= delta:
            if include_b1 and "b1" in (k1, k2) and len(finite) >= 3:
                vals = [finite[k] for k in ("vote", "modal", "b1") if k in finite]
                return float(np.mean(vals)), "triple_consensus", best_single_label
            return (finite[k1] + finite[k2]) / 2.0, f"{k1}_{k2}_pair_consensus", best_single_label
        pick, tag = _pick_highest_confidence({k1: finite[k1], k2: finite[k2]}, confidences)
        return pick, f"{tag}_pair_conf", tag

    if variant == "v1+SingleRemote" and np.isfinite(bpm_single_remote):
        return float(bpm_single_remote), "single_remote_fallback", "remote"

    pick, tag = _pick_highest_confidence(finite, confidences)
    return pick, f"{tag}_best_conf", tag


def calibrate_sa_v2_thresholds(
    window_records: Sequence[dict],
) -> Dict[str, float]:
    """Calibrate τ_high / τ_low / cv_thresh on 102621 per plan §3.2.3."""
    mean_etas = [float(r["eta_remote"]["mean"]) for r in window_records if r.get("eta_remote")]
    cvs = [float(r["eta_remote"]["cv"]) for r in window_records if r.get("eta_remote")]
    errors = [
        float(r["error_b1"])
        for r in window_records
        if np.isfinite(r.get("error_b1", float("nan")))
    ]
    if not mean_etas:
        return {"tau_high": 0.0, "tau_low": 0.0, "cv_thresh": float("inf")}

    if errors:
        order = np.argsort(errors)
        n_third = max(1, len(order) // 3)
        low_err_idx = order[:n_third]
        low_err_etas = [mean_etas[i] for i in low_err_idx if i < len(mean_etas)]
        tau_high = float(np.percentile(low_err_etas, 25)) if low_err_etas else float(np.percentile(mean_etas, 25))
    else:
        tau_high = float(np.percentile(mean_etas, 25))

    return {
        "tau_high": tau_high,
        "tau_low": float(np.median(mean_etas)),
        "cv_thresh": float(np.median(cvs)) if cvs else float("inf"),
    }


def run_p1_b1_deviation_analysis(
    window_records: Sequence[dict],
    scenario: str,
) -> dict:
    """P1: B1 deviation vs Voting/Modal consensus on one scenario."""
    records = list(window_records)
    type_counts = {"b1_disruptor": 0, "b1_improver": 0, "all_dispersed": 0, "other": 0}
    disruptor_spreads: List[float] = []
    improver_spreads: List[float] = []

    for r in records:
        b1_dev = float(r.get("b1_deviation", float("nan")))
        modal_div = float(r.get("modal_vote_divergence", float("nan")))
        error_b1 = float(r.get("error_b1", float("nan")))
        error_pair = float(r.get("error_pair", float("nan")))
        spread = float(r.get("per_modal_bpm_spread", float("nan")))

        if b1_dev > 3.0 and modal_div <= 3.0:
            wtype = "b1_disruptor"
            if np.isfinite(spread):
                disruptor_spreads.append(spread)
        elif np.isfinite(error_b1) and np.isfinite(error_pair) and error_b1 < error_pair - 0.5:
            wtype = "b1_improver"
            if np.isfinite(spread):
                improver_spreads.append(spread)
        elif float(r.get("min_pairwise_diff", float("inf"))) > 3.0:
            wtype = "all_dispersed"
        else:
            wtype = "other"
        type_counts[wtype] += 1
        r["window_type"] = wtype

    n = max(len(records), 1)
    return {
        "scenario": scenario,
        "n_windows": len(records),
        "type_fractions": {k: v / n for k, v in type_counts.items()},
        "type_counts": type_counts,
        "disruptor_mean_spread": float(np.mean(disruptor_spreads)) if disruptor_spreads else float("nan"),
        "improver_mean_spread": float(np.mean(improver_spreads)) if improver_spreads else float("nan"),
        "window_records": records,
    }


def _run_single_modality_baselines(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    plan2: Plan2Config,
) -> Dict[str, Optional[dict]]:
    """Single Remote / Local / Phase / Best Single segment baselines."""
    merged: Dict[str, Optional[dict]] = {}
    var_keys = {
        "remote_amplitudes": "single_remote",
        "local_amplitudes": "single_local",
        "phases": "single_phase",
    }
    for var, key in var_keys.items():
        partial = estimate_segment_bpm_methods(
            multichannel_by_var[var],
            variable=var,
            config=config,
            metric_params=metric_params,
            methods=("single",),
            single_channel_metric=plan2.channel_metric,
            verbose=False,
        )
        for seg_name, row in partial.items():
            if row is None:
                continue
            if merged.get(seg_name) is None:
                merged[seg_name] = {
                    "segment": seg_name,
                    "bpm_gt": row["bpm_gt"],
                    "metadata": row["metadata"],
                }
            merged[seg_name][key] = row["fft_single_max_energy"]

    for seg_name in sorted(multichannel_by_var["phases"].keys()):
        ref = multichannel_by_var["phases"].get(seg_name)
        if ref is None or ref["metadata"].get("segment_type") == "apnea":
            continue
        fs = ref["metadata"]["sampling_rate"]
        win_len = int(round(metric_params.window_length_sec * fs))
        step_len = int(round(metric_params.step_length_sec * fs))
        ref_len = max(
            len(c["phases"]["bandpass_filtered"])
            for c in ref["channels"].values()
        )
        if ref_len < win_len:
            continue
        starts = _sliding_window_indices(ref_len, win_len, step_len)
        bpms: List[float] = []
        labels: List[str] = []
        for st in starts:
            end = st + win_len
            bpm, label, _score = compute_per_window_best_single(
                multichannel_by_var, seg_name, st, end, fs, config
            )
            bpms.append(bpm)
            labels.append(label)
        row = merged.setdefault(
            seg_name,
            {
                "segment": seg_name,
                "bpm_gt": ref["metadata"].get("bpm_gt"),
                "metadata": ref["metadata"],
            },
        )
        from ble_analysis.chfusion import _seg_bpm_stats

        row["best_single"] = {
            **_seg_bpm_stats(np.asarray(bpms, dtype=float), row["bpm_gt"], len(starts)),
            "modality_labels": labels,
        }
    return merged


def run_signal_adaptive_gating_benchmark(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    segment_config: Dict[str, dict],
    *,
    filter_params: Optional[FilterParams] = None,
    metric_params: Optional[BreathMetricParams] = None,
    config: Optional[ChFusionConfig] = None,
    plan2_config: Optional[Plan2Config] = None,
    scenario_id: str = "",
    sa_v2_calibration: Optional[Dict[str, float]] = None,
    verbose: bool = True,
) -> dict:
    """Full signal-adaptive gating benchmark for one scenario."""
    _ = filter_params
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()
    p2 = plan2_config or Plan2Config(channel_metric="energy_ratio")
    vcfg = VotingConfig(voting_strategy="eta_rho_weighted")

    gating_bench = run_gating_benchmark(
        None,
        segment_config,
        metric_params=mp,
        config=cfg,
        plan2_config=p2,
        verbose=False,
        multichannel_by_var=multichannel_by_var,
    )
    merged = dict(gating_bench["results"])
    window_signals_by_seg = gating_bench["window_signals_by_seg"]

    single_merged = _run_single_modality_baselines(
        multichannel_by_var, config=cfg, metric_params=mp, plan2=p2
    )
    for seg_name, row in single_merged.items():
        if merged.get(seg_name) is None:
            merged[seg_name] = row
        else:
            for k, v in row.items():
                if k not in ("segment", "bpm_gt", "metadata"):
                    merged[seg_name][k] = v

    systematic_partial: Dict[str, Optional[dict]] = {}
    for seg_name in sorted(segment_config.keys()):
        row = estimate_systematic_fusion_segment(
            multichannel_by_var,
            seg_name,
            channel_strategy="vote",
            modal_strategy="equal",
            config=cfg,
            metric_params=mp,
            vcfg=vcfg,
            verbose=False,
        )
        if row is not None:
            systematic_partial[seg_name] = row
            if merged.get(seg_name) is None:
                merged[seg_name] = {
                    "segment": seg_name,
                    "bpm_gt": row["bpm_gt"],
                    "metadata": row["metadata"],
                }
            merged[seg_name]["b1_vote_modal_equal"] = row["b1_vote_modal_equal"]

    sa_variants: Tuple[Tuple[str, SAVariant], ...] = (
        ("sa_v1", "v1"),
        ("sa_v1_no_b1", "v1-noB1"),
        ("sa_v2", "v2"),
        ("sa_v1_single_remote", "v1+SingleRemote"),
    )
    sa_partial: Dict[str, Dict[str, Optional[dict]]] = {k: {} for k, _ in sa_variants}
    sa_decisions: Dict[str, Dict[str, int]] = {k: {} for k, _ in sa_variants}
    window_records_all: List[dict] = []
    segment_window_data: Dict[str, List[dict]] = {}

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
        ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
        ref_len = max(len(ch_map[c]["remote_amplitudes"]["bandpass_filtered"]) for c in ch_map)
        starts = _sliding_window_indices(ref_len, win_len, step_len)

        seg_windows: List[dict] = []

        for wi, ws in enumerate(signals):
            if wi >= len(starts):
                break
            st = int(starts[wi])
            end = st + win_len

            bpm_b1, _spectra, _sel = _compute_window_modal_bpm(
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
            )
            bpm_vote = ws["bpm_vote"]
            bpm_modal = ws["bpm_modal"]
            bpm_single_remote = ws["bpm_single"]
            bpm_best, best_label, best_score = compute_per_window_best_single(
                multichannel_by_var, seg_name, st, end, fs, cfg
            )
            per_modal_bpms = compute_per_modal_voting_bpms(
                multichannel_by_var, seg_name, st, end, fs, cfg, vcfg, mp
            )
            eta_remote = compute_per_tone_eta_stats(
                ch_list, ch_map, "remote_amplitudes", st, end, fs, cfg
            )
            local_seg = multichannel_by_var["local_amplitudes"].get(seg_name)
            if local_seg:
                local_ch_list = sorted(
                    local_seg["channels"].keys(), key=lambda c: (isinstance(c, str), str(c))
                )
                eta_local_stats = compute_per_tone_eta_stats(
                    local_ch_list,
                    local_seg["channels"],
                    "local_amplitudes",
                    st,
                    end,
                    fs,
                    cfg,
                )
            else:
                eta_local_stats = {"mean": 0.0, "cv": float("inf")}
            phase_seg = multichannel_by_var["phases"].get(seg_name)
            if phase_seg:
                phase_ch_list = sorted(
                    phase_seg["channels"].keys(), key=lambda c: (isinstance(c, str), str(c))
                )
                eta_phase_stats = compute_per_tone_eta_stats(
                    phase_ch_list,
                    phase_seg["channels"],
                    "phases",
                    st,
                    end,
                    fs,
                    cfg,
                )
            else:
                eta_phase_stats = {"mean": 0.0, "cv": float("inf")}
            max_eta_mean = max(
                eta_remote["mean"],
                eta_local_stats.get("mean", 0.0),
                eta_phase_stats.get("mean", 0.0),
            )

            b1_deviation = (
                abs(bpm_b1 - (bpm_vote + bpm_modal) / 2.0)
                if np.isfinite(bpm_b1) and np.isfinite(bpm_vote) and np.isfinite(bpm_modal)
                else float("nan")
            )
            modal_vote_divergence = (
                abs(bpm_vote - bpm_modal)
                if np.isfinite(bpm_vote) and np.isfinite(bpm_modal)
                else float("nan")
            )
            pm_vals = [v for v in per_modal_bpms.values() if np.isfinite(v)]
            per_modal_spread = float(np.std(pm_vals)) if len(pm_vals) >= 2 else float("nan")
            pair_vals = [v for v in (bpm_vote, bpm_modal, bpm_b1) if np.isfinite(v)]
            min_pair = (
                min(abs(pair_vals[i] - pair_vals[j]) for i in range(len(pair_vals)) for j in range(i + 1, len(pair_vals)))
                if len(pair_vals) >= 2
                else float("nan")
            )
            error_b1 = (
                abs(bpm_b1 - bpm_gt) / bpm_gt * 100.0
                if bpm_gt and bpm_gt > 0 and np.isfinite(bpm_b1)
                else float("nan")
            )
            error_pair = (
                abs((bpm_vote + bpm_modal) / 2.0 - bpm_gt) / bpm_gt * 100.0
                if bpm_gt and bpm_gt > 0 and np.isfinite(bpm_vote) and np.isfinite(bpm_modal)
                else float("nan")
            )

            wdata = {
                "ws": ws,
                "bpm_b1": bpm_b1,
                "bpm_best": bpm_best,
                "best_label": best_label,
                "best_score": best_score,
                "eta_remote": eta_remote,
            }
            seg_windows.append(wdata)

            rec = {
                "segment": seg_name,
                "window_index": wi,
                "bpm_vote": bpm_vote,
                "bpm_modal": bpm_modal,
                "bpm_b1": bpm_b1,
                "bpm_best_single": bpm_best,
                "best_single_label": best_label,
                "bpm_gt": bpm_gt,
                "b1_deviation": b1_deviation,
                "modal_vote_divergence": modal_vote_divergence,
                "per_modal_bpm_spread": per_modal_spread,
                "per_modal_bpms": per_modal_bpms,
                "min_pairwise_diff": min_pair,
                "triplet_consensus_score": compute_triplet_consensus_score(
                    bpm_vote, bpm_modal, bpm_b1
                ),
                "error_b1": error_b1,
                "error_pair": error_pair,
                "eta_remote": eta_remote,
                "eta_local": eta_local_stats,
                "eta_phase": eta_phase_stats,
                "max_eta_mean": max_eta_mean,
            }
            window_records_all.append(rec)

        segment_window_data[seg_name] = seg_windows

    if sa_v2_calibration is not None:
        calibration = dict(sa_v2_calibration)
    elif scenario_id == "cs_102621":
        calibration = calibrate_sa_v2_thresholds(window_records_all)
    else:
        calibration = {"tau_high": 0.0, "tau_low": 0.0, "cv_thresh": float("inf")}

    for seg_name, seg_windows in segment_window_data.items():
        row = merged.get(seg_name)
        if row is None:
            continue
        bpm_gt = row["bpm_gt"]
        metadata = row["metadata"]
        sa_window_bpms: Dict[str, List[float]] = {k: [] for k, _ in sa_variants}
        sa_decision_lists: Dict[str, List[str]] = {k: [] for k, _ in sa_variants}

        for wdata in seg_windows:
            ws = wdata["ws"]
            for sa_key, sa_var in sa_variants:
                bpm_out, tag, _fb_mod = gate_signal_adaptive(
                    ws["bpm_vote"],
                    ws["bpm_modal"],
                    wdata["bpm_b1"],
                    wdata["bpm_best"],
                    wdata["best_label"],
                    wdata["eta_remote"],
                    eta_vote=ws["eta_vote_max"],
                    eta_modal=ws["eta_modal_max"],
                    b1_mean_eta=wdata["eta_remote"]["mean"],
                    best_single_score=wdata["best_score"],
                    bpm_single_remote=ws["bpm_single"],
                    variant=sa_var,
                    tau_high=calibration.get("tau_high") if sa_var == "v2" else None,
                    tau_low=calibration.get("tau_low") if sa_var == "v2" else None,
                    cv_thresh=calibration.get("cv_thresh") if sa_var == "v2" else None,
                )
                sa_window_bpms[sa_key].append(bpm_out)
                sa_decision_lists[sa_key].append(tag)
                sa_decisions[sa_key][tag] = sa_decisions[sa_key].get(tag, 0) + 1

        for sa_key, _ in sa_variants:
            gated = _segment_from_window_bpms(
                seg_name,
                bpm_gt,
                metadata,
                sa_window_bpms[sa_key],
                sa_key,
                extra={"decision_tags": sa_decision_lists[sa_key]},
            )
            sa_partial[sa_key][seg_name] = gated

    for sa_key, _ in sa_variants:
        for seg_name, grow in sa_partial[sa_key].items():
            if merged.get(seg_name) is None:
                merged[seg_name] = grow
            else:
                merged[seg_name][sa_key] = grow[sa_key]
        if verbose:
            stats = _overall_rel_error(sa_partial[sa_key], sa_key)
            print(
                f"✓ [{sa_key}] mean err {stats['mean_rel_err_pct']:.2f}% "
                f"± {stats['std_rel_err_pct']:.2f}%"
            )

    p1_records = window_records_all if scenario_id == "cs_102621" else []
    p1 = run_p1_b1_deviation_analysis(p1_records, scenario_id)

    return {
        "results": merged,
        "multichannel_by_var": multichannel_by_var,
        "window_signals_by_seg": window_signals_by_seg,
        "window_records": window_records_all,
        "p1_analysis": p1,
        "sa_decision_counts": sa_decisions,
        "sa_v2_calibration": calibration,
        "gating_benchmark": gating_bench,
    }


def compute_sa_cross_domain_aggregate(
    results_by_scenario: Dict[str, dict],
    method_specs: Sequence[Tuple[str, str, str]] = SA_METHOD_SPECS,
) -> List[dict]:
    rows: List[dict] = []
    for label, key, color in method_specs:
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


def plot_signal_adaptive_figures(
    results_by_scenario: Dict[str, dict],
    cross_domain: List[dict],
    *,
    figures_dir,
    scenario_ids: Sequence[str],
    p1_by_scenario: Optional[Dict[str, dict]] = None,
    save: bool = True,
    show: bool = False,
) -> Dict[str, str]:
    figures_dir = Path(figures_dir)
    figures_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, str] = {}

    # Leaderboard
    fig, ax = plt.subplots(figsize=(12, 7))
    labels = [r["label"] for r in cross_domain]
    means = [r["cross_domain_mean"] for r in cross_domain]
    colors = [r["color"] for r in cross_domain]
    y = np.arange(len(labels))
    ax.barh(y, means, color=colors, alpha=0.85)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Cross-domain mean BPM err %")
    ax.set_title("Signal-adaptive gating — cross-domain leaderboard")
    ax.axvline(8.45, color="gray", linestyle="--", linewidth=1, label="B1 ref 8.45%")
    ax.legend(loc="lower right")
    ax.grid(True, axis="x", alpha=0.3)
    plt.tight_layout()
    p = figures_dir / "sa_leaderboard.png"
    fig.savefig(p, bbox_inches="tight", dpi=150)
    paths["leaderboard"] = str(p)
    plt.close(fig)

    # P1 scatter (102621)
    if p1_by_scenario and "cs_102621" in p1_by_scenario:
        recs = p1_by_scenario["cs_102621"].get("window_records", [])
        if recs:
            x = [r["per_modal_bpm_spread"] for r in recs]
            y = [r["b1_deviation"] for r in recs]
            fig, ax = plt.subplots(figsize=(7, 6))
            ax.scatter(x, y, alpha=0.5, s=18, c="teal")
            ax.set_xlabel("per_modal_bpm_spread")
            ax.set_ylabel("b1_deviation (BPM)")
            ax.set_title("P1: B1 deviation vs per-modal Voting spread (102621)")
            plt.tight_layout()
            p = figures_dir / "sa_p1_b1_deviation_scatter.png"
            fig.savefig(p, bbox_inches="tight", dpi=150)
            paths["p1_scatter"] = str(p)
            plt.close(fig)

            fracs = p1_by_scenario["cs_102621"].get("type_fractions", {})
            if fracs:
                fig, ax = plt.subplots(figsize=(6, 6))
                tags = list(fracs.keys())
                sizes = [fracs[t] for t in tags]
                ax.pie(sizes, labels=tags, autopct="%1.1f%%", startangle=90)
                ax.set_title("P1: Window type distribution (102621)")
                plt.tight_layout()
                p = figures_dir / "sa_p1_window_type_pie.png"
                fig.savefig(p, bbox_inches="tight", dpi=150)
                paths["p1_pie"] = str(p)
                plt.close(fig)

    # SA decision distribution (SA-v1)
    decision_totals: Dict[str, int] = {}
    for sid in scenario_ids:
        dc = results_by_scenario[sid].get("sa_decision_counts", {}).get("sa_v1", {})
        for tag, cnt in dc.items():
            decision_totals[tag] = decision_totals.get(tag, 0) + int(cnt)
    if decision_totals:
        fig, ax = plt.subplots(figsize=(7, 7))
        tags = list(decision_totals.keys())
        sizes = [decision_totals[t] for t in tags]
        ax.pie(sizes, labels=tags, autopct="%1.1f%%", startangle=90)
        ax.set_title("SA-v1 window decision distribution (all scenarios)")
        plt.tight_layout()
        p = figures_dir / "sa_decision_distribution.png"
        fig.savefig(p, bbox_inches="tight", dpi=150)
        paths["decision_pie"] = str(p)
        plt.close(fig)

    # Single modality comparison
    single_keys = ("single_remote", "single_local", "single_phase", "best_single")
    single_labels = ("Remote", "Local", "Phase", "Best Single")
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(single_labels))
    width = 0.25
    for i, sid in enumerate(scenario_ids):
        vals = []
        for key in single_keys:
            stats = _overall_rel_error(results_by_scenario[sid]["results"], key)
            vals.append(stats["mean_rel_err_pct"] if np.isfinite(stats["mean_rel_err_pct"]) else 0.0)
        ax.bar(x + i * width, vals, width, label=sid[-6:], alpha=0.85)
    ax.set_xticks(x + width)
    ax.set_xticklabels(single_labels)
    ax.set_ylabel("Mean BPM err %")
    ax.set_title("Single modality baselines by scenario")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    p = figures_dir / "sa_single_modality_comparison.png"
    fig.savefig(p, bbox_inches="tight", dpi=150)
    paths["single_modality"] = str(p)
    plt.close(fig)

    # P3 eta distribution
    eta_remote_all: Dict[str, List[float]] = {sid: [] for sid in scenario_ids}
    for sid in scenario_ids:
        for rec in results_by_scenario[sid].get("window_records", []):
            if rec.get("eta_remote"):
                eta_remote_all[sid].append(rec["eta_remote"]["mean"])
    if any(len(eta_remote_all[sid]) for sid in scenario_ids):
        fig, ax = plt.subplots(figsize=(8, 5))
        data = [eta_remote_all[sid] for sid in scenario_ids if eta_remote_all[sid]]
        ax.boxplot(data, labels=[sid[-6:] for sid in scenario_ids if eta_remote_all[sid]])
        ax.set_ylabel("mean per-tone η (remote)")
        ax.set_title("P3: Per-tone η distribution by scenario")
        plt.tight_layout()
        p = figures_dir / "sa_p3_eta_distribution.png"
        fig.savefig(p, bbox_inches="tight", dpi=150)
        paths["p3_eta"] = str(p)
        plt.close(fig)

    # SA-v1 vs SA-v1+SingleRemote ablation
    ablation_keys = ("sa_v1", "sa_v1_single_remote")
    ablation_labels = ("SA-v1 (best-single)", "SA-v1+SingleRemote")
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(scenario_ids))
    w = 0.35
    for j, (key, lab) in enumerate(zip(ablation_keys, ablation_labels)):
        vals = []
        for sid in scenario_ids:
            stats = _overall_rel_error(results_by_scenario[sid]["results"], key)
            vals.append(stats["mean_rel_err_pct"] if np.isfinite(stats["mean_rel_err_pct"]) else np.nan)
        ax.bar(x + j * w, vals, w, label=lab, alpha=0.85)
    ax.set_xticks(x + w / 2)
    ax.set_xticklabels([s[-6:] for s in scenario_ids])
    ax.set_ylabel("Mean BPM err %")
    ax.set_title("Ablation: dynamic vs hardcoded Remote fallback")
    ax.legend()
    plt.tight_layout()
    p = figures_dir / "sa_ablation_fallback_modality.png"
    fig.savefig(p, bbox_inches="tight", dpi=150)
    paths["ablation"] = str(p)
    plt.close(fig)

    # P3 091339 eta vs error
    if "cs_091339" in results_by_scenario:
        recs_091 = results_by_scenario["cs_091339"].get("window_records", [])
        if recs_091:
            eta_vals = [r["max_eta_mean"] for r in recs_091]
            err_vals = [r["error_b1"] for r in recs_091 if np.isfinite(r.get("error_b1", float("nan")))]
            if len(eta_vals) == len(err_vals) and err_vals:
                fig, ax = plt.subplots(figsize=(7, 5))
                ax.scatter(eta_vals, err_vals, alpha=0.4, s=15, c="coral")
                ax.set_xlabel("max-η (remote/local/phase)")
                ax.set_ylabel("B1 window error %")
                ax.set_title("P3: 091339 max-η vs B1 error")
                plt.tight_layout()
                p = figures_dir / "sa_p3_eta_vs_error.png"
                fig.savefig(p, bbox_inches="tight", dpi=150)
                paths["p3_eta_error"] = str(p)
                plt.close(fig)

    if show:
        plt.show()
    return paths
