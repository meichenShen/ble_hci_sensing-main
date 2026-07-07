"""Compare Liu 2016 BPM estimates across modal variables (remote, local, phases)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

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
from ble_analysis.chfusion import ChFusionConfig, load_multichannel_for_scenario
from ble_analysis.liu_2016 import (
    run_liu_2016_modal_comparison,
    MODAL_LIU_VARIABLES,
)
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import BreathMetricParams, FilterParams

DEFAULT_SCENARIOS = ("cs_091339", "cs_095806", "cs_102621")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Liu 2016 modal variable comparison")
    parser.add_argument("--scenario", type=str, default=None, help="Single scenario id")
    parser.add_argument("--all", action="store_true", help="Run all default scenarios")
    return parser.parse_args()


def collect_modal_results(benchmark: dict) -> pd.DataFrame:
    """Collect per-segment results across all modal variables and combined."""
    rows = []
    
    # Per-modal results
    for modal_var in MODAL_LIU_VARIABLES:
        for seg_name, result in benchmark["results_by_modal"][modal_var].items():
            if result is None:
                continue
            rows.append({
                "segment": seg_name,
                "modal_variable": modal_var,
                "bpm_gt": result["bpm_gt"],
                "mean_rel_err_pct": result["liu_2016_modal"]["bpm_rel_err"] * 100.0,
                "std_rel_err_pct": result["liu_2016_modal"]["bpm_rel_err_std"] * 100.0,
            })
    
    # Combined results
    for seg_name, result in benchmark["results_combined"].items():
        if result is None:
            continue
        rows.append({
            "segment": seg_name,
            "modal_variable": "combined (remote+local+phases)",
            "bpm_gt": result["bpm_gt"],
            "mean_rel_err_pct": result["liu_2016"]["bpm_rel_err"] * 100.0,
            "std_rel_err_pct": result["liu_2016"]["bpm_rel_err_std"] * 100.0,
        })
    
    return pd.DataFrame(rows)


def plot_modal_comparison_bars(figures_dir: Path, scenario_id: str, df: pd.DataFrame) -> None:
    """Plot relative error comparison across modals."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    # Group by modal variable and calculate mean errors across segments
    modal_means = df.groupby("modal_variable")[["mean_rel_err_pct", "std_rel_err_pct"]].mean()
    
    modals = list(modal_means.index)
    colors = {
        "remote_amplitudes": "#e74c3c",
        "local_amplitudes": "#3498db",
        "phases": "#2ecc71",
        "combined (remote+local+phases)": "#f39c12",
    }
    bar_colors = [colors.get(m, "#95a5a6") for m in modals]
    
    # Mean relative error
    axes[0].bar(modals, modal_means["mean_rel_err_pct"], color=bar_colors, alpha=0.8, edgecolor="#333")
    axes[0].set_ylabel("平均相对误差 (%)")
    axes[0].set_title(f"{scenario_id} — 各模态平均相对误差")
    axes[0].grid(axis="y", alpha=0.3)
    axes[0].tick_params(axis="x", rotation=45)
    
    # Std of relative error
    axes[1].bar(modals, modal_means["std_rel_err_pct"], color=bar_colors, alpha=0.8, edgecolor="#333")
    axes[1].set_ylabel("相对误差标准差 (%)")
    axes[1].set_title(f"{scenario_id} — 各模态相对误差标准差")
    axes[1].grid(axis="y", alpha=0.3)
    axes[1].tick_params(axis="x", rotation=45)
    
    fig.tight_layout()
    fig.savefig(
        figures_dir / f"liu_2016_{scenario_id}_modal_comparison_bars.png",
        dpi=200,
        bbox_inches="tight"
    )
    plt.close(fig)


