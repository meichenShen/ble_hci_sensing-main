"""chFusion Systematic Modal×Channel Fusion validation.

Implements ``docs/plans/systematic_modal_channel_fusion_plan.md``: Block A/B/C
plus baseline comparison across three metal-plate scenarios.

Run: ``python notebooks/scripts/chFusion_systematic_fusion.py``
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
from ble_analysis.systematic_fusion import (
    ALL_METHOD_SPECS,
    SYSTEMATIC_NEW_METHOD_SPECS,
    build_systematic_leaderboard_rows,
    compute_systematic_cross_domain,
    plot_systematic_fusion_figures,
    run_systematic_fusion_benchmark,
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
    bench = run_systematic_fusion_benchmark(
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
    tag = scenario.tag
    report_path = REPORTS_DIR / f"systematic_fusion_{tag}_results.npy"
    np.save(report_path, bench, allow_pickle=True)
    print(f"Saved: {report_path}")

np.save(REPORTS_DIR / "systematic_fusion_results.npy", results_by_scenario, allow_pickle=True)
print(f"\nSaved combined: {REPORTS_DIR / 'systematic_fusion_results.npy'}")

# %%
cross_domain = compute_systematic_cross_domain(results_by_scenario)
np.save(REPORTS_DIR / "systematic_fusion_cross_domain.npy", cross_domain, allow_pickle=True)

print("\n=== Cross-domain leaderboard (mean err%) ===")
print(f"{'Rank':<5} {'Method':<30} {'Mean':>8} {'±std':>8}")
print("-" * 54)
for row in cross_domain:
    print(
        f"{row['rank']:<5} {row['label']:<30} "
        f"{row['cross_domain_mean']:8.2f} {row['cross_domain_std']:8.2f}"
    )

# %%
print("\n=== Per-scenario mean err% ===")
header = f"{'Method':<30}" + "".join(f"{sid[-6:]:>10}" for sid in SCENARIO_IDS) + f"{'X-dom':>10}"
print(header)
print("-" * len(header))
for label, key, _ in ALL_METHOD_SPECS:
    row = f"{label:<30}"
    per_vals = []
    for sid in SCENARIO_IDS:
        stats = _overall_rel_error(results_by_scenario[sid]["results"], key)
        val = stats["mean_rel_err_pct"]
        per_vals.append(val)
        row += f"{val:10.2f}" if np.isfinite(val) else f"{'—':>10}"
    xdom = float(np.mean([v for v in per_vals if np.isfinite(v)])) if per_vals else np.nan
    row += f"{xdom:10.2f}" if np.isfinite(xdom) else f"{'—':>10}"
    print(row)

# %%
print("\n=== Ablation pairs (cross-domain) ===")
ablation_pairs = [
    ("A1 vs T0-V3 (phase vs remote voting)", "a1_phase_vote", "t0_v3_eta_rho_weighted"),
    ("B3 vs T0-V3 (modal fusion gain)", "b3_vote_modal_top2", "t0_v3_eta_rho_weighted"),
    ("B3 vs Modal top2 (voting vs single-best)", "b3_vote_modal_top2", "b2_modal_top2_equal"),
    ("B4 vs B3 (persistence gain)", "b4_votep_modal_top2", "b3_vote_modal_top2"),
    ("C1 vs Modal top2 (uniform vs single)", "c1_uniform_modal_top2", "b2_modal_top2_equal"),
]
for title, key_a, key_b in ablation_pairs:
    va = next((r["cross_domain_mean"] for r in cross_domain if r["method_key"] == key_a), np.nan)
    vb = next((r["cross_domain_mean"] for r in cross_domain if r["method_key"] == key_b), np.nan)
    delta = va - vb if np.isfinite(va) and np.isfinite(vb) else np.nan
    sign = "better" if delta < 0 else "worse"
    print(f"  {title}: {va:.2f}% vs {vb:.2f}% (Δ={delta:+.2f}%, {sign})")

# %%
fig_paths = plot_systematic_fusion_figures(
    results_by_scenario,
    cross_domain,
    figures_dir=FIGURES_DIR,
    scenario_ids=SCENARIO_IDS,
    show=False,
    save=True,
)
for name, path in fig_paths.items():
    print(f"Saved figure: {path}")

plt.close("all")

# %%
print("\nDone. Generate report: docs/reports/systematic_modal_channel_fusion_report.md")
