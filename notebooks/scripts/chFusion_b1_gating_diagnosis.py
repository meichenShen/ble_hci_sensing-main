"""B1 joint gating and Vote→Equal mechanism diagnosis.

Implements ``docs/plans/b1_gating_and_diagnosis_plan.md``.

Run: ``python notebooks/scripts/chFusion_b1_gating_diagnosis.py``
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
from ble_analysis.b1_gating_diagnosis import (
    BASELINE_KEYS,
    G4_B1_METHOD_SPECS,
    compute_b1_cross_domain_aggregate,
    plot_b1_gating_figures,
    run_b1_gating_diagnosis_benchmark,
)
from ble_analysis.chfusion import ChFusionConfig, Plan2Config, _overall_rel_error, load_multichannel_for_scenario
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
diagnostics_by_scenario: dict = {}

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
    bench = run_b1_gating_diagnosis_benchmark(
        multichannel_by_var,
        scenario.segment_config,
        filter_params=filter_params,
        metric_params=metric_params,
        config=chfusion_config,
        plan2_config=plan2_config,
        verbose=True,
        include_g5_b1=(scenario_id == "cs_091339"),
    )
    results_by_scenario[scenario_id] = bench
    diagnostics_by_scenario[scenario_id] = bench["diagnostics"]
    tag = scenario.tag
    np.save(REPORTS_DIR / f"b1_gating_diagnosis_{tag}_results.npy", bench, allow_pickle=True)
    print(f"Saved: {REPORTS_DIR / f'b1_gating_diagnosis_{tag}_results.npy'}")

np.save(REPORTS_DIR / "b1_gating_diagnosis_results.npy", results_by_scenario, allow_pickle=True)

# %%
all_specs = [
    *[(label, key, color) for label, key, color, _v in G4_B1_METHOD_SPECS],
    *[(label, key) for label, key in BASELINE_KEYS],
    ("G5-B1 (091339 only)", "g5_b1", "darkred"),
    ("D3-A B1", "d3_a_b1", "darkorange"),
    ("D3-A B3", "d3_a_b3", "coral"),
    ("D3-C16 B1", "d3_c16_b1", "royalblue"),
    ("D3-C16 B3", "d3_c16_b3", "dodgerblue"),
]
cross_domain = compute_b1_cross_domain_aggregate(results_by_scenario, all_specs)
np.save(REPORTS_DIR / "b1_gating_diagnosis_cross_domain.npy", cross_domain, allow_pickle=True)

print("\n=== Cross-domain leaderboard (mean err%) ===")
print(f"{'Rank':<5} {'Method':<28} {'Mean':>8} {'±std':>8}")
print("-" * 52)
for row in cross_domain:
    print(
        f"{row['rank']:<5} {row['label']:<28} "
        f"{row['cross_domain_mean']:8.2f} {row['cross_domain_std']:8.2f}"
    )

# %%
print("\n=== Per-scenario mean err% (G4-B1 + baselines) ===")
show_keys = [key for _, key, _, _ in G4_B1_METHOD_SPECS] + [k for _, k in BASELINE_KEYS]
header = f"{'Method':<22}" + "".join(f"{sid[-6:]:>10}" for sid in SCENARIO_IDS) + f"{'X-dom':>10}"
print(header)
print("-" * len(header))
for key in show_keys:
    label = next(
        (s[0] for s in G4_B1_METHOD_SPECS if s[1] == key),
        next((s[0] for s in BASELINE_KEYS if s[1] == key), key),
    )
    row = f"{label:<22}"
    per_vals = []
    for sid in SCENARIO_IDS:
        if key == "g5_b1" and sid != "cs_091339":
            row += f"{'—':>10}"
            continue
        stats = _overall_rel_error(results_by_scenario[sid]["results"], key)
        val = stats["mean_rel_err_pct"]
        per_vals.append(val)
        row += f"{val:10.2f}" if np.isfinite(val) else f"{'—':>10}"
    xdom_vals = [v for v in per_vals if np.isfinite(v)]
    xdom = float(np.mean(xdom_vals)) if xdom_vals else np.nan
    row += f"{xdom:10.2f}" if np.isfinite(xdom) else f"{'—':>10}"
    print(row)

# %%
fig_paths = plot_b1_gating_figures(
    results_by_scenario,
    cross_domain,
    diagnostics_by_scenario,
    figures_dir=FIGURES_DIR,
    scenario_ids=SCENARIO_IDS,
    show=False,
    save=True,
)
for name, path in fig_paths.items():
    print(f"Saved figure [{name}]: {path}")

print("\nDone. Report: docs/reports/b1_gating_and_diagnosis_report.md")
