"""Cross-spectrum failure mechanism diagnosis (D1–D4).

Implements ``docs/plans/cross_spectrum_failure_diagnosis_plan.md``.
Uses existing ``outputs/reports/cross_spectrum_results.npy`` — no new benchmark.

Run: ``python notebooks/scripts/chFusion_cross_spectrum_diagnosis.py``
"""

# %%
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np

_cwd = Path.cwd().resolve()
project_root = next(
    (p for p in [_cwd, *_cwd.parents] if (p / "src").is_dir()),
    None,
)
if project_root is None:
    raise FileNotFoundError("Project root not found (missing src/ directory)")

_src = project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from ble_analysis.bootstrap import init_notebook

_env = init_notebook(project_root)
project_root = _env["project_root"]
FIGURES_DIR = _env["FIGURES_DIR"]
REPORTS_DIR = _env["REPORTS_DIR"]

# %%
from ble_analysis.chfusion import ChFusionConfig, _next_pow2
from ble_analysis.cross_spectrum import (
    CrossSpectrumConfig,
    X0_BASELINE_SPEC,
    _collect_tone_fft_data,
    per_modal_cross_spectrum,
)
from ble_analysis.segments import BreathMetricParams, _sliding_window_indices
from ble_analysis.systematic_fusion import (
    MODAL_VOTING_VARIABLES,
    VAR_SHORT,
    modal_fusion_from_spectra,
    per_modal_voting_spectrum,
)
from ble_analysis.voting_fusion import VotingConfig

SCENARIO_IDS = ("cs_091339", "cs_095806", "cs_102621")
X0_KEY = X0_BASELINE_SPEC[1]
X3_KEY = "x3_cross_coh_all"
X3_XCFG = CrossSpectrumConfig(cross_mode="coherent", max_delta_k=None)

filter_params = BreathMetricParams()
metric_params = BreathMetricParams()
chfusion_config = ChFusionConfig(
    breath_freq_low=metric_params.breath_freq_low,
    breath_freq_high=metric_params.breath_freq_high,
    window_length_sec=metric_params.window_length_sec,
    step_length_sec=metric_params.step_length_sec,
    enable_consensus=False,
)
vcfg = VotingConfig(voting_strategy="eta_rho_weighted")


def _peak_significance(spectrum: np.ndarray, eps: float) -> float:
    peak = float(np.max(spectrum))
    noise_floor = float(np.median(spectrum) + eps)
    return peak / noise_floor if noise_floor > 0 else 0.0


def _window_rel_err(bpm: float, bpm_gt: float) -> float:
    if not bpm_gt or not np.isfinite(bpm):
        return np.nan
    return abs(bpm - bpm_gt) / bpm_gt


def _segment_window_setup(
    multichannel_by_var: dict,
    seg_name: str,
) -> Optional[Tuple[float, float, int, int, int, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict, dict]]:
    ref_seg = multichannel_by_var["phases"].get(seg_name)
    if ref_seg is None:
        return None
    metadata = ref_seg["metadata"]
    if metadata.get("segment_type") == "apnea":
        return None
    bpm_gt = metadata.get("bpm_gt")
    if not bpm_gt:
        return None

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

    cfg = chfusion_config
    nfft = cfg.nfft or _next_pow2(4 * win_len)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
    band_freqs = freqs[band_mask]
    hann = np.hanning(win_len)
    starts = _sliding_window_indices(ref_len, win_len, step_len)
    return bpm_gt, fs, win_len, step_len, nfft, band_mask, band_freqs, hann, starts, seg_maps, ch_lists


def _compute_x0_peak_sig(
    seg_maps: dict,
    ch_lists: dict,
    st: int,
    end: int,
    fs: float,
    nfft: int,
    band_mask: np.ndarray,
    band_freqs: np.ndarray,
    hann: np.ndarray,
) -> float:
    cfg = chfusion_config
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
        spectra_by_var[VAR_SHORT[var]] = spec
        scores_by_var[VAR_SHORT[var]] = info["score"]
    fused = np.sum(
        np.vstack([spectra_by_var[k] for k in spectra_by_var]) / len(spectra_by_var),
        axis=0,
    )
    return _peak_significance(fused, cfg.eps)


