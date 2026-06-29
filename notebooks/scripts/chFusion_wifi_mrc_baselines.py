"""WiFi MRC baseline validation for BLE CS BPM estimation.

Implements ``docs/plans/wifi_mrc_baselines_plan.md``.

Run:
    python notebooks/scripts/chFusion_wifi_mrc_baselines.py --scenario cs_091339
    python notebooks/scripts/chFusion_wifi_mrc_baselines.py --all
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

from ble_analysis.chfusion import ChFusionConfig, Plan2Config, _overall_rel_error, load_multichannel_for_scenario
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import BreathMetricParams, FilterParams
from ble_analysis.wifi_mrc import (
    WIFI_MRC_METHOD_SPECS,
    compute_wifi_mrc_cross_domain,
    compute_window_level_metrics,
    plot_wifi_mrc_figures,
    run_wifi_mrc_benchmark,
)

DEFAULT_SCENARIOS = ("cs_091339", "cs_095806", "cs_102621")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WiFi MRC baselines benchmark")
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Single scenario id, e.g. cs_091339",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all three validation scenarios",
    )
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
    bench = run_wifi_mrc_benchmark(
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
    tag = scenario.tag
    report_path = REPORTS_DIR / f"wifi_mrc_baselines_{tag}_results.npy"
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
        enable_consensus=False,
    )
    plan2_config = Plan2Config(channel_metric="energy_ratio")

    if args.all or args.scenario is None:
        scenario_ids = list(DEFAULT_SCENARIOS)
    else:
        scenario_ids = [args.scenario]

    results_by_scenario: dict = {}
    for sid in scenario_ids:
        results_by_scenario[sid] = run_one_scenario(sid)

    combined_path = REPORTS_DIR / "wifi_mrc_baselines_results.npy"
    np.save(combined_path, results_by_scenario, allow_pickle=True)
    print(f"\nSaved combined: {combined_path}")

    cross_domain = compute_wifi_mrc_cross_domain(results_by_scenario)
    np.save(REPORTS_DIR / "wifi_mrc_baselines_cross_domain.npy", cross_domain, allow_pickle=True)

    print("\n=== Cross-domain leaderboard (mean err%) ===")
    print(f"{'Rank':<5} {'Method':<28} {'Mean':>8} {'±std':>8}")
    print("-" * 52)
    for row in cross_domain:
        print(
            f"{row['rank']:<5} {row['label']:<28} "
            f"{row['cross_domain_mean']:8.2f} {row['cross_domain_std']:8.2f}"
        )

    print("\n=== Per-scenario mean err% ===")
    header = f"{'Method':<28}" + "".join(f"{sid[-6:]:>10}" for sid in scenario_ids) + f"{'X-dom':>10}"
    print(header)
    print("-" * len(header))
    for label, key, _ in WIFI_MRC_METHOD_SPECS:
        row = f"{label:<28}"
        per_vals = []
        for sid in scenario_ids:
            stats = _overall_rel_error(results_by_scenario[sid]["results"], key)
            val = stats["mean_rel_err_pct"]
            per_vals.append(val)
            row += f"{val:10.2f}" if np.isfinite(val) else f"{'—':>10}"
        xdom = float(np.mean([v for v in per_vals if np.isfinite(v)])) if per_vals else np.nan
        row += f"{xdom:10.2f}" if np.isfinite(xdom) else f"{'—':>10}"
        print(row)

    if len(scenario_ids) == len(DEFAULT_SCENARIOS):
        fig_paths = plot_wifi_mrc_figures(
            results_by_scenario,
            cross_domain,
            figures_dir=FIGURES_DIR,
            scenario_ids=DEFAULT_SCENARIOS,
            show=False,
            save=True,
        )
        for name, path in fig_paths.items():
            print(f"Saved figure: {path}")

    print("\nDone. Report: docs/reports/wifi_mrc_baselines_report.md")
