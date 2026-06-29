"""Signal-level adaptive gating benchmark.

Implements ``docs/plans/signal_adaptive_gating_plan.md``.

Run: ``python notebooks/scripts/chFusion_signal_adaptive_gating.py``
"""

# %%
import sys
from pathlib import Path

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
from ble_analysis.signal_adaptive_gating import (
    SA_METHOD_SPECS,
    compute_sa_cross_domain_aggregate,
    plot_signal_adaptive_figures,
    run_signal_adaptive_gating_benchmark,
)

SCENARIO_IDS = ("cs_102621", "cs_091339", "cs_095806")

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
p1_by_scenario: dict = {}
sa_v2_calibration: dict | None = None

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
    bench = run_signal_adaptive_gating_benchmark(
        multichannel_by_var,
        scenario.segment_config,
        filter_params=filter_params,
        metric_params=metric_params,
        config=chfusion_config,
        plan2_config=plan2_config,
        scenario_id=scenario_id,
        sa_v2_calibration=sa_v2_calibration,
        verbose=True,
    )
    if scenario_id == "cs_102621":
        sa_v2_calibration = bench["sa_v2_calibration"]
        print(f"SA-v2 calibration (102621): {sa_v2_calibration}")

    results_by_scenario[scenario_id] = bench
    p1_by_scenario[scenario_id] = bench["p1_analysis"]
    tag = scenario.tag
    np.save(
        REPORTS_DIR / f"signal_adaptive_gating_{tag}_results.npy",
        bench,
        allow_pickle=True,
    )
    print(f"Saved: {REPORTS_DIR / f'signal_adaptive_gating_{tag}_results.npy'}")

np.save(
    REPORTS_DIR / "signal_adaptive_gating_results.npy",
    results_by_scenario,
    allow_pickle=True,
)

# %%
cross_domain = compute_sa_cross_domain_aggregate(results_by_scenario, SA_METHOD_SPECS)
np.save(REPORTS_DIR / "signal_adaptive_gating_cross_domain.npy", cross_domain, allow_pickle=True)

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
show_keys = [key for _, key, _ in SA_METHOD_SPECS]
header = f"{'Method':<22}" + "".join(f"{sid[-6:]:>10}" for sid in SCENARIO_IDS) + f"{'X-dom':>10}"
print(header)
print("-" * len(header))
for key in show_keys:
    label = next((s[0] for s in SA_METHOD_SPECS if s[1] == key), key)
    row = f"{label:<22}"
    per_vals = []
    for sid in SCENARIO_IDS:
        stats = _overall_rel_error(results_by_scenario[sid]["results"], key)
        val = stats["mean_rel_err_pct"]
        per_vals.append(val)
        row += f"{val:10.2f}" if np.isfinite(val) else f"{'—':>10}"
    xdom_vals = [v for v in per_vals if np.isfinite(v)]
    xdom = float(np.mean(xdom_vals)) if xdom_vals else np.nan
    row += f"{xdom:10.2f}" if np.isfinite(xdom) else f"{'—':>10}"
    print(row)

# %%
if "cs_102621" in p1_by_scenario:
    p1 = p1_by_scenario["cs_102621"]
    print("\n=== P1 window type fractions (102621) ===")
    for k, v in p1.get("type_fractions", {}).items():
        print(f"  {k}: {v:.1%}")

# %%
fig_paths = plot_signal_adaptive_figures(
    results_by_scenario,
    cross_domain,
    figures_dir=FIGURES_DIR,
    scenario_ids=SCENARIO_IDS,
    p1_by_scenario=p1_by_scenario,
    show=False,
    save=True,
)
for name, path in fig_paths.items():
    print(f"Figure [{name}]: {path}")

print("\nDone. Review materials:")
print(f"  - {REPORTS_DIR / 'signal_adaptive_gating_cross_domain.npy'}")
print(f"  - {FIGURES_DIR / 'sa_*.png'}")