def collect_d1_d2_records(bench: dict) -> List[dict]:
    records: List[dict] = []
    results = bench["results"]
    mc = bench["multichannel_by_var"]

    for seg_name, row in results.items():
        if row is None:
            continue
        setup = _segment_window_setup(mc, seg_name)
        if setup is None:
            continue
        bpm_gt, fs, win_len, _step, nfft, band_mask, band_freqs, hann, starts, seg_maps, ch_lists = setup
        x0 = row.get(X0_KEY)
        x3 = row.get(X3_KEY)
        if not x0 or not x3:
            continue

        bpms_x0 = np.asarray(x0["bpm_per_window"], dtype=float)
        bpms_x3 = np.asarray(x3["bpm_per_window"], dtype=float)
        sig_x3 = np.asarray(x3.get("cross_peak_significance_remote", []), dtype=float)
        n_pairs = np.asarray(x3.get("n_effective_pairs_remote", []), dtype=float)
        n_win = min(len(bpms_x0), len(bpms_x3), len(starts))

        for wi in range(n_win):
            st = int(starts[wi])
            end = st + win_len
            sig_x0 = _compute_x0_peak_sig(
                seg_maps, ch_lists, st, end, fs, nfft, band_mask, band_freqs, hann
            )
            err_x0 = _window_rel_err(bpms_x0[wi], bpm_gt)
            err_x3 = _window_rel_err(bpms_x3[wi], bpm_gt)
            records.append(
                {
                    "segment": seg_name,
                    "window_idx": wi,
                    "start": st,
                    "bpm_gt": bpm_gt,
                    "bpm_x0": float(bpms_x0[wi]),
                    "bpm_x3": float(bpms_x3[wi]),
                    "err_x0": err_x0,
                    "err_x3": err_x3,
                    "peak_sig_x0": sig_x0,
                    "peak_sig_x3": float(sig_x3[wi]) if wi < len(sig_x3) else np.nan,
                    "n_effective_pairs": int(n_pairs[wi]) if wi < len(n_pairs) else 0,
                }
            )
    return records


def pick_window_by_criterion(
    records: List[dict],
    criterion: str,
) -> Optional[dict]:
    finite = [r for r in records if np.isfinite(r["err_x0"]) and np.isfinite(r["err_x3"])]
    if not finite:
        return None
    if criterion == "x0_best":
        return min(finite, key=lambda r: r["err_x0"])
    if criterion == "x3_worst":
        return max(finite, key=lambda r: r["err_x3"])
    if criterion == "both_bad":
        return max(finite, key=lambda r: r["err_x0"] + r["err_x3"])
    if criterion == "both_good":
        return min(finite, key=lambda r: r["err_x0"] + r["err_x3"])
    if criterion == "x0_good_x3_bad":
        candidates = [r for r in finite if r["err_x0"] < 0.05 and r["err_x3"] > 0.15]
        if candidates:
            return max(candidates, key=lambda r: r["err_x3"] - r["err_x0"])
        return max(finite, key=lambda r: r["err_x3"] - r["err_x0"])
    if criterion == "both_bad_d4":
        return max(finite, key=lambda r: min(r["err_x0"], r["err_x3"]))
    return None


