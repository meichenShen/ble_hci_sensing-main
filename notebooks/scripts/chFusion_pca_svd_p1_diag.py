"""P1: cs_091339 harmonic + PC1 spectrum diagnostics.

Run: ``python notebooks/scripts/chFusion_pca_svd_p1_diag.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

_cwd = Path.cwd().resolve()
project_root = next((p for p in [_cwd, *_cwd.parents] if (p / "src").is_dir()), None)
if project_root is None:
    raise FileNotFoundError("Project root not found")

_src = project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from ble_analysis.bootstrap import init_notebook
from ble_analysis.pca_svd_pipeline import (
    DIAG_SCENARIO_ID,
    make_default_pipeline_config,
    run_p1_diagnostics,
)

_env = init_notebook(project_root)
FIGURES_DIR = _env["FIGURES_DIR"]
REPORTS_DIR = _env["REPORTS_DIR"]


def main() -> None:
    pipe_cfg = make_default_pipeline_config()
    run_p1_diagnostics(
        DIAG_SCENARIO_ID,
        project_root=project_root,
        reports_dir=REPORTS_DIR,
        figures_dir=FIGURES_DIR,
        pipe_cfg=pipe_cfg,
        verbose=True,
    )


if __name__ == "__main__":
    main()
