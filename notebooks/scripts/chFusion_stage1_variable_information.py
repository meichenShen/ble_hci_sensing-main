"""Stage 1: single-variable information analysis for BLE multivariable fusion.

Run:
    PYTHONPATH=src .venv/bin/python notebooks/scripts/chFusion_stage1_variable_information.py --all
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
    MULTIVARIABLE_VARIABLES,
    MultivariableFusionConfig,
    quality_mrc_channel_fusion,
    summarize_windows,
)
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import FilterParams, _sliding_window_indices

DEFAULT_SCENARIOS = ("cs_091339", "cs_095806", "cs_102621")
METHOD = "quality_mrc_single_variable_reference"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 1 variable information analysis")
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


def segment_matrix(seg: dict, variable: str) -> tuple[np.ndarray, list]:
    ch_map = seg["channels"]
    channels = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
    series = []
    kept = []
    for ch in channels:
        block = ch_map[ch].get(variable, {})
        arr = np.asarray(block.get("bandpass_filtered", []), dtype=float)
        if arr.size and np.all(np.isfinite(arr)):
            series.append(arr)
            kept.append(ch)
    if not series:
        return np.empty((0, 0)), []
    n = min(len(x) for x in series)
    return np.column_stack([x[:n] for x in series]), kept


def run_scenario(scenario_id: str, reports_dir: Path, figures_dir: Path) -> tuple[list[dict], list[dict]]:
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
    window_rows: list[dict] = []

    for variable in MULTIVARIABLE_VARIABLES:
        for segment, seg in sorted(multichannel_by_var[variable].items()):
            if seg is None or seg["metadata"].get("segment_type") == "apnea":
                continue
            bpm_gt = seg["metadata"].get("bpm_gt")
            fs_seg = float(seg["metadata"].get("sampling_rate", fs))
            data, channels = segment_matrix(seg, variable)
            win_len = int(round(cfg.window_length_sec * fs_seg))
            step_len = int(round(cfg.step_length_sec * fs_seg))
            if data.shape[0] < win_len or data.shape[1] == 0:
                window_rows.append(
                    {
                        "scenario": scenario_id,
                        "segment": segment,
                        "variable": variable,
                        "method": METHOD,
                        "bpm_gt": bpm_gt,
                        "bpm_pred": np.nan,
                        "rel_err_pct": np.nan,
                        "window_index": 0,
                        "n_windows": 0,
                        "valid": False,
                        "failure_reason": "segment_too_short_or_no_tones",
                    }
                )
                continue
            starts = _sliding_window_indices(data.shape[0], win_len, step_len)
            for wi, st in enumerate(starts):
                ed = st + win_len
                result = quality_mrc_channel_fusion(data[st:ed, :], fs_seg, cfg)
                bpm_pred = result.get("bpm_pred", np.nan)
                rel = (
                    abs(bpm_pred - bpm_gt) / bpm_gt * 100.0
                    if bpm_gt and bpm_gt > 0 and np.isfinite(bpm_pred)
                    else np.nan
                )
                window_rows.append(
                    {
                        "scenario": scenario_id,
                        "segment": segment,
                        "variable": variable,
                        "method": METHOD,
                        "bpm_gt": bpm_gt,
                        "bpm_pred": bpm_pred,
                        "rel_err_pct": rel,
                        "window_index": wi,
                        "window_start": st,
                        "window_end": ed,
                        "valid": bool(result.get("valid")),
                        "n_tones": result.get("n_tones"),
                        "n_valid_tones": result.get("n_valid_tones"),
                        "quality_snr": result.get("quality_snr"),
                        "quality_pr": result.get("quality_pr"),
                        "quality_stability": result.get("quality_stability"),
                        "outlier_frac": result.get("outlier_frac"),
                        "failure_reason": "" if result.get("valid") else "invalid_estimate",
                    }
                )

    summary = summarize_windows(window_rows, ("scenario", "segment", "variable"))
    return summary, window_rows


def plot_quality_heatmap(path: Path, summary: list[dict]) -> None:
    if not summary:
        return
    variables = list(MULTIVARIABLE_VARIABLES)
    labels = sorted({f"{r['scenario']} {r['segment']}" for r in summary})
    matrix = np.full((len(variables), len(labels)), np.nan)
    for r in summary:
        i = variables.index(r["variable"])
        j = labels.index(f"{r['scenario']} {r['segment']}")
        matrix[i, j] = r.get("mean_pr", np.nan)
    fig, ax = plt.subplots(figsize=(max(8, 0.55 * len(labels)), 3.8))
    im = ax.imshow(matrix, aspect="auto", cmap="viridis")
    ax.set_yticks(range(len(variables)), variables)
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
    ax.set_title("Stage 1 variable periodicity quality")
    ax.set_xlabel("Scenario segment")
    ax.set_ylabel("Variable")
    fig.colorbar(im, ax=ax, label="Mean pr")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_validity(path: Path, summary: list[dict]) -> None:
    if not summary:
        return
    variables = list(MULTIVARIABLE_VARIABLES)
    vals = [
        float(np.nanmean([r["valid_window_rate"] for r in summary if r["variable"] == v]))
        for v in variables
    ]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(variables, vals, color=["#4c72b0", "#55a868", "#c44e52"], edgecolor="#333333")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Valid window rate")
    ax.set_title("Stage 1 variable coverage")
    ax.tick_params(axis="x", rotation=15)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_failure_modes(path: Path, summary: list[dict]) -> None:
    counts: dict[str, int] = {}
    for r in summary:
        reason = r.get("failure_reason", "") or "valid"
        counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return
    labels = sorted(counts)
    vals = [counts[k] for k in labels]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(labels, vals, color="#dd8452", edgecolor="#333333")
    ax.set_ylabel("Segment-variable count")
    ax.set_title("Stage 1 failure modes")
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

    all_summary: list[dict] = []
    all_windows: list[dict] = []
    for scenario_id in scenario_ids:
        summary, windows = run_scenario(scenario_id, reports_dir, figures_dir)
        all_summary.extend(summary)
        all_windows.extend(windows)

    write_csv(reports_dir / "stage1_variable_information_summary.csv", all_summary)
    write_csv(reports_dir / "stage1_variable_window_diagnostics.csv", all_windows)
    plot_quality_heatmap(figures_dir / "stage1_variable_quality_heatmap.png", all_summary)
    plot_validity(figures_dir / "stage1_variable_validity_coverage.png", all_summary)
    plot_failure_modes(figures_dir / "stage1_variable_failure_modes.png", all_summary)
    print(f"Saved Stage 1 outputs to {reports_dir}")


if __name__ == "__main__":
    main()