def compute_cos_diagnostics(
    mc: dict,
    record: dict,
) -> dict:
    setup = _segment_window_setup(mc, record["segment"])
    if setup is None:
        return {}
    bpm_gt, fs, win_len, _step, nfft, band_mask, band_freqs, hann, _starts, _seg_maps, _ch_lists = setup
    var = "remote_amplitudes"
    seg = mc[var][record["segment"]]
    ch_list = sorted(seg["channels"].keys(), key=lambda c: (isinstance(c, str), str(c)))
    ch_map = seg["channels"]
    st = record["start"]
    end = st + win_len

    x_fft, q, valid = _collect_tone_fft_data(
        ch_list, ch_map, var, st, end, fs, chfusion_config, nfft, band_mask, hann
    )
    gt_hz = bpm_gt / 60.0
    k_breath = int(np.argmin(np.abs(band_freqs - gt_hz)))

    x_peak = x_fft[:, k_breath]
    cross = np.outer(x_peak, np.conj(x_peak))
    cos_mat = np.real(cross) / (np.abs(cross) + chfusion_config.eps)

    cos_vals = cos_mat[np.triu_indices(len(ch_list), k=1)]
    neg_frac = float(np.mean(cos_vals < 0)) if cos_vals.size else np.nan

    delta_ks: List[int] = []
    cos_pairs: List[float] = []
    for i in range(len(ch_list)):
        for j in range(i + 1, len(ch_list)):
            delta_ks.append(abs(int(ch_list[i]) - int(ch_list[j])))
            cos_pairs.append(float(cos_mat[i, j]))

    delta_ks_arr = np.asarray(delta_ks)
    cos_pairs_arr = np.asarray(cos_pairs)
    max_dk = int(np.max(delta_ks_arr)) if delta_ks_arr.size else 0
    mean_cos_by_dk = []
    for dk in range(max_dk + 1):
        mask = delta_ks_arr == dk
        mean_cos_by_dk.append(float(np.mean(cos_pairs_arr[mask])) if np.any(mask) else np.nan)

    return {
        "cos_mat": cos_mat,
        "ch_list": ch_list,
        "cos_vals": cos_vals,
        "neg_frac": neg_frac,
        "mean_cos": float(np.mean(cos_vals)) if cos_vals.size else np.nan,
        "mean_cos_dk1": mean_cos_by_dk[1] if len(mean_cos_by_dk) > 1 else np.nan,
        "delta_ks": list(range(max_dk + 1)),
        "mean_cos_by_dk": mean_cos_by_dk,
        "k_breath": k_breath,
        "gt_hz": gt_hz,
        "band_freqs": band_freqs,
    }


def get_window_spectra(
    mc: dict,
    record: dict,
) -> Tuple[np.ndarray, np.ndarray, float, float, dict]:
    setup = _segment_window_setup(mc, record["segment"])
    if setup is None:
        raise ValueError("segment setup failed")
    _bpm_gt, fs, win_len, _step, nfft, band_mask, band_freqs, hann, _starts, seg_maps, ch_lists = setup
    st = record["start"]
    end = st + win_len
    cfg = chfusion_config

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
        spectra_by_var[VAR_SHORT[var]] = spec
        scores_by_var[VAR_SHORT[var]] = info["score"]
    fused_x0 = np.sum(
        np.vstack([spectra_by_var[k] for k in spectra_by_var]) / len(spectra_by_var),
        axis=0,
    )
    spec_x3, _, info_x3 = per_modal_cross_spectrum(
        ch_lists["remote_amplitudes"],
        seg_maps["remote_amplitudes"],
        "remote_amplitudes",
        st,
        end,
        fs,
        cfg,
        X3_XCFG,
        nfft,
        band_mask,
        band_freqs,
        hann,
    )
    return (
        fused_x0,
        spec_x3,
        _peak_significance(fused_x0, cfg.eps),
        float(info_x3.get("cross_peak_significance", 0.0)),
        {"band_freqs": band_freqs, "n_pairs": info_x3.get("n_effective_pairs", 0)},
    )


# %%
results_path = REPORTS_DIR / "cross_spectrum_results.npy"
if not results_path.exists():
    raise FileNotFoundError(f"Missing {results_path} — run chFusion_cross_spectrum.py first")

