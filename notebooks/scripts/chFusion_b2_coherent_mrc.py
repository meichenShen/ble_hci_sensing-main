"""B2 Coherent-MRC waveform fusion validation.

Implements ``docs/plans/b2_coherent_mrc_waveform_fusion_plan.md``.

Run:
    python notebooks/scripts/chFusion_b2_coherent_mrc.py --scenario cs_091339
    python notebooks/scripts/chFusion_b2_coherent_mrc.py --all
    python notebooks/scripts/chFusion_b2_coherent_mrc.py --all --phase 1
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
from ble_analysis.coherent_mrc import B2_ALL_SPECS, B2_METHOD_KEYS, compute_b2_cross_domain, run_b2_benchmark
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import BreathMetricParams, FilterParams

DEFAULT_SCENARIOS = ("cs_091339", "cs_095806", "cs_102621")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B2 Coherent-MRC benchmark")
    parser.add_argument("--scenario", type=str, default=None, help="Single scenario id")
    parser.add_argument("--all", action="store_true", help="Run all three validation scenarios")
    parser.add_argument(
        "--phase",
        type=str,
        default="all",
        choices=("1", "all"),
        help="Run Phase 1 only (A0/A1) or all B2 variants",
    )
    return parser.parse_args()


def run_one_scenario(scenario_id: str, phase: str) -> dict:
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
    bench = run_b2_benchmark(
        None,
        scenario.segment_config,
        filter_params=filter_params,
        metric_params=metric_params,
        config=chfusion_config,
        plan2_config=plan2_config,
        verbose=True,
        cache_dir=CACHE_DIR,
        multichannel_by_var=multichannel_by_var,
        phase=phase,
    )
    tag = scenario.tag
    suffix = f"phase1_{tag}" if phase == "1" else tag
    report_path = REPORTS_DIR / f"b2_coherent_mrc_{suffix}_results.npy"
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
        results_by_scenario[sid] = run_one_scenario(sid, args.phase)

    suffix = "phase1" if args.phase == "1" else "all"
    combined_path = REPORTS_DIR / f"b2_coherent_mrc_{suffix}_results.npy"
    np.save(combined_path, results_by_scenario, allow_pickle=True)
    print(f"\nSaved combined: {combined_path}")

    baseline_specs = B2_ALL_SPECS + (
        ("B0 Single Remote", "b0_single_remote", "steelblue"),
        ("B1 Vote→Equal modal", "b1_vote_modal_equal", "olive"),
        ("MRC-PCA-η-equal", "mrc_pca_eta_equal", "crimson"),
    )
    cross_domain = compute_b2_cross_domain(results_by_scenario, baseline_specs)
    np.save(REPORTS_DIR / f"b2_coherent_mrc_{suffix}_cross_domain.npy", cross_domain, allow_pickle=True)

    print("\n=== Cross-domain leaderboard (mean err%) ===")
    print(f"{'Rank':<5} {'Method':<40} {'Mean':>8} {'±std':>8}")
    print("-" * 64)
    for row in cross_domain:
        print(
            f"{row['rank']:<5} {row['label']:<40} "
            f"{row['cross_domain_mean']:8.2f} {row['cross_domain_std']:8.2f}"
        )

    print("\n=== B2 methods per-scenario ===")
    keys = list(B2_METHOD_KEYS) if args.phase == "all" else [s[1] for s in B2_ALL_SPECS[:2]]
    header = f"{'Method':<40}" + "".join(f"{sid[-6:]:>10}" for sid in scenario_ids) + f"{'X-dom':>10}"
    print(header)
    print("-" * len(header))
    for label, key, _ in B2_ALL_SPECS:
        if key not in keys:
            continue
        row = f"{label:<40}"
        per_vals = []
        for sid in scenario_ids:
            stats = _overall_rel_error(results_by_scenario[sid]["results"], key)
            val = stats["mean_rel_err_pct"]
            per_vals.append(val)
            row += f"{val:10.2f}" if np.isfinite(val) else f"{'—':>10}"
        xdom = float(np.mean([v for v in per_vals if np.isfinite(v)])) if per_vals else np.nan
        row += f"{xdom:10.2f}" if np.isfinite(xdom) else f"{'—':>10}"
        print(row)
