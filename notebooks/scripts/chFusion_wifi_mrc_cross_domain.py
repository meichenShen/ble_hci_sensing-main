"""Cross-domain aggregation for WiFi MRC baselines.

Loads ``outputs/reports/wifi_mrc_baselines_results.npy`` and regenerates figures.

Run: ``python notebooks/scripts/chFusion_wifi_mrc_cross_domain.py``
"""

from __future__ import annotations

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

from ble_analysis.chfusion import _overall_rel_error
from ble_analysis.wifi_mrc import (
    WIFI_MRC_METHOD_SPECS,
    compute_wifi_mrc_cross_domain,
    compute_window_level_metrics,
    plot_wifi_mrc_figures,
)

SCENARIO_IDS = ("cs_091339", "cs_095806", "cs_102621")
RESULTS_PATH = REPORTS_DIR / "wifi_mrc_baselines_results.npy"

if not RESULTS_PATH.exists():
    raise FileNotFoundError(
        f"Missing {RESULTS_PATH}. Run chFusion_wifi_mrc_baselines.py --all first."
    )

results_by_scenario = np.load(RESULTS_PATH, allow_pickle=True).item()
cross_domain = compute_wifi_mrc_cross_domain(results_by_scenario)
np.save(REPORTS_DIR / "wifi_mrc_baselines_cross_domain.npy", cross_domain, allow_pickle=True)

print("=== Cross-domain leaderboard ===")
for row in cross_domain:
    print(f"{row['rank']:>2}. {row['label']:<28} {row['cross_domain_mean']:.2f}%")

print("\n=== Window-level metrics (pooled across scenarios) ===")
for label, key, _ in WIFI_MRC_METHOD_SPECS:
    if not key.startswith(("fan_", "mrc_", "b1_vote")):
        continue
    all_metrics = []
    for sid in SCENARIO_IDS:
        if sid not in results_by_scenario:
            continue
        m = compute_window_level_metrics(results_by_scenario[sid]["results"], key)
        if m["n_windows"] > 0:
            all_metrics.append(m)
    if not all_metrics:
        continue
    p90 = float(np.mean([m["p90_rel_err_pct"] for m in all_metrics]))
    w1 = float(np.mean([m["within_1_bpm_ratio"] for m in all_metrics]))
    w2 = float(np.mean([m["within_2_bpm_ratio"] for m in all_metrics]))
    print(f"{label:<28} p90={p90:.1f}%  ≤1BPM={w1:.2%}  ≤2BPM={w2:.2%}")

fig_paths = plot_wifi_mrc_figures(
    results_by_scenario,
    cross_domain,
    figures_dir=FIGURES_DIR,
    scenario_ids=SCENARIO_IDS,
    show=False,
    save=True,
)
for name, path in fig_paths.items():
    print(f"Saved figure: {path}")

print("\nDone.")
