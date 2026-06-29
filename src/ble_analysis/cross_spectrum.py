"""Cross-spectrum combining for BLE CS channel fusion.

See ``docs/plans/cross_spectrum_combining_plan.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np

from ble_analysis.chfusion import (
    ChFusionConfig,
    _bpm_from_fused_spectrum,
    _energy_ratio,
    _next_pow2,
    _overall_rel_error,
    _peak_prominence,
    _seg_bpm_stats,
    run_multichannel_segment_filtering,
)
from ble_analysis.segments import BreathMetricParams, FilterParams, _sliding_window_indices
from ble_analysis.systematic_fusion import (
    MODAL_VOTING_VARIABLES,
    VAR_SHORT,
    modal_fusion_from_spectra,
    per_modal_voting_spectrum,
)
from ble_analysis.voting_fusion import VotingConfig

CrossSpectrumMode = Literal["magnitude", "real", "coherent"]

CROSS_SPECTRUM_METHOD_SPECS: Tuple[Tuple[str, str, str, CrossSpectrumMode, Optional[int]], ...] = (
    ("X1 CrossSpec-mag-all", "x1_cross_mag_all", "teal", "magnitude", None),
    ("X2 CrossSpec-real-all", "x2_cross_real_all", "darkcyan", "real", None),
    ("X3 CrossSpec-coh-all", "x3_cross_coh_all", "cadetblue", "coherent", None),
    ("X4 CrossSpec-mag-d1", "x4_cross_mag_d1", "olive", "magnitude", 1),
    ("X5 CrossSpec-real-d1", "x5_cross_real_d1", "darkolivegreen", "real", 1),
    ("X6 CrossSpec-mag-d5", "x6_cross_mag_d5", "seagreen", "magnitude", 5),
    ("X7 CrossSpec-real-d5", "x7_cross_real_d5", "forestgreen", "real", 5),
)

X0_BASELINE_SPEC: Tuple[str, str, str] = (
    "X0 B1 Vote→Equal",
    "x0_b1_vote_equal",
    "steelblue",
)

REFERENCE_BASELINE_SPECS: Tuple[Tuple[str, str, str, str], ...] = (
    ("B0 Single Remote", "b0_single_remote", "gray", "systematic_fusion"),
    ("B1 Uniform Remote", "b1_uniform_remote", "lightgray", "systematic_fusion"),
    ("B2 Modal top2 equal", "b2_modal_top2_equal", "mediumpurple", "systematic_fusion"),
    ("T0-V3 Per-Tone η·ρ", "t0_v3_eta_rho_weighted", "indianred", "systematic_fusion"),
    ("G4 Single fallback", "g4_single_fallback", "slateblue", "systematic_fusion"),
)

__all__ = [
    "CrossSpectrumConfig",
    "CrossSpectrumMode",
    "CROSS_SPECTRUM_METHOD_SPECS",
    "X0_BASELINE_SPEC",
    "REFERENCE_BASELINE_SPECS",
    "per_modal_cross_spectrum",
    "estimate_cross_spectrum_segment",
    "run_cross_spectrum_benchmark",
    "build_cross_spectrum_leaderboard_rows",
    "compute_cross_spectrum_cross_domain",
    "plot_cross_spectrum_figures",
    "import_reference_baselines",
    "import_x0_from_systematic",
]


@dataclass
class CrossSpectrumConfig:
    cross_mode: CrossSpectrumMode = "magnitude"
    max_delta_k: Optional[int] = None
    weight_mode: str = "eta_rho_product"


def _collect_tone_fft_data(
    ch_list: Sequence[Any],
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    nfft: int,
    band_mask: np.ndarray,
    hann: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-tone complex breath-band spectra and η·ρ quality weights."""
    n_ch = len(ch_list)
    n_bins = int(np.sum(band_mask))
    x_fft = np.zeros((n_ch, n_bins), dtype=np.complex128)
    q = np.zeros(n_ch, dtype=float)

    for idx, ch in enumerate(ch_list):
        ch_data = ch_map[ch][variable]
        bp = ch_data["bandpass_filtered"]
        hp = ch_data["highpass_filtered"]
        if len(bp) < end or len(hp) < end:
            continue

        bp_slice = bp[st:end]
        hp_slice = hp[st:end]
        if len(bp_slice) != len(hann) or not np.all(np.isfinite(bp_slice)):
            continue

        eta = _energy_ratio(hp_slice, fs, cfg)
        rho = _peak_prominence(bp_slice, fs, cfg)
        q[idx] = eta * rho
        if q[idx] <= cfg.eps:
            continue

        seg = bp_slice - np.mean(bp_slice)
        if np.std(seg) < cfg.eps:
            continue
        x_full = np.fft.rfft(seg * hann, n=nfft)
        x_fft[idx] = x_full[band_mask]

    return x_fft, q, np.isfinite(q) & (q > cfg.eps)


