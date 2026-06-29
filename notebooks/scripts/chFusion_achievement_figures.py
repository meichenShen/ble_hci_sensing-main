"""Generate achievement-report summary figures (§9.3 high-priority charts).

Run: ``python notebooks/scripts/chFusion_achievement_figures.py``

Outputs PNG to ``outputs/figures/`` per
``docs/achievements/pca_voting_comprehensive_achievement_report.md``.
"""

# %%
import sys
from pathlib import Path

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

from ble_analysis.achievement_figures import plot_all_achievement_figures
from ble_analysis.bootstrap import init_notebook

_env = init_notebook(project_root)
FIGURES_DIR = _env["FIGURES_DIR"]
REPORTS_DIR = _env["REPORTS_DIR"]

# %%
paths = plot_all_achievement_figures(
    reports_dir=REPORTS_DIR,
    figures_dir=FIGURES_DIR,
    include_pca=True,
)

print("\n=== Achievement figures generated ===")
for name, path in paths.items():
    print(f"  {name}: {path}")

print("\n=== Done ===")
