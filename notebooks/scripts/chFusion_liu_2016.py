"""Liu et al. 2016 baseline benchmark for BLE CS breathing BPM estimation.

Run:
    python notebooks/scripts/chFusion_liu_2016.py --scenario cs_091339
    python notebooks/scripts/chFusion_liu_2016.py --all
"""

from __future__ import annotations

import argparse
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

from ble_analysis.chfusion import ChFusionConfig, _overall_rel_error, load_multichannel_for_scenario
from ble_analysis.liu_2016 import run_liu_2016_benchmark
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import BreathMetricParams, FilterParams

DEFAULT_SCENARIOS = ("cs_091339", "cs_095806", "cs_102621")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Liu 2016-style benchmark")
    parser.add_argument("--scenario", type=str, default=None, help="Single scenario id")
    parser.add_argument("--all", action="store_true", help="Run all three scenarios")
    return parser.parse_args()


def run_one_scenario(scenario_id: str) -> dict:
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
    bench = run_liu_2016_benchmark(
        None,
        scenario.segment_config,
        filter_params=filter_params,
        metric_params=metric_params,
        config=chfusion_config,
        verbose=True,
        cache_dir=CACHE_DIR,
        multichannel_by_var=multichannel_by_var,
    )
    report_path = REPORTS_DIR / f"liu_2016_{scenario.tag}_results.npy"
    np.save(report_path, bench, allow_pickle=True)
    print(f"Saved: {report_path}")
    return bench


if __name__ == "__main__":
    args = parse_args()
    filter_params = FilterParams()
    metric_params = BreathMetricParams()
    chfusion_config = ChFusionConfig(
        breath_freq_low=metric_params.breath_freq_low,
        breath_freq_high=metric_params.breath_freq_high,
        window_length_sec=metric_params.window_length_sec,
        step_length_sec=metric_params.step_length_sec,
    )

    if args.all or args.scenario is None:
        scenario_ids = list(DEFAULT_SCENARIOS)
    else:
        scenario_ids = [args.scenario]

    results_by_scenario: dict = {}
    for sid in scenario_ids:
        results_by_scenario[sid] = run_one_scenario(sid)

    combined_path = REPORTS_DIR / "liu_2016_results.npy"
    np.save(combined_path, results_by_scenario, allow_pickle=True)
    print(f"\nSaved combined: {combined_path}")

    print("\n=== Cross-domain summary ===")
    for sid in scenario_ids:
        stats = _overall_rel_error(results_by_scenario[sid]["results"], "liu_2016")
        print(f"{sid}: mean err {stats['mean_rel_err_pct']:.2f}% ± {stats['std_rel_err_pct']:.2f}%")

    print("\nDone. Report: docs/reports/liu_2016_report.md")