def plot_modal_comparison_by_segment(figures_dir: Path, scenario_id: str, df: pd.DataFrame) -> None:
    """Plot modal variable comparison grouped by segment."""
    segments = sorted(df["segment"].unique())
    modals = [m for m in df["modal_variable"].unique() if m != "combined (remote+local+phases)"]
    combined = "combined (remote+local+phases)"
    
    fig, axes = plt.subplots(len(segments), 1, figsize=(12, 3 * len(segments)))
    if len(segments) == 1:
        axes = [axes]
    
    colors = {
        "remote_amplitudes": "#e74c3c",
        "local_amplitudes": "#3498db",
        "phases": "#2ecc71",
        "combined (remote+local+phases)": "#f39c12",
    }
    
    for idx, seg in enumerate(segments):
        seg_data = df[df["segment"] == seg]
        modal_errors = seg_data[seg_data["modal_variable"].isin(modals + [combined])]
        
        x_labels = list(modal_errors["modal_variable"])
        y_values = list(modal_errors["mean_rel_err_pct"])
        bar_colors = [colors.get(m, "#95a5a6") for m in x_labels]
        
        axes[idx].bar(x_labels, y_values, color=bar_colors, alpha=0.8, edgecolor="#333")
        axes[idx].set_ylabel("相对误差 (%)")
        axes[idx].set_title(f"{scenario_id} 段落 {seg} — 各模态相对误差")
        axes[idx].grid(axis="y", alpha=0.3)
        axes[idx].tick_params(axis="x", rotation=45)
    
    fig.tight_layout()
    fig.savefig(
        figures_dir / f"liu_2016_{scenario_id}_modal_by_segment.png",
        dpi=200,
        bbox_inches="tight"
    )
    plt.close(fig)


def save_modal_results_table(reports_dir: Path, scenario_id: str, df: pd.DataFrame) -> None:
    """Save results table as CSV and summary stats."""
    df.to_csv(reports_dir / f"liu_2016_{scenario_id}_modal_comparison.csv", index=False)
    
    # Summary by modal variable
    summary = df.groupby("modal_variable")[["mean_rel_err_pct", "std_rel_err_pct"]].agg(
        ["mean", "std", "min", "max"]
    )
    summary.to_csv(reports_dir / f"liu_2016_{scenario_id}_modal_summary.csv")
    
    print(f"\n=== {scenario_id} 模态对比汇总 ===")
    print(summary)


def main() -> None:
    args = parse_args()
    env = init_notebook(project_root)
    figures_dir = env["FIGURES_DIR"] / "liu_2016_ble_ablation" / "legacy_modal"
    figures_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = env["REPORTS_DIR"]
    cache_dir = project_root / "outputs" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    filter_params = FilterParams()
    metric_params = BreathMetricParams()
    cfg = ChFusionConfig(
        breath_freq_low=metric_params.breath_freq_low,
        breath_freq_high=metric_params.breath_freq_high,
        window_length_sec=metric_params.window_length_sec,
        step_length_sec=metric_params.step_length_sec,
    )

    if args.all or args.scenario is None:
        scenario_ids = list(DEFAULT_SCENARIOS)
    else:
        scenario_ids = [args.scenario]

    all_results_dfs = []

    for scenario_id in scenario_ids:
        print(f"\n{'='*70}")
        print(f"场景: {scenario_id}")
        print(f"{'='*70}")
        scenario = load_scenario(scenario_id, project_root=project_root)
        print_scenario_summary(scenario)
        
        # Load multichannel data (done in run_liu_2016_modal_comparison if not provided)
        print("\n加载多通道数据...")
        multichannel_by_var, fs, skipped = load_multichannel_for_scenario(
            scenario,
            project_root=project_root,
            filter_params=filter_params,
            cache_dir=str(cache_dir),
            verbose=False,
        )
        
        # Run modal comparison
        print("运行模态对比基准...")
        benchmark = run_liu_2016_modal_comparison(
            scenario.segment_config,
            filter_params=filter_params,
            metric_params=metric_params,
            config=cfg,
            verbose=False,
            cache_dir=str(cache_dir),
            multichannel_by_var=multichannel_by_var,
        )
        
        # Collect results
        df = collect_modal_results(benchmark)
        all_results_dfs.append(df)
        
        # Save and plot
        save_modal_results_table(reports_dir, scenario_id, df)
        plot_modal_comparison_bars(figures_dir, scenario_id, df)
        plot_modal_comparison_by_segment(figures_dir, scenario_id, df)
        
        print(f"✅ 已保存图表和报告到 {reports_dir} 和 {figures_dir}")

    # Cross-scenario summary
    if len(all_results_dfs) > 1:
        print(f"\n{'='*70}")
        print("跨场景汇总")
        print(f"{'='*70}")
        all_df = pd.concat(all_results_dfs, ignore_index=True)
        cross_summary = all_df.groupby("modal_variable")[["mean_rel_err_pct", "std_rel_err_pct"]].agg(["mean", "std"])
        print(cross_summary)
        cross_summary.to_csv(reports_dir / "liu_2016_cross_scenario_modal_summary.csv")

    print("\n✅ 完成!")


if __name__ == "__main__":
    main()