all_results = np.load(results_path, allow_pickle=True).item()
records_by_scenario: Dict[str, List[dict]] = {}
for sid in SCENARIO_IDS:
    print(f"\nCollecting D1/D2 records for {sid}...")
    records_by_scenario[sid] = collect_d1_d2_records(all_results[sid])
    print(f"  {len(records_by_scenario[sid])} windows")

# %%
# D1 scatter + histogram
fig, ax = plt.subplots(figsize=(7, 6))
colors = {"cs_091339": "crimson", "cs_095806": "steelblue", "cs_102621": "seagreen"}
for sid in SCENARIO_IDS:
    recs = records_by_scenario[sid]
    ax.scatter(
        [r["peak_sig_x0"] for r in recs],
        [r["peak_sig_x3"] for r in recs],
        s=12,
        alpha=0.45,
        c=colors[sid],
        label=sid,
    )
lims = ax.get_xlim()
ax.plot(lims, lims, "k--", lw=0.8, alpha=0.5, label="y=x")
ax.set_xlabel("X0 power peak significance")
ax.set_ylabel("X3 cross peak significance")
ax.set_title("D1: Peak significance per window (X0 vs X3)")
ax.legend(loc="upper left", fontsize=8)
ax.grid(True, alpha=0.3)
fig.tight_layout()
scatter_path = FIGURES_DIR / "cross_spectrum_diag_peak_sig_scatter.png"
fig.savefig(scatter_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Saved {scatter_path}")

fig, axes = plt.subplots(1, 3, figsize=(12, 3.5), sharey=True)
for ax, sid in zip(axes, SCENARIO_IDS):
    recs = records_by_scenario[sid]
    x0_vals = [r["peak_sig_x0"] for r in recs]
    x3_vals = [r["peak_sig_x3"] for r in recs]
    bins = np.linspace(
        0,
        max(max(x0_vals), max(x3_vals), 1.0) * 1.05,
        25,
    )
    ax.hist(x0_vals, bins=bins, alpha=0.55, label="X0 power", color="steelblue")
    ax.hist(x3_vals, bins=bins, alpha=0.55, label="X3 cross", color="coral")
    ax.set_title(sid[-6:])
    ax.set_xlabel("Peak significance")
    ax.legend(fontsize=7)
axes[0].set_ylabel("Window count")
fig.suptitle("D1: Peak significance distributions", y=1.02)
fig.tight_layout()
hist_path = FIGURES_DIR / "cross_spectrum_diag_peak_sig_hist.png"
fig.savefig(hist_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Saved {hist_path}")

# %%
# D2 boxplot
fig, ax = plt.subplots(figsize=(7, 4))
data = [[r["n_effective_pairs"] for r in records_by_scenario[sid]] for sid in SCENARIO_IDS]
bp = ax.boxplot(data, tick_labels=[s[-6:] for s in SCENARIO_IDS], patch_artist=True)
for patch, c in zip(bp["boxes"], colors.values()):
    patch.set_facecolor(c)
    patch.set_alpha(0.45)
ax.axhline(2556, color="gray", ls="--", lw=0.8, label="C(72,2)=2556")
ax.axhline(71, color="orange", ls=":", lw=0.8, label="Δk≤1 max ≈71")
ax.set_ylabel("n_effective_pairs (X3 remote)")
ax.set_title("D2: Effective tone-pair count per window")
ax.legend(fontsize=8)
ax.grid(True, axis="y", alpha=0.3)
fig.tight_layout()
box_path = FIGURES_DIR / "cross_spectrum_diag_n_pairs_box.png"
fig.savefig(box_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Saved {box_path}")

# %%
# D3 cos matrix (cs_091339 only)
d3_criteria = [
    ("x0_best", "A: X0 best"),
    ("x3_worst", "B: X3 worst"),
    ("both_bad", "C: both bad"),
]
mc_091339 = all_results["cs_091339"]["multichannel_by_var"]
recs_091339 = records_by_scenario["cs_091339"]
d3_results = []
fig, axes = plt.subplots(1, 3, figsize=(14, 4.2))
for ax, (crit, title) in zip(axes, d3_criteria):
    rec = pick_window_by_criterion(recs_091339, crit)
    if rec is None:
        ax.set_visible(False)
        continue
    diag = compute_cos_diagnostics(mc_091339, rec)
    d3_results.append({"criterion": crit, "record": rec, **diag})
    im = ax.imshow(diag["cos_mat"], cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_title(f"{title}\nneg={diag['neg_frac']:.0%}, mean={diag['mean_cos']:.2f}")
    ax.set_xlabel("tone j")
    ax.set_ylabel("tone i")
fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.8, label="cos(φᵢ−φⱼ)")
fig.suptitle("D3: Phase coherence at GT breath bin (cs_091339, remote)", y=1.02)
fig.tight_layout()
cos_mat_path = FIGURES_DIR / "cross_spectrum_diag_cos_matrix.png"
fig.savefig(cos_mat_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Saved {cos_mat_path}")

fig, ax = plt.subplots(figsize=(7, 4))
for item in d3_results:
    ax.plot(
        item["delta_ks"],
        item["mean_cos_by_dk"],
        "o-",
        label=f"{item['criterion']} (neg={item['neg_frac']:.0%})",
    )
ax.axhline(0, color="k", lw=0.6)
ax.set_xlabel("|tone_i − tone_j| (Δk)")
ax.set_ylabel("Mean cos(φᵢ−φⱼ)")
ax.set_title("D3: Coherence vs tone spacing (cs_091339)")
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)
fig.tight_layout()
cos_dk_path = FIGURES_DIR / "cross_spectrum_diag_cos_vs_delta_k.png"
fig.savefig(cos_dk_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Saved {cos_dk_path}")

# %%
# D4 spectrum shape (cs_091339 + cs_095806)
d4_scenarios = ("cs_091339", "cs_095806")
d4_criteria = [
    ("both_good", "both ≈ GT"),
    ("x0_good_x3_bad", "X0 ok, X3 bad"),
    ("both_bad_d4", "both bad"),
]
fig, axes = plt.subplots(6, 2, figsize=(11, 16), squeeze=False)
row_idx = 0
d4_picks = []
for sid in d4_scenarios:
    mc = all_results[sid]["multichannel_by_var"]
    recs = records_by_scenario[sid]
    for crit, crit_label in d4_criteria:
        rec = pick_window_by_criterion(recs, crit)
        if rec is None:
            row_idx += 1
            continue
        spec_x0, spec_x3, ps_x0, ps_x3, meta = get_window_spectra(mc, rec)
        band_freqs = meta["band_freqs"]
        bpm_gt = rec["bpm_gt"]
        gt_bpm_axis = bpm_gt
        d4_picks.append({"scenario": sid, "criterion": crit, "record": rec, "ps_x0": ps_x0, "ps_x3": ps_x3})

        for col, (spec, ps, label, bpm_est) in enumerate(
            [
                (spec_x0, ps_x0, "X0 power", rec["bpm_x0"]),
                (spec_x3, ps_x3, "X3 cross", rec["bpm_x3"]),
            ]
        ):
            ax = axes[row_idx, col]
            ax.plot(band_freqs * 60, spec, "k-", lw=1.1)
            peak_idx = int(np.argmax(spec))
            ax.axvline(band_freqs[peak_idx] * 60, color="red", ls="--", lw=0.9, label=f"argmax {band_freqs[peak_idx]*60:.1f}")
            ax.axvline(gt_bpm_axis, color="green", ls="-", lw=0.9, alpha=0.8, label=f"GT {gt_bpm_axis:.1f}")
            ax.set_title(
                f"{sid[-6:]} {crit_label} | {label}\n"
                f"peak_sig={ps:.2f}, est={bpm_est:.1f}, err={_window_rel_err(bpm_est, bpm_gt)*100:.1f}%",
                fontsize=8,
            )
            ax.set_xlabel("BPM")
            ax.legend(fontsize=6, loc="upper right")
            ax.grid(True, alpha=0.3)
        row_idx += 1

fig.suptitle("D4: Power vs cross spectrum shape (representative windows)", y=1.01)
fig.tight_layout()
shape_path = FIGURES_DIR / "cross_spectrum_diag_spectrum_shape.png"
fig.savefig(shape_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Saved {shape_path}")

# %%
# Aggregate diagnostic stats for report
def _summarize_d1(recs: List[dict]) -> dict:
    x0s = np.asarray([r["peak_sig_x0"] for r in recs], dtype=float)
    x3s = np.asarray([r["peak_sig_x3"] for r in recs], dtype=float)
    err_x0 = np.asarray([r["err_x0"] for r in recs], dtype=float)
    err_x3 = np.asarray([r["err_x3"] for r in recs], dtype=float)
    high_sig_bad = [
        r
        for r in recs
        if r["peak_sig_x3"] > r["peak_sig_x0"] and r["err_x3"] > r["err_x0"]
    ]
    return {
        "median_peak_sig_x0": float(np.median(x0s)),
        "median_peak_sig_x3": float(np.median(x3s)),
        "mean_peak_sig_x0": float(np.mean(x0s)),
        "mean_peak_sig_x3": float(np.mean(x3s)),
        "frac_x3_higher_peak_sig": float(np.mean(x3s > x0s)),
        "frac_high_sig_x3_worse_bpm": len(high_sig_bad) / max(len(recs), 1),
        "median_err_x0": float(np.nanmedian(err_x0)),
        "median_err_x3": float(np.nanmedian(err_x3)),
    }


diag_summary = {
    "d1_by_scenario": {sid: _summarize_d1(records_by_scenario[sid]) for sid in SCENARIO_IDS},
    "d2_median_n_pairs": {
        sid: float(np.median([r["n_effective_pairs"] for r in records_by_scenario[sid]]))
        for sid in SCENARIO_IDS
    },
    "d3": [
        {
            "criterion": item["criterion"],
            "neg_frac": item["neg_frac"],
            "mean_cos": item["mean_cos"],
            "mean_cos_dk1": item["mean_cos_dk1"],
            "segment": item["record"]["segment"],
            "err_x0": item["record"]["err_x0"],
            "err_x3": item["record"]["err_x3"],
        }
        for item in d3_results
    ],
}
np.save(REPORTS_DIR / "cross_spectrum_failure_diagnosis_summary.npy", diag_summary, allow_pickle=True)
print(f"\nSaved summary: {REPORTS_DIR / 'cross_spectrum_failure_diagnosis_summary.npy'}")
print("\n=== D1 summary ===")
for sid in SCENARIO_IDS:
    s = diag_summary["d1_by_scenario"][sid]
    print(
        f"  {sid}: median peak_sig X0={s['median_peak_sig_x0']:.2f}, X3={s['median_peak_sig_x3']:.2f}, "
        f"X3>X0 in {s['frac_x3_higher_peak_sig']:.0%} windows, "
        f"high-sig-but-worse BPM={s['frac_high_sig_x3_worse_bpm']:.0%}"
    )
print("\n=== D2 median n_effective_pairs ===")
for sid in SCENARIO_IDS:
    print(f"  {sid}: {diag_summary['d2_median_n_pairs'][sid]:.0f}")
print("\n=== D3 (cs_091339) ===")
for item in diag_summary["d3"]:
    print(
        f"  {item['criterion']}: neg_frac={item['neg_frac']:.0%}, mean_cos={item['mean_cos']:.3f}, "
        f"dk1={item['mean_cos_dk1']:.3f}"
    )
