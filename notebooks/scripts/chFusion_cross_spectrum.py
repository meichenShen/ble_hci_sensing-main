"""chFusion Cross-Spectrum Combining validation.

Implements ``docs/plans/cross_spectrum_combining_plan.md``: X0–X7 cross-spectrum
methods vs power-spectrum baseline across three metal-plate scenarios.

Run: ``python notebooks/scripts/chFusion_cross_spectrum.py``
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
from ble_analysis.chfusion import ChFusionConfig, _overall_rel_error, load_multichannel_for_scenario
from ble_analysis.cross_spectrum import (
    CROSS_SPECTRUM_METHOD_SPECS,
    REFERENCE_BASELINE_SPECS,
    X0_BASELINE_SPEC,
    build_cross_spectrum_leaderboard_rows,
    compute_cross_spectrum_cross_domain,
    plot_cross_spectrum_figures,
    run_cross_spectrum_benchmark,
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

# Load prior systematic fusion results for reference baselines (if available)
systematic_path = REPORTS_DIR / "systematic_fusion_results.npy"
systematic_results = None
if systematic_path.exists():
    systematic_results = np.load(systematic_path, allow_pickle=True).item()
    print(f"Loaded reference baselines from {systematic_path}")
else:
    print("No systematic_fusion_results.npy — X0 will be computed inline; reference baselines omitted")

# %%
results_by_scenario: dict = {}
last_multichannel = None

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
    last_multichannel = multichannel_by_var
    bench = run_cross_spectrum_benchmark(
        None,
        scenario.segment_config,
        filter_params=filter_params,
        metric_params=metric_params,
        config=chfusion_config,
        verbose=True,
        cache_dir=CACHE_DIR,
        multichannel_by_var=multichannel_by_var,
        systematic_results=systematic_results,
        scenario_id=scenario_id,
    )
    results_by_scenario[scenario_id] = bench
    tag = scenario.tag
    report_path = REPORTS_DIR / f"cross_spectrum_{tag}_results.npy"
    np.save(report_path, bench, allow_pickle=True)
    print(f"Saved: {report_path}")

np.save(REPORTS_DIR / "cross_spectrum_results.npy", results_by_scenario, allow_pickle=True)
print(f"\nSaved combined: {REPORTS_DIR / 'cross_spectrum_results.npy'}")

# %%
cross_domain = compute_cross_spectrum_cross_domain(results_by_scenario)
np.save(REPORTS_DIR / "cross_spectrum_cross_domain.npy", cross_domain, allow_pickle=True)

print("\n=== Cross-domain leaderboard (mean err%) ===")
print(f"{'Rank':<5} {'Method':<28} {'Mean':>8} {'±std':>8}")
print("-" * 52)
for row in cross_domain:
    print(
        f"{row['rank']:<5} {row['label']:<28} "
        f"{row['cross_domain_mean']:8.2f} {row['cross_domain_std']:8.2f}"
    )

# %%
print("\n=== Per-scenario mean err% (X0–X7) ===")
x_specs = [X0_BASELINE_SPEC] + list(CROSS_SPECTRUM_METHOD_SPECS)
header = f"{'Method':<28}" + "".join(f"{sid[-6:]:>10}" for sid in SCENARIO_IDS) + f"{'X-dom':>10}"
print(header)
print("-" * len(header))
for spec in x_specs:
    label, key = spec[0], spec[1]
    row = f"{label:<28}"
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
print("\n=== Cross-spectrum vs X0 (delta cross-domain mean) ===")
x0_mean = next((r["cross_domain_mean"] for r in cross_domain if r["method_key"] == X0_BASELINE_SPEC[1]), np.nan)
for spec in CROSS_SPECTRUM_METHOD_SPECS:
    label, key = spec[0], spec[1]
    xm = next((r["cross_domain_mean"] for r in cross_domain if r["method_key"] == key), np.nan)
    if np.isfinite(x0_mean) and np.isfinite(xm):
        delta = xm - x0_mean
        sign = "better" if delta < 0 else "worse"
        print(f"  {label}: {xm:.2f}% vs X0 {x0_mean:.2f}% (Δ={delta:+.2f}%, {sign})")

# %%
primary_sid = SCENARIO_IDS[0]
fig_paths = plot_cross_spectrum_figures(
    results_by_scenario,
    cross_domain,
    figures_dir=FIGURES_DIR,
    scenario_ids=SCENARIO_IDS,
    multichannel_by_var=results_by_scenario[primary_sid].get("multichannel_by_var", last_multichannel),
    config=chfusion_config,
    metric_params=metric_params,
    show=False,
    save=True,
)
for name, path in fig_paths.items():
    print(f"Saved figure: {path}")

plt.close("all")

# %%
print("\nDone. Generate report: docs/reports/cross_spectrum_combining_report.md")