def _combine_cross_spectrum(
    x_fft: np.ndarray,
    q: np.ndarray,
    valid: np.ndarray,
    xcfg: CrossSpectrumConfig,
    cfg: ChFusionConfig,
) -> Tuple[np.ndarray, dict]:
    """Merge tone-pair cross-spectra into a scalar spectrum."""
    band_bins = x_fft.shape[1]
    zero = np.zeros(band_bins, dtype=float)
    if not np.any(valid):
        return zero, {
            "cross_peak_significance": 0.0,
            "n_effective_pairs": 0,
            "mean_pair_weight": 0.0,
        }

    valid_idx = np.flatnonzero(valid)
    x_sub = x_fft[valid_idx]
    q_sub = q[valid_idx]
    n = len(valid_idx)

    pair_weights: List[float] = []
    pair_contribs: List[np.ndarray] = []

    for a in range(n):
        for b in range(a + 1, n):
            i_pos = valid_idx[a]
            j_pos = valid_idx[b]
            if xcfg.max_delta_k is not None and abs(i_pos - j_pos) > xcfg.max_delta_k:
                continue
            w_ij = q_sub[a] * q_sub[b]
            if w_ij <= cfg.eps:
                continue
            cross_ij = x_sub[a] * np.conj(x_sub[b])
            if xcfg.cross_mode == "magnitude":
                contrib = w_ij * np.abs(cross_ij)
            elif xcfg.cross_mode == "real":
                contrib = w_ij * np.maximum(0.0, np.real(cross_ij))
            else:
                contrib = w_ij * cross_ij
            pair_weights.append(w_ij)
            pair_contribs.append(contrib)

    if not pair_contribs:
        return zero, {
            "cross_peak_significance": 0.0,
            "n_effective_pairs": 0,
            "mean_pair_weight": 0.0,
        }

    w_arr = np.asarray(pair_weights, dtype=float)
    w_sum = float(np.sum(w_arr))
    if w_sum <= cfg.eps:
        return zero, {
            "cross_peak_significance": 0.0,
            "n_effective_pairs": 0,
            "mean_pair_weight": 0.0,
        }

    if xcfg.cross_mode == "coherent":
        stacked = np.vstack(pair_contribs)
        c_total = np.sum(stacked, axis=0) / w_sum
        fused = np.abs(c_total)
    else:
        stacked = np.vstack(pair_contribs)
        fused = np.sum(stacked, axis=0) / w_sum

    peak = float(np.max(fused))
    noise_floor = float(np.median(fused) + cfg.eps)
    return fused, {
        "cross_peak_significance": peak / noise_floor,
        "n_effective_pairs": len(pair_weights),
        "mean_pair_weight": float(np.mean(w_arr)),
    }


def per_modal_cross_spectrum(
    ch_list: Sequence[Any],
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    xcfg: CrossSpectrumConfig,
    nfft: int,
    band_mask: np.ndarray,
    band_freqs: np.ndarray,
    hann: np.ndarray,
) -> Tuple[np.ndarray, float, dict]:
    """Cross-spectrum combining for one modal variable."""
    x_fft, q, valid = _collect_tone_fft_data(
        ch_list, ch_map, variable, st, end, fs, cfg, nfft, band_mask, hann
    )
    fused, info = _combine_cross_spectrum(x_fft, q, valid, xcfg, cfg)
    bpm = _bpm_from_fused_spectrum(fused, band_freqs, cfg)
    mean_eta = 0.0
    if np.any(valid):
        eta_vals = []
        for idx, ch in enumerate(ch_list):
            if not valid[idx]:
                continue
            hp = ch_map[ch][variable]["highpass_filtered"]
            if len(hp) >= end:
                eta_vals.append(_energy_ratio(hp[st:end], fs, cfg))
        mean_eta = float(np.mean(eta_vals)) if eta_vals else 0.0

    info.update({"score": info["cross_peak_significance"], "mean_eta": mean_eta})
    return fused, bpm, info


