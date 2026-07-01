"""Generate diagnostic graphs for the Liu 2016 BLE CS benchmark."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
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
from ble_analysis.chfusion import ChFusionConfig, _overall_rel_error, load_multichannel_for_scenario
from ble_analysis.liu_2016 import (
    run_liu_2016_benchmark,
    _gather_liu_modal_window_data,
    _bpm_from_waveform,
)
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import BreathMetricParams, FilterParams

DEFAULT_SCENARIOS = ("cs_091339", "cs_095806", "cs_102621")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Liu 2016 diagnostic graphs")
    parser.add_argument("--scenario", type=str, default=None, help="Single scenario id")
    parser.add_argument("--all", action="store_true", help="Run all default scenarios")
    parser.add_argument("--segment", type=str, default=None, help="Single segment for diagnostic plots")
    return parser.parse_args()


def figure_path(figures_dir: Path, name: str) -> Path:
    return figures_dir / f"liu_2016_{name}.png"


def plot_window_bpm_curve(figures_dir: Path, scenario_id: str, seg_name: str, row: dict) -> None:
    bpm_est = row["liu_2016"]["bpm_per_window"]
    bpm_gt = row["bpm_gt"]
    windows = np.arange(len(bpm_est))
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(windows, bpm_est, marker="o", label="Liu-style BPM")
    ax.axhline(bpm_gt, color="red", linestyle="--", label=f"GT {bpm_gt:.1f}")
    ax.set_xlabel("Window index")
    ax.set_ylabel("BPM")
    ax.set_title(f"{scenario_id} segment {seg_name} — window-level BPM")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(figure_path(figures_dir, f"{scenario_id}_segment_{seg_name}_window_bpm_curve"), dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_window_error_hist(figures_dir: Path, scenario_id: str, seg_name: str, row: dict) -> None:
    bpm_est = row["liu_2016"]["bpm_per_window"]
    bpm_gt = row["bpm_gt"]
    errors = np.abs(bpm_est - bpm_gt)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(errors, bins=15, color="#4c72b0", edgecolor="#333", alpha=0.8)
    ax.set_xlabel("Absolute BPM error")
    ax.set_ylabel("Count")
    ax.set_title(f"{scenario_id} segment {seg_name} — window-level BPM error distribution")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(figure_path(figures_dir, f"{scenario_id}_segment_{seg_name}_window_error_hist"), dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_segment_error_bars(figures_dir: Path, scenario_id: str, results: dict) -> None:
    seg_names = []
    errors = []
    for seg_name, row in sorted(results.items(), key=lambda kv: kv[0]):
        if row is None:
            continue
        seg_names.append(seg_name)
        errors.append(float(row["liu_2016"]["bpm_rel_err"] * 100.0))
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(seg_names, errors, color="#55a868")
    ax.set_xlabel("Segment")
    ax.set_ylabel("Relative error (%)")
    ax.set_title(f"{scenario_id} — segment-level relative error")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(figure_path(figures_dir, f"{scenario_id}_segment_rel_err"), dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_tone_quality_scatter(figures_dir: Path, scenario_id: str, seg_name: str, row: dict, multichannel_by_var: dict, cfg: ChFusionConfig, metric_params: BreathMetricParams, fs: float) -> None:
    ref_seg = multichannel_by_var["remote_amplitudes"].get(seg_name)
    if ref_seg is None:
        return
    ch_map = ref_seg["channels"]
    ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
    first_win = 0
    ref_len = max(len(ch_map[c]["remote_amplitudes"]["bandpass_filtered"]) for c in ch_list)
    win_len = int(round(metric_params.window_length_sec * fs))
    step_len = int(round(metric_params.step_length_sec * fs))
    starts = np.arange(0, max(1, ref_len - win_len + 1), step_len)
    if len(starts) == 0:
        return
    st = starts[first_win]
    end = st + win_len
    data_matrix, eta_per_tone, rho_per_tone, labels = _gather_liu_modal_window_data(
        multichannel_by_var, seg_name, ch_list, st, end, fs, cfg
    )
    if data_matrix.size == 0 or len(labels) == 0:
        return
    bpm_per_tone = []
    for i in range(data_matrix.shape[1]):
        bpm_per_tone.append(_bpm_from_waveform(data_matrix[:, i], fs, cfg))
    bpm_per_tone = np.asarray(bpm_per_tone)
    fig, ax = plt.subplots(figsize=(10, 5))
    scatter = ax.scatter(eta_per_tone, rho_per_tone, c=bpm_per_tone, cmap="viridis", s=60, alpha=0.8)
    for i, label in enumerate(labels):
        ax.text(eta_per_tone[i], rho_per_tone[i], label, fontsize=7, alpha=0.8)
    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label("BPM per tone")
    ax.set_xlabel("Energy ratio η")
    ax.set_ylabel("Peak ratio ρ")
    ax.set_title(f"{scenario_id} segment {seg_name} — tone quality and BPM candidates")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(figure_path(figures_dir, f"{scenario_id}_segment_{seg_name}_tone_quality"), dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    env = init_notebook(project_root)
    figures_dir = env["FIGURES_DIR"]
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

    for scenario_id in scenario_ids:
        scenario = load_scenario(scenario_id, project_root=project_root)
        print(f"Scenario: {scenario_id}")
        print_scenario_summary(scenario)
        multichannel_by_var, fs, skipped = load_multichannel_for_scenario(
            scenario,
            project_root=project_root,
            filter_params=filter_params,
            cache_dir=str(cache_dir),
            verbose=False,
        )
        bench = run_liu_2016_benchmark(
            None,
            scenario.segment_config,
            filter_params=filter_params,
            metric_params=metric_params,
            config=cfg,
            verbose=False,
            cache_dir=str(cache_dir),
            multichannel_by_var=multichannel_by_var,
        )
        report_path = reports_dir / f"liu_2016_{scenario_id}_diagnostics.npy"
        np.save(report_path, bench, allow_pickle=True)
        print(f"Saved benchmark cache: {report_path}")

        plot_segment_error_bars(figures_dir, scenario_id, bench["results"])

        plot_seg_names = [args.segment] if args.segment else [seg for seg in bench["results"].keys() if bench["results"][seg] is not None][:3]
        for seg_name in plot_seg_names:
            if seg_name not in bench["results"] or bench["results"][seg_name] is None:
                continue
            row = bench["results"][seg_name]
            plot_window_bpm_curve(figures_dir, scenario_id, seg_name, row)
            plot_window_error_hist(figures_dir, scenario_id, seg_name, row)
            try:
                plot_tone_quality_scatter(figures_dir, scenario_id, seg_name, row, multichannel_by_var, cfg, metric_params, fs)
            except Exception as exc:
                print(f"Warning: failed to generate tone quality scatter for {scenario_id}/{seg_name}: {exc}")

    print("Done.")


if __name__ == "__main__":
    main()
