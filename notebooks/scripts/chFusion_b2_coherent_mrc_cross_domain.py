"""Cross-domain aggregation for B2 Coherent-MRC validation.

Run: ``python notebooks/scripts/chFusion_b2_coherent_mrc_cross_domain.py``
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
FIGURES_DIR = _env["FIGURES_DIR"]
REPORTS_DIR = _env["REPORTS_DIR"]

from ble_analysis.coherent_mrc import B2_ALL_SPECS, compute_b2_cross_domain, plot_b2_figures, plot_b2_achievement_figures

SCENARIO_IDS = ("cs_091339", "cs_095806", "cs_102621")
RESULTS_PATH = REPORTS_DIR / "b2_coherent_mrc_all_results.npy"

if not RESULTS_PATH.exists():
    raise FileNotFoundError(
        f"Missing {RESULTS_PATH}. Run chFusion_b2_coherent_mrc.py --all first."
    )

results_by_scenario = np.load(RESULTS_PATH, allow_pickle=True).item()
baseline_specs = B2_ALL_SPECS + (
    ("B0 Single Remote", "b0_single_remote", "steelblue"),
    ("Modal top2 equal", "b2_modal_top2_equal", "mediumpurple"),
    ("B1 Vote→Equal modal", "b1_vote_modal_equal", "olive"),
    ("MRC-PCA-η-equal", "mrc_pca_eta_equal", "crimson"),
)
cross_domain = compute_b2_cross_domain(results_by_scenario, baseline_specs)
np.save(REPORTS_DIR / "b2_coherent_mrc_all_cross_domain.npy", cross_domain, allow_pickle=True)

print("=== Cross-domain leaderboard ===")
for row in cross_domain:
    print(f"{row['rank']:>2}. {row['label']:<40} {row['cross_domain_mean']:.2f}%")

fig_paths = plot_b2_figures(
    results_by_scenario,
    cross_domain,
    figures_dir=FIGURES_DIR,
    scenario_ids=SCENARIO_IDS,
    show=False,
    save=True,
)
for name, path in fig_paths.items():
    print(f"Saved figure: {path}")

ach_paths = plot_b2_achievement_figures(
    cross_domain,
    figures_dir=FIGURES_DIR,
    scenario_ids=SCENARIO_IDS,
    show=False,
    save=True,
)
for name, path in ach_paths.items():
    print(f"Saved achievement figure: {path}")

print("\nDone.")