def estimate_cross_spectrum_segment(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    *,
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    xcfg: CrossSpectrumConfig,
    method_key: str,
    verbose: bool = False,
) -> Optional[dict]:
    """Run cross-spectrum pipeline on one breath segment."""
    ref_seg = multichannel_by_var["phases"].get(seg_name)
    if ref_seg is None:
        return None
    metadata = ref_seg["metadata"]
    if metadata.get("segment_type") == "apnea":
        return None

    bpm_gt = metadata.get("bpm_gt")
    fs = metadata["sampling_rate"]

    seg_maps: Dict[str, Dict[Any, dict]] = {}
    ch_lists: Dict[str, List[Any]] = {}
    ref_len = 0
    for var in MODAL_VOTING_VARIABLES:
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
    diag_cross_sig: List[float] = []
    diag_n_pairs: List[int] = []

    for st in starts:
        end = st + win_len
        spectra_by_var: Dict[str, np.ndarray] = {}
        scores_by_var: Dict[str, float] = {}

        for var in MODAL_VOTING_VARIABLES:
            spec, _bpm, info = per_modal_cross_spectrum(
                ch_lists[var],
                seg_maps[var],
                var,
                st,
                end,
                fs,
                cfg,
                xcfg,
                nfft,
                band_mask,
                band_freqs,
                hann,
            )
            short = VAR_SHORT[var]
            spectra_by_var[short] = spec
            scores_by_var[short] = info["score"]
            if var == "remote_amplitudes":
                diag_cross_sig.append(info.get("cross_peak_significance", 0.0))
                diag_n_pairs.append(info.get("n_effective_pairs", 0))

        bpm, _selected = modal_fusion_from_spectra(
            spectra_by_var, scores_by_var, "equal", band_freqs, cfg
        )
        bpms.append(bpm)

    return {
        "segment": seg_name,
        "bpm_gt": bpm_gt,
        "metadata": metadata,
        method_key: {
            **_seg_bpm_stats(np.asarray(bpms), bpm_gt, len(starts)),
            "cross_peak_significance_remote": diag_cross_sig,
            "n_effective_pairs_remote": diag_n_pairs,
        },
    }


def _estimate_x0_baseline_segment(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    *,
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    vcfg: VotingConfig,
) -> Optional[dict]:
    """X0 = B1 Vote→Equal (power spectrum baseline)."""
    ref_seg = multichannel_by_var["phases"].get(seg_name)
    if ref_seg is None:
        return None
    metadata = ref_seg["metadata"]
    if metadata.get("segment_type") == "apnea":
        return None

    bpm_gt = metadata.get("bpm_gt")
    fs = metadata["sampling_rate"]
    method_key = X0_BASELINE_SPEC[1]

    seg_maps: Dict[str, Dict[Any, dict]] = {}
    ch_lists: Dict[str, List[Any]] = {}
    ref_len = 0
    for var in MODAL_VOTING_VARIABLES:
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
    for st in starts:
        end = st + win_len
        spectra_by_var: Dict[str, np.ndarray] = {}
        scores_by_var: Dict[str, float] = {}
        for var in MODAL_VOTING_VARIABLES:
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
            short = VAR_SHORT[var]
            spectra_by_var[short] = spec
            scores_by_var[short] = info["score"]
        bpm, _sel = modal_fusion_from_spectra(
            spectra_by_var, scores_by_var, "equal", band_freqs, cfg
        )
        bpms.append(bpm)

    return {
        "segment": seg_name,
        "bpm_gt": bpm_gt,
        "metadata": metadata,
        method_key: _seg_bpm_stats(np.asarray(bpms), bpm_gt, len(starts)),
    }


