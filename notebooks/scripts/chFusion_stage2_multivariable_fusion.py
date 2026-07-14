"""Stage 2: channel-level and variable-level multivariable fusion experiments.

Run:
    PYTHONPATH=src .venv/bin/python notebooks/scripts/chFusion_stage2_multivariable_fusion.py --all
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

_cwd = Path.cwd().resolve()
project_root = next((p for p in [_cwd, *_cwd.parents] if (p / "src").is_dir()), None)
if project_root is None:
    raise FileNotFoundError("Project root not found")
_src = project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from ble_analysis.bootstrap import init_notebook
from ble_analysis.chfusion import load_multichannel_for_scenario
from ble_analysis.multivariable_fusion import (
    CHANNEL_FUSION_METHODS,
    HIERARCHICAL_COMPARISON_METHODS,
    MULTIVARIABLE_VARIABLES,
    VARIABLE_FUSION_METHODS,
    MultivariableFusionConfig,
    quality_mrc_channel_fusion,
    run_channel_fusion_methods,
    run_hierarchical_comparisons,
    summarize_windows,
    variable_level_fusion,
)
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import FilterParams, _sliding_window_indices

DEFAULT_SCENARIOS = ("cs_091339", "cs_095806", "cs_102621")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 2 multivariable fusion")
    parser.add_argument("--scenario", type=str, default=None)
    parser.add_argument("--all", action="store_true")
    return parser.parse_args()


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for row in rows for k in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def segment_matrix(seg: dict, variable: str) -> np.ndarray:
    ch_map = seg["channels"]
    channels = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
    series = []
    for ch in channels:
        arr = np.asarray(ch_map[ch].get(variable, {}).get("bandpass_filtered", []), dtype=float)
        if arr.size and np.all(np.isfinite(arr)):
            series.append(arr)
    if not series:
        return np.empty((0, 0))
    n = min(len(x) for x in series)
    return np.column_stack([x[:n] for x in series])


def add_result_row(
    rows: list[dict],
    *,
    scenario: str,
    segment: str,
    method: str,
    variable: str,
    level: str,
    bpm_gt: float,
    window_index: int,
    result: dict,
) -> None:
    bpm_pred = result.get("bpm_pred", np.nan)
    rel = (
        abs(bpm_pred - bpm_gt) / bpm_gt * 100.0
        if bpm_gt and bpm_gt > 0 and np.isfinite(bpm_pred)
        else np.nan
    )
    rows.append(
        {
            "scenario": scenario,
            "segment": segment,
            "level": level,
            "method": method,
            "variable": variable,
            "bpm_gt": bpm_gt,
            "bpm_pred": bpm_pred,
            "rel_err_pct": rel,
            "window_index": window_index,
            "valid": bool(result.get("valid")),
            "n_tones": result.get("n_tones", np.nan),
            "n_valid_tones": result.get("n_valid_tones", np.nan),
            "quality_snr": result.get("quality_snr", np.nan),
            "quality_pr": result.get("quality_pr", np.nan),
            "quality_stability": result.get("quality_stability", np.nan),
            "quality": result.get("quality", np.nan),
            "outlier_frac": result.get("outlier_frac", np.nan),
            "variables_used": result.get("variables_used", ""),
            "selected_variable": result.get("selected_variable", ""),
            "failure_reason": "" if result.get("valid") else "invalid_estimate",
        }
    )


def run_scenario(scenario_id: str) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    scenario = load_scenario(scenario_id, project_root=project_root)
    print_scenario_summary(scenario)
    multichannel_by_var, fs, _ = load_multichannel_for_scenario(
        scenario,
        project_root=project_root,
        variables=MULTIVARIABLE_VARIABLES,
        filter_params=FilterParams(),
        cache_dir=str(project_root / "outputs" / "cache"),
        verbose=True,
    )
    cfg = MultivariableFusionConfig()
    stage2a_windows: list[dict] = []
    stage2b_windows: list[dict] = []

    for segment in sorted(scenario.segment_config.keys()):
        variable_data: dict[str, tuple[np.ndarray, dict]] = {}
        for variable in MULTIVARIABLE_VARIABLES:
            seg = multichannel_by_var[variable].get(segment)
            if seg is None or seg["metadata"].get("segment_type") == "apnea":
                continue
            data = segment_matrix(seg, variable)
            if data.shape[0] == 0:
                continue
            variable_data[variable] = (data, seg["metadata"])
        if not variable_data:
            continue

        common_len = min(data.shape[0] for data, _meta in variable_data.values())
        bpm_gt = next(meta.get("bpm_gt") for _data, meta in variable_data.values())
        fs_seg = float(next(meta.get("sampling_rate", fs) for _data, meta in variable_data.values()))
        win_len = int(round(cfg.window_length_sec * fs_seg))
        step_len = int(round(cfg.step_length_sec * fs_seg))
        if common_len < win_len:
            continue
        starts = _sliding_window_indices(common_len, win_len, step_len)

        for wi, st in enumerate(starts):
            ed = st + win_len
            variable_window_data = {
                var: data[st:ed, :]
                for var, (data, _meta) in variable_data.items()
            }

            quality_mrc_variable_results = {}
            for variable, win_data in variable_window_data.items():
                method_results = run_channel_fusion_methods(win_data, fs_seg, cfg)
                for method, result in method_results.items():
                    add_result_row(
                        stage2a_windows,
                        scenario=scenario_id,
                        segment=segment,
                        method=method,
                        variable=variable,
                        level="channel",
                        bpm_gt=bpm_gt,
                        window_index=wi,
                        result=result,
                    )
                quality_mrc_variable_results[variable] = quality_mrc_channel_fusion(
                    win_data, fs_seg, cfg
                )

            variable_results = variable_level_fusion(
                quality_mrc_variable_results, fs_seg, cfg, methods=VARIABLE_FUSION_METHODS
            )
            for method, result in variable_results.items():
                add_result_row(
                    stage2b_windows,
                    scenario=scenario_id,
                    segment=segment,
                    method=method,
                    variable="local+remote+phase",
                    level="variable",
                    bpm_gt=bpm_gt,
                    window_index=wi,
                    result=result,
                )

            hierarchical = run_hierarchical_comparisons(variable_window_data, fs_seg, cfg)
            for method, result in hierarchical.items():
                add_result_row(
                    stage2b_windows,
                    scenario=scenario_id,
                    segment=segment,
                    method=method,
                    variable="local+remote+phase",
                    level="hierarchical",
                    bpm_gt=bpm_gt,
                    window_index=wi,
                    result=result,
                )

    stage2a_summary = summarize_windows(
        stage2a_windows, ("scenario", "segment", "variable", "method")
    )
    stage2b_summary = summarize_windows(
        stage2b_windows, ("scenario", "segment", "level", "method")
    )
    return stage2a_summary, stage2a_windows, stage2b_summary, stage2b_windows


def plot_method_comparison(path: Path, rows: list[dict], *, title: str, group_key: str = "method") -> None:
    if not rows:
        return
    methods = sorted({r[group_key] for r in rows})
    vals = [
        float(np.nanmean([r["rel_err_pct"] for r in rows if r[group_key] == m]))
        for m in methods
    ]
    fig, ax = plt.subplots(figsize=(max(8, 0.55 * len(methods)), 4.2))
    ax.bar(methods, vals, color="#4c72b0", edgecolor="#333333")
    ax.set_ylabel("Mean relative error (%)")
    ax.set_title(title)
    ax.tick_params(axis="x", rotation=25)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_weight_distribution(path: Path, rows: list[dict]) -> None:
    method_rows = [r for r in rows if r.get("method") in ("snr_mrc", "quality_mrc")]
    if not method_rows:
        return
    methods = ["snr_mrc", "quality_mrc"]
    vals = [
        float(np.nanmean([r.get("quality", np.nan) for r in method_rows if r["method"] == m]))
        for m in methods
    ]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(methods, vals, color=["#55a868", "#8172b2"], edgecolor="#333333")
    ax.set_ylabel("Mean quality")
    ax.set_title("MRC quality distribution")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_adaptive_selection(path: Path, rows: list[dict]) -> None:
    counts: dict[str, int] = {}
    for r in rows:
        if r.get("method") != "adaptive_selection":
            continue
        selected = r.get("selected_variable") or "none"
        counts[selected] = counts.get(selected, 0) + 1
    if not counts:
        return
    labels = sorted(counts)
    vals = [counts[k] for k in labels]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(labels, vals, color="#c44e52", edgecolor="#333333")
    ax.set_ylabel("Window count")
    ax.set_title("Adaptive variable selection")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    init_notebook(project_root)
    scenario_ids = DEFAULT_SCENARIOS if args.all or args.scenario is None else (args.scenario,)
    reports_dir = project_root / "outputs" / "reports" / "multivariable_fusion"
    figures_dir = project_root / "outputs" / "figures" / "multivariable_fusion"
    reports_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    all_2a_summary: list[dict] = []
    all_2a_windows: list[dict] = []
    all_2b_summary: list[dict] = []
    all_2b_windows: list[dict] = []
    for scenario_id in scenario_ids:
        s2a, w2a, s2b, w2b = run_scenario(scenario_id)
        all_2a_summary.extend(s2a)
        all_2a_windows.extend(w2a)
        all_2b_summary.extend(s2b)
        all_2b_windows.extend(w2b)

    write_csv(reports_dir / "stage2a_channel_fusion_summary.csv", all_2a_summary)
    write_csv(reports_dir / "stage2a_channel_fusion_windows.csv", all_2a_windows)
    write_csv(reports_dir / "stage2b_variable_fusion_summary.csv", all_2b_summary)
    write_csv(reports_dir / "stage2b_variable_fusion_windows.csv", all_2b_windows)

    plot_method_comparison(
        figures_dir / "stage2a_channel_method_comparison.png",
        all_2a_summary,
        title="Stage 2A channel/tone fusion comparison",
    )
    plot_weight_distribution(
        figures_dir / "stage2a_mrc_weight_distribution.png",
        all_2a_windows,
    )
    plot_method_comparison(
        figures_dir / "stage2b_variable_method_comparison.png",
        all_2b_summary,
        title="Stage 2B variable/hierarchical fusion comparison",
    )
    plot_adaptive_selection(
        figures_dir / "stage2b_adaptive_selection_distribution.png",
        all_2b_windows,
    )
    print(f"Saved Stage 2 outputs to {reports_dir}")


if __name__ == "__main__":
    main()
