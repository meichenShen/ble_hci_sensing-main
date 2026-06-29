"""chFusion Voting Fusion — per-tone BPM voting validation.

Implements ``docs/plans/voting_fusion_plan.md``: T0/T1/T2/T3 voting methods
vs Plan2 baselines across three metal-plate scenarios.

Run: ``python notebooks/scripts/chFusion_voting_fusion.py``
"""

# %%
import sys
from pathlib import Path

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
CACHE_DIR = str(project_root / "outputs" / "cache")

# %%
from ble_analysis.chfusion import ChFusionConfig, Plan2Config, _overall_rel_error, load_multichannel_for_scenario
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import BreathMetricParams, FilterParams
from ble_analysis.voting_fusion import (
    VOTING_METHOD_SPECS,
    build_voting_leaderboard_rows,
    compute_channel_bpm_persistence,
    compute_cross_domain_aggregate,
    plot_voting_diagnostics,
    run_voting_fusion_benchmark,
)

SCENARIO_IDS = ("cs_091339", "cs_095806", "cs_102621")

filter_params = FilterParams()
metric_params = BreathMetricParams()
chfusion_config = ChFusionConfig(
    breath_freq_low=metric_params.breath_freq_low,
    breath_freq_high=metric_params.breath_freq_high,
    window_length_sec=metric_params.window_length_sec,
    step_length_sec=metric_params.step_length_sec,
    enable_consensus=False,
)
plan2_config = Plan2Config(channel_metric="energy_ratio")

# %%
results_by_scenario: dict = {}

for scenario_id in SCENARIO_IDS:
    scenario = load_scenario(scenario_id, project_root=project_root)
    print(f"\n{'=' * 60}")
    print_scenario_summary(scenario)
    multichannel_by_var, _fs, _skipped = load_multichannel_for_scenario(
        scenario,
        project_root=project_root,
        filter_params=filter_params,
        cache_dir=CACHE_DIR,
        verbose=True,
    )
    bench = run_voting_fusion_benchmark(
        None,
        scenario.segment_config,
        filter_params=filter_params,
        metric_params=metric_params,
        config=chfusion_config,
        plan2_config=plan2_config,
        verbose=True,
        cache_dir=CACHE_DIR,
        multichannel_by_var=multichannel_by_var,
    )
    results_by_scenario[scenario_id] = bench
    report_path = REPORTS_DIR / f"voting_fusion_{scenario.tag}_results.npy"
    np.save(report_path, bench, allow_pickle=True)
    print(f"Saved: {report_path}")

np.save(REPORTS_DIR / "voting_fusion_results.npy", results_by_scenario, allow_pickle=True)
print(f"\nSaved combined: {REPORTS_DIR / 'voting_fusion_results.npy'}")

# %%
cross_domain = compute_cross_domain_aggregate(results_by_scenario)
np.save(REPORTS_DIR / "voting_fusion_cross_domain.npy", cross_domain, allow_pickle=True)

print("\n=== Cross-domain leaderboard (mean err%) ===")
print(f"{'Rank':<5} {'Method':<28} {'Mean':>8} {'±std':>8}")
print("-" * 52)
for row in cross_domain:
    print(
        f"{row['rank']:<5} {row['label']:<28} "
        f"{row['cross_domain_mean']:8.2f} {row['cross_domain_std']:8.2f}"
    )

# %%
# Per-scenario table
print("\n=== Per-scenario mean err% ===")
header = f"{'Method':<28}" + "".join(f"{sid[-6:]:>10}" for sid in SCENARIO_IDS) + f"{'X-dom':>10}"
print(header)
print("-" * len(header))
for label, key, _ in VOTING_METHOD_SPECS:
    row = f"{label:<28}"
    per_scenario = []
    for sid in SCENARIO_IDS:
        stats = _overall_rel_error(results_by_scenario[sid]["results"], key)
        val = stats["mean_rel_err_pct"]
        per_scenario.append(val)
        row += f"{val:10.2f}" if np.isfinite(val) else f"{'—':>10}"
    xdom = float(np.mean([v for v in per_scenario if np.isfinite(v)])) if per_scenario else np.nan
    row += f"{xdom:10.2f}" if np.isfinite(xdom) else f"{'—':>10}"
    print(row)