def _run_cross_spectrum_methods(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    vcfg: VotingConfig,
    run_x0: bool = True,
    verbose: bool = True,
) -> Dict[str, Optional[dict]]:
    merged: Dict[str, Optional[dict]] = {}
    seg_names = sorted(multichannel_by_var["phases"].keys())

    if run_x0:
        if verbose:
            print("\n--- X0 B1 Vote→Equal (power spectrum baseline) ---")
        for seg_name in seg_names:
            row = _estimate_x0_baseline_segment(
                multichannel_by_var,
                seg_name,
                config=config,
                metric_params=metric_params,
                vcfg=vcfg,
            )
            if row is None:
                merged.setdefault(seg_name, None)
                continue
            if merged.get(seg_name) is None:
                merged[seg_name] = {
                    "segment": seg_name,
                    "bpm_gt": row["bpm_gt"],
                    "metadata": row["metadata"],
                }
            merged[seg_name][X0_BASELINE_SPEC[1]] = row[X0_BASELINE_SPEC[1]]
        if verbose:
            stats = _overall_rel_error(merged, X0_BASELINE_SPEC[1])
            print(
                f"✓ [{X0_BASELINE_SPEC[1]}] mean err {stats['mean_rel_err_pct']:.2f}% "
                f"± {stats['std_rel_err_pct']:.2f}%"
            )

    for label, method_key, _color, mode, max_dk in CROSS_SPECTRUM_METHOD_SPECS:
        xcfg = CrossSpectrumConfig(cross_mode=mode, max_delta_k=max_dk)
        if verbose:
            print(f"\n--- {label} ---")
        partial: Dict[str, Optional[dict]] = {}
        for seg_name in seg_names:
            row = estimate_cross_spectrum_segment(
                multichannel_by_var,
                seg_name,
                config=config,
                metric_params=metric_params,
                xcfg=xcfg,
                method_key=method_key,
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


def import_reference_baselines(
    merged: Dict[str, Optional[dict]],
    results_by_scenario: Optional[Dict[str, dict]],
    scenario_id: str,
) -> None:
    """Attach reference baselines from prior systematic_fusion results."""
    if not results_by_scenario or scenario_id not in results_by_scenario:
        return
    src_results = results_by_scenario[scenario_id].get("results", {})
    for _label, key, _color, _src in REFERENCE_BASELINE_SPECS:
        for seg_name, src_row in src_results.items():
            if src_row is None:
                continue
            block = src_row.get(key)
            if block is None:
                continue
            if merged.get(seg_name) is None:
                merged[seg_name] = {
                    "segment": seg_name,
                    "bpm_gt": src_row.get("bpm_gt"),
                    "metadata": src_row.get("metadata"),
                }
            merged[seg_name][key] = block


def import_x0_from_systematic(
    merged: Dict[str, Optional[dict]],
    results_by_scenario: Optional[Dict[str, dict]],
    scenario_id: str,
) -> bool:
    """Try to import X0 from b1_vote_modal_equal in systematic fusion results."""
    if not results_by_scenario or scenario_id not in results_by_scenario:
        return False
    src_results = results_by_scenario[scenario_id].get("results", {})
    src_key = "b1_vote_modal_equal"
    dst_key = X0_BASELINE_SPEC[1]
    found = False
    for seg_name, src_row in src_results.items():
        if src_row is None:
            continue
        block = src_row.get(src_key)
        if block is None:
            continue
        found = True
        if merged.get(seg_name) is None:
            merged[seg_name] = {
                "segment": seg_name,
                "bpm_gt": src_row.get("bpm_gt"),
                "metadata": src_row.get("metadata"),
            }
        merged[seg_name][dst_key] = block
    return found


def run_cross_spectrum_benchmark(
    frames,
    segment_config: dict,
    *,
    filter_params: Optional[FilterParams] = None,
    metric_params: Optional[BreathMetricParams] = None,
    config: Optional[ChFusionConfig] = None,
    verbose: bool = True,
    cache_dir: Optional[str] = None,
    multichannel_by_var: Optional[Dict[str, Dict[str, Optional[dict]]]] = None,
    systematic_results: Optional[Dict[str, dict]] = None,
    scenario_id: str = "",
) -> dict:
    """Full cross-spectrum benchmark across all segments and methods."""
    cfg = config or ChFusionConfig()
    fp = filter_params or FilterParams()
    mp = metric_params or BreathMetricParams()
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

    run_x0 = True
    imported_x0: Dict[str, Optional[dict]] = {}
    if systematic_results and scenario_id:
        if import_x0_from_systematic(imported_x0, systematic_results, scenario_id):
            run_x0 = False
            if verbose:
                print(f"Imported X0 baseline from systematic_fusion ({scenario_id})")

    merged = _run_cross_spectrum_methods(
        multichannel_by_var,
        config=cfg,
        metric_params=mp,
        vcfg=vcfg,
        run_x0=run_x0,
        verbose=verbose,
    )

    if not run_x0 and imported_x0:
        for seg_name, block in imported_x0.items():
            if block is None:
                continue
            x0 = block.get(X0_BASELINE_SPEC[1])
            if x0 is None:
                continue
            if merged.get(seg_name) is None:
                merged[seg_name] = block
            else:
                merged[seg_name][X0_BASELINE_SPEC[1]] = x0

    import_reference_baselines(merged, systematic_results, scenario_id)

    return {
        "results": merged,
        "multichannel_by_var": multichannel_by_var,
        "segment_config": segment_config,
        "scenario_id": scenario_id,
    }


def _all_method_specs_for_leaderboard() -> Tuple[Tuple[str, str, str], ...]:
    return (
        (X0_BASELINE_SPEC[0], X0_BASELINE_SPEC[1], X0_BASELINE_SPEC[2]),
        *[(label, key, color) for label, key, color, _m, _d in CROSS_SPECTRUM_METHOD_SPECS],
        *[(label, key, color) for label, key, color, _src in REFERENCE_BASELINE_SPECS],
    )


def build_cross_spectrum_leaderboard_rows(benchmark: dict) -> List[dict]:
    results = benchmark["results"]
    rows: List[dict] = []
    for label, key, color in _all_method_specs_for_leaderboard():
        stats = _overall_rel_error(results, key)
        if not np.isfinite(stats["mean_rel_err_pct"]):
            continue
        rows.append({"label": label, "method_key": key, "color": color, **stats})
    rows.sort(key=lambda r: r["mean_rel_err_pct"])
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def compute_cross_spectrum_cross_domain(
    results_by_scenario: Dict[str, dict],
) -> List[dict]:
    agg: List[dict] = []
    for label, key, color in _all_method_specs_for_leaderboard():
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


def plot_cross_spectrum_figures(
    results_by_scenario: Dict[str, dict],
    cross_domain: List[dict],
    *,
    figures_dir,
    scenario_ids: Sequence[str],
    multichannel_by_var: Optional[Dict[str, Dict[str, Optional[dict]]]] = None,
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    show: bool = False,
    save: bool = True,
) -> dict:
    """Generate leaderboard, vs power spectrum, pair spacing scan, aggregate bars."""
    import matplotlib.pyplot as plt
    from pathlib import Path

    figures_dir = Path(figures_dir)
    paths: dict = {}
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()

    # --- Leaderboard (X0–X7 only) ---
    x_methods = [X0_BASELINE_SPEC] + list(CROSS_SPECTRUM_METHOD_SPECS)
    x_keys = {spec[1] for spec in x_methods}
    x_rows = [r for r in cross_domain if r["method_key"] in x_keys]
    x_rows.sort(key=lambda r: r["cross_domain_mean"])

    fig, ax = plt.subplots(figsize=(12, 7))
    labels = [r["label"] for r in x_rows]
    means = [r["cross_domain_mean"] for r in x_rows]
    colors = [r["color"] for r in x_rows]
    y_pos = np.arange(len(labels))
    ax.barh(y_pos, means, color=colors, alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Cross-domain mean BPM err %")
    ax.set_title("Cross-spectrum combining — X0–X7 leaderboard")
    ax.axvline(x=8.45, color="gray", linestyle="--", alpha=0.6, label="B1 ref 8.45%")
    ax.legend()
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    lb_path = figures_dir / "cross_spectrum_leaderboard.png"
    if save:
        fig.savefig(lb_path, dpi=150, bbox_inches="tight")
    paths["leaderboard"] = lb_path
    if not show:
        plt.close(fig)

    # --- Cross-domain aggregate bars (all methods incl. references) ---
    fig, ax = plt.subplots(figsize=(14, 8))
    labels_all = [r["label"] for r in cross_domain]
    means_all = [r["cross_domain_mean"] for r in cross_domain]
    colors_all = [r["color"] for r in cross_domain]
    y_pos = np.arange(len(labels_all))
    ax.barh(y_pos, means_all, color=colors_all, alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels_all, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Cross-domain mean BPM err %")
    ax.set_title("Cross-spectrum — full cross-domain aggregate")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    agg_path = figures_dir / "cross_spectrum_cross_domain_aggregate_bars.png"
    if save:
        fig.savefig(agg_path, dpi=150, bbox_inches="tight")
    paths["aggregate_bars"] = agg_path
    if not show:
        plt.close(fig)

    # --- Pair spacing scan ---
    spacing_keys = [
        ("x1_cross_mag_all", "all", "magnitude"),
        ("x4_cross_mag_d1", "d1", "magnitude"),
        ("x6_cross_mag_d5", "d5", "magnitude"),
        ("x2_cross_real_all", "all", "real"),
        ("x5_cross_real_d1", "d1", "real"),
        ("x7_cross_real_d5", "d5", "real"),
    ]
    spacing_labels = []
    spacing_vals = []
    for key, spacing, mode in spacing_keys:
        row = next((r for r in cross_domain if r["method_key"] == key), None)
        if row is None:
            continue
        spacing_labels.append(f"{mode}\nΔk={spacing}")
        spacing_vals.append(row["cross_domain_mean"])

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(spacing_labels))
    ax.bar(x, spacing_vals, color=["teal", "olive", "seagreen", "darkcyan", "darkolivegreen", "forestgreen"][: len(spacing_vals)], alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(spacing_labels)
    ax.set_ylabel("Cross-domain mean BPM err %")
    ax.set_title("Tone-pair spacing scan (X1/X4/X6, X2/X5/X7)")
    x0_val = next((r["cross_domain_mean"] for r in cross_domain if r["method_key"] == X0_BASELINE_SPEC[1]), np.nan)
    if np.isfinite(x0_val):
        ax.axhline(y=x0_val, color="steelblue", linestyle="--", label=f"X0 power spec {x0_val:.2f}%")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    scan_path = figures_dir / "cross_spectrum_pair_spacing_scan.png"
    if save:
        fig.savefig(scan_path, dpi=150, bbox_inches="tight")
    paths["pair_spacing_scan"] = scan_path
    if not show:
        plt.close(fig)

    # --- Cross vs power spectrum example ---
    if multichannel_by_var is not None and scenario_ids:
        _plot_spectrum_comparison(
            multichannel_by_var,
            cfg,
            mp,
            figures_dir,
            paths,
            show,
            save,
        )

    return paths


def _plot_spectrum_comparison(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    cfg: ChFusionConfig,
    mp: BreathMetricParams,
    figures_dir,
    paths: dict,
    show: bool,
    save: bool,
) -> None:
    import matplotlib.pyplot as plt

    seg_names = [
        s
        for s, row in multichannel_by_var["phases"].items()
        if row is not None and row["metadata"].get("segment_type") != "apnea"
    ]
    if not seg_names:
        return
    seg_name = seg_names[0]
    ref_seg = multichannel_by_var["phases"][seg_name]
    fs = ref_seg["metadata"]["sampling_rate"]
    var = "remote_amplitudes"
    seg = multichannel_by_var[var][seg_name]
    ch_list = sorted(seg["channels"].keys(), key=lambda c: (isinstance(c, str), str(c)))
    ch_map = seg["channels"]

    ref_len = max(len(c[var]["bandpass_filtered"]) for c in ch_map.values())
    win_len = int(round(mp.window_length_sec * fs))
    step_len = int(round(mp.step_length_sec * fs))
    nfft = cfg.nfft or _next_pow2(4 * win_len)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
    band_freqs = freqs[band_mask]
    hann = np.hanning(win_len)
    starts = _sliding_window_indices(ref_len, win_len, step_len)
    if not starts:
        return

    vcfg = VotingConfig(voting_strategy="eta_rho_weighted")
    xcfg = CrossSpectrumConfig(cross_mode="magnitude", max_delta_k=None)
    pick_windows = [starts[len(starts) // 4], starts[len(starts) // 2], starts[3 * len(starts) // 4]]

    fig, axes = plt.subplots(len(pick_windows), 2, figsize=(12, 3.5 * len(pick_windows)), squeeze=False)
    for wi, st in enumerate(pick_windows):
        end = st + win_len
        p_power, _, _ = per_modal_voting_spectrum(
            ch_list, ch_map, var, st, end, fs, cfg, vcfg, nfft, band_mask, band_freqs, hann
        )
        p_cross, _, info = per_modal_cross_spectrum(
            ch_list, ch_map, var, st, end, fs, cfg, xcfg, nfft, band_mask, band_freqs, hann
        )
        for col, (spec, title) in enumerate(
            [(p_power, "Power spectrum (X0/B1)"), (p_cross, f"Cross-spectrum mag (pairs={info['n_effective_pairs']})")]
        ):
            ax = axes[wi, col]
            ax.plot(band_freqs * 60, spec, "k-", lw=1.2)
            ax.set_xlabel("BPM")
            ax.set_ylabel("Normalized amplitude")
            ax.set_title(f"Window {wi + 1} — {title}")
            ax.grid(True, alpha=0.3)

    fig.suptitle(f"Cross-spectrum vs power spectrum ({seg_name}, remote)", fontsize=12)
    fig.tight_layout()
    cmp_path = figures_dir / "cross_spectrum_vs_power_spectrum.png"
    if save:
        fig.savefig(cmp_path, dpi=150, bbox_inches="tight")
    paths["vs_power_spectrum"] = cmp_path
    if not show:
        plt.close(fig)
