"""chFusion Voting Gating — window-level consensus gating validation.

Implements ``docs/plans/voting_gating_plan.md``: G1–G6 gating strategies
vs Plan2 baselines and T0-V3 voting across three metal-plate scenarios.

Run: ``python notebooks/scripts/chFusion_voting_gating.py``
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
from ble_analysis.consensus_gating import (
    GATING_METHOD_SPECS,
    GATING_STRATEGY_PRESETS,
    build_gating_leaderboard_rows,
    compute_gating_cross_domain_aggregate,
    compute_oracle_selection_stats,
    plot_gating_figures,
    run_gating_benchmark,
)
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import BreathMetricParams, FilterParams

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
    bench = run_gating_benchmark(
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
    report_path = REPORTS_DIR / f"voting_gating_{tag}_results.npy"
    np.save(report_path, bench, allow_pickle=True)
    print(f"Saved: {report_path}")

np.save(REPORTS_DIR / "voting_gating_results.npy", results_by_scenario, allow_pickle=True)
print(f"\nSaved combined: {REPORTS_DIR / 'voting_gating_results.npy'}")

# %%
cross_domain = compute_gating_cross_domain_aggregate(results_by_scenario)
np.save(REPORTS_DIR / "voting_gating_cross_domain.npy", cross_domain, allow_pickle=True)

print("\n=== Cross-domain leaderboard (mean err%) ===")
print(f"{'Rank':<5} {'Method':<28} {'Mean':>8} {'±std':>8}")
print("-" * 52)
for row in cross_domain:
    print(
        f"{row['rank']:<5} {row['label']:<28} "
        f"{row['cross_domain_mean']:8.2f} {row['cross_domain_std']:8.2f}"
    )

# %%
print("\n=== Per-scenario mean err% ===")
header = f"{'Method':<28}" + "".join(f"{sid[-6:]:>10}" for sid in SCENARIO_IDS) + f"{'X-dom':>10}"
print(header)
print("-" * len(header))
for label, key, _ in GATING_METHOD_SPECS:
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
oracle_all = {}
for gkey in GATING_STRATEGY_PRESETS:
    oracle_rows = []
    for sid in SCENARIO_IDS:
        stats = compute_oracle_selection_stats(results_by_scenario[sid], gating_method_key=gkey)
        for r in stats["rows"]:
            oracle_rows.append({**r, "scenario": sid})
    oracle_all[gkey] = oracle_rows
np.save(REPORTS_DIR / "voting_gating_oracle_stats.npy", oracle_all, allow_pickle=True)

print("\n=== Oracle selection accuracy (G1) ===")
for r in oracle_all.get("g1_simple_consensus", []):
    print(
        f"  {r['scenario']}/{r['segment']}: "
        f"vote={r['oracle_vote_frac']:.0%} modal={r['oracle_modal_frac']:.0%} "
        f"single={r['oracle_single_frac']:.0%} | gating correct={r['gating_correct_frac']:.0%}"
    )

# %%
fig_paths = plot_gating_figures(
    results_by_scenario,
    cross_domain,
    results_by_scenario[SCENARIO_IDS[0]],
    figures_dir=FIGURES_DIR,
    scenario_ids=SCENARIO_IDS,
    show=False,
    save=True,
)
for name, path in fig_paths.items():
    print(f"Saved figure: {path}")

plt.close("all")

# %%
print("\nDone. Generate report: docs/reports/voting_gating_report.md")
