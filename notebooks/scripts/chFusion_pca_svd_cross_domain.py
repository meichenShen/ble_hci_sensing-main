"""chFusion PCA/SVD — cross-domain pipeline runner (§8 only).

Run: ``python notebooks/scripts/chFusion_pca_svd_cross_domain.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

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
from ble_analysis.pca_svd_pipeline import (
    COMPARE_SCENARIO_IDS,
    aggregate_cross_domain_rows,
    ensure_scenario_report,
    make_default_pipeline_config,
    print_cross_domain_table,
    save_cross_domain_aggregate,
)
from ble_analysis.scenarios import load_scenario

_env = init_notebook(project_root)
FIGURES_DIR = _env["FIGURES_DIR"]
REPORTS_DIR = _env["REPORTS_DIR"]

FORCE_REBUILD = False


def main() -> None:
    pipe_cfg = make_default_pipeline_config()
    results_by_tag = {}
    for sid in COMPARE_SCENARIO_IDS:
        sc = load_scenario(sid, project_root=project_root)
        results_by_tag[sc.tag] = ensure_scenario_report(
            sid,
            project_root=project_root,
            reports_dir=REPORTS_DIR,
            pipe_cfg=pipe_cfg,
            verbose=True,
            force=FORCE_REBUILD,
        )

    compare_tags = [
        load_scenario(sid, project_root=project_root).tag for sid in COMPARE_SCENARIO_IDS
    ]
    cross_rows = aggregate_cross_domain_rows(results_by_tag, compare_tags)
    print_cross_domain_table(cross_rows, compare_tags)
    report_path, fig_path = save_cross_domain_aggregate(
        cross_rows,
        results_by_tag,
        reports_dir=REPORTS_DIR,
        figures_dir=FIGURES_DIR,
        scenario_ids=COMPARE_SCENARIO_IDS,
        compare_tags=compare_tags,
    )
    print(f"  Saved: {report_path.name}")
    print(f"  Fig: {fig_path.name}")


if __name__ == "__main__":
    main()