# %%
# Leaderboard bar chart (cross-domain)
fig, ax = plt.subplots(figsize=(12, 6))
labels = [r["label"] for r in cross_domain]
means = [r["cross_domain_mean"] for r in cross_domain]
stds = [r["cross_domain_std"] for r in cross_domain]
colors = [r["color"] for r in cross_domain]
y_pos = np.arange(len(labels))
ax.barh(y_pos, means, xerr=stds, color=colors, alpha=0.85, capsize=3)
ax.set_yticks(y_pos)
ax.set_yticklabels(labels, fontsize=9)
ax.set_xlabel("Mean BPM relative error (%)")
ax.set_title("Voting Fusion — cross-domain aggregate (3 metal-plate scenarios)")
ax.axvline(9.45, color="gray", linestyle="--", linewidth=1, label="Modal top2 ref (9.45%)")
ax.legend(loc="lower right")
ax.grid(True, axis="x", alpha=0.3)
plt.tight_layout()
leaderboard_path = FIGURES_DIR / "voting_fusion_leaderboard.pdf"
fig.savefig(leaderboard_path, bbox_inches="tight")
print(f"Saved: {leaderboard_path}")
plt.close(fig)

# %%
# Cross-domain aggregate bars (scenario-colored)
fig, ax = plt.subplots(figsize=(14, 6))
method_labels = [r["label"] for r in cross_domain[:8]]
x = np.arange(len(method_labels))
width = 0.25
scenario_colors = ["#4C72B0", "#55A868", "#C44E52"]
for i, sid in enumerate(SCENARIO_IDS):
    tag = load_scenario(sid, project_root=project_root).tag
    vals = []
    for row in cross_domain[:8]:
        stats = _overall_rel_error(results_by_scenario[sid]["results"], row["method_key"])
        vals.append(stats["mean_rel_err_pct"])
    ax.bar(x + (i - 1) * width, vals, width, label=tag, color=scenario_colors[i], alpha=0.85)
ax.set_xticks(x)
ax.set_xticklabels(method_labels, rotation=30, ha="right", fontsize=8)
ax.set_ylabel("Mean BPM relative error (%)")
ax.set_title("Voting Fusion — top-8 methods by scenario")
ax.legend()
ax.grid(True, axis="y", alpha=0.3)
plt.tight_layout()
cross_path = FIGURES_DIR / "voting_fusion_cross_domain_aggregate_bars.pdf"
fig.savefig(cross_path, bbox_inches="tight")
print(f"Saved: {cross_path}")
plt.close(fig)

# %%
# Diagnostics: per-tone BPM + multi-method trajectories (091339, seg 3)
diag_scenario = "cs_091339"
bench = results_by_scenario[diag_scenario]
results = bench["results"]
seg_name = "3"
row = results.get(seg_name)
if row and "t0_v2_eta_weighted" in row:
    block = row["t0_v2_eta_weighted"]
    gt = row["bpm_gt"]
    ch_ids = block.get("tone_channel_ids")
    if not ch_ids:
        ref_seg = bench["multichannel_by_var"]["remote_amplitudes"].get(seg_name)
        if ref_seg:
            ch_ids = sorted(
                ref_seg["channels"].keys(),
                key=lambda c: (isinstance(c, str), str(c)),
            )

    plot_voting_diagnostics(
        row,
        seg_name=seg_name,
        gt=gt,
        tone_channel_ids=ch_ids or [],
        figures_dir=FIGURES_DIR,
        scenario_tag=load_scenario(diag_scenario, project_root=project_root).tag,
        show=False,
        save=True,
    )

    if ch_ids:
        pers = compute_channel_bpm_persistence(block, ch_ids)
        print(
            f"\nChannel BPM persistence (seg {seg_name}): "
            f"mean |ΔBPM| across consecutive windows = {pers['mean_step_l1']:.2f} BPM "
            f"({pers['n_channels']} tones, {pers['n_windows']} windows)"
        )
        print(
            "Panel 1 overlays (cross-domain rank): T0-V2, T0-V3 (best voting), "
            "Modal top2, Single Remote, T3 hybrid"
        )

print("\n=== Done ===")
