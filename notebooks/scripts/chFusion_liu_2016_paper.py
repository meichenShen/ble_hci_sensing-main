"""Strict Liu 2016 paper reproduction on BLE CS amplitude tones.

Run:
    PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016_paper.py --scenario cs_091339
    PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016_paper.py --all

Outputs are organized under:
    outputs/reports/liu_2016_paper/
    outputs/figures/liu_2016_paper/
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
    raise FileNotFoundError("Project root not found (missing src/ directory)")

_src = project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from ble_analysis.bootstrap import init_notebook
from ble_analysis.data import load_ble_frames
from ble_analysis.liu_2016 import Liu2016PaperConfig, run_liu_2016_paper_benchmark
from ble_analysis.scenarios import load_scenario, print_scenario_summary

DEFAULT_SCENARIOS = ("cs_091339", "cs_095806", "cs_102621")
METHOD = "liu_2016_paper"
SUMMARY_FIELDS = [
    "scenario",
    "segment",
    "method",
    "variable",
    "bpm_gt",
    "bpm_pred",
    "mean_rel_err_pct",
    "std_rel_err_pct",
    "n_windows",
    "median_n_tones",
    "median_n_kept",
    "mean_outlier_frac",
    "mean_pr",
    "zscore_scale",
    "breath_freq_low",
    "breath_freq_high",
    "preprocessing_mode",
    "skip_reason",
]
SEGMENT_ORDER = ("1a", "1b", "2a", "2b", "3", "4a", "4b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict Liu 2016 paper reproduction")
    parser.add_argument("--scenario", type=str, default=None, help="Single scenario id")
    parser.add_argument("--all", action="store_true", help="Run all default scenarios")
    parser.add_argument("--variable", type=str, default="amplitudes", help="Amplitude-like variable")
    return parser.parse_args()


def _summary_rows(scenario_id: str, variable: str, bench: dict) -> list[dict]:
    rows = []
    for seg_name, row in sorted(bench["results"].items()):
        if row is None:
            continue
        stat = row["liu_2016_paper"]
        rows.append({
            "scenario": scenario_id,
            "segment": seg_name,
            "method": METHOD,
            "variable": variable,
            "bpm_gt": row.get("bpm_gt"),
            "bpm_pred": stat.get("bpm_mean"),
            "mean_rel_err_pct": stat.get("bpm_rel_err", np.nan) * 100.0,
            "std_rel_err_pct": stat.get("bpm_rel_err_std", np.nan) * 100.0,
            "n_windows": stat.get("n_windows"),
            "median_n_tones": stat.get("median_n_tones"),
            "median_n_kept": stat.get("median_n_kept"),
            "mean_outlier_frac": stat.get("mean_outlier_frac"),
            "mean_pr": stat.get("mean_pr"),
            "zscore_scale": stat.get("zscore_scale"),
            "breath_freq_low": stat.get("breath_freq_low"),
            "breath_freq_high": stat.get("breath_freq_high"),
            "preprocessing_mode": stat.get("preprocessing_mode"),
            "skip_reason": stat.get("skip_reason"),
        })
    return rows


def _window_rows(scenario_id: str, variable: str, bench: dict) -> list[dict]:
    rows = []
    for seg_name, row in sorted(bench["results"].items()):
        if row is None:
            continue
        bpm_gt = row.get("bpm_gt")
        for win in row.get("window_results", []):
            out = dict(win)
            out.update({
                "scenario": scenario_id,
                "method": METHOD,
                "variable": variable,
                "bpm_gt": bpm_gt,
            })
            rows.append(out)
    return rows


def _diagnostic_rows(scenario_id: str, variable: str, bench: dict) -> list[dict]:
    rows = []
    for seg_name, row in sorted(bench["results"].items()):
        if row is None:
            continue
        for diag in row.get("diagnostics", []):
            out = dict(diag)
            out.update({
                "scenario": scenario_id,
                "method": METHOD,
                "variable": variable,
                "segment": seg_name,
            })
            rows.append(out)
    return rows


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    if fields is None:
        field_set = set()
        for row in rows:
            field_set.update(row.keys())
        fields = sorted(field_set)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def plot_segment_errors(figures_dir: Path, scenario_id: str, rows: list[dict]) -> None:
    if not rows:
        return
    labels = [r["segment"] for r in rows]
    vals = [r["mean_rel_err_pct"] if np.isfinite(r["mean_rel_err_pct"]) else 0.0 for r in rows]
    colors = ["#4c72b0" if not r.get("skip_reason", "") else "#c8c8c8" for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4))
    bars = ax.bar(labels, vals, color=colors, edgecolor="#333333")
    for bar, row in zip(bars, rows):
        if row.get("skip_reason", ""):
            bar.set_hatch("//")
    ax.set_xlabel("Segment")
    ax.set_ylabel("Relative error (%)")
    ax.set_title(f"Paper-faithful Liu 2016 on BLE amplitude tones - {scenario_id}")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(figures_dir / f"liu_2016_paper_{scenario_id}_segment_errors.png", dpi=200)
    plt.close(fig)


def plot_window_diagnostics(figures_dir: Path, scenario_id: str, rows: list[dict]) -> None:
    valid_rows = [r for r in rows if np.isfinite(r.get("bpm_pred", np.nan))]
    if not valid_rows:
        return
    gt_by_segment = {r["segment"]: r["bpm_gt"] for r in valid_rows}
    for seg in sorted({r["segment"] for r in valid_rows}):
        seg_rows = [r for r in valid_rows if r["segment"] == seg]
        windows = [int(r["window_index"]) for r in seg_rows]
        bpm = [float(r["bpm_pred"]) for r in seg_rows]
        n_kept = [float(r["n_kept"]) for r in seg_rows]
        mean_pr = [float(r["mean_pr"]) if np.isfinite(float(r["mean_pr"])) else np.nan for r in seg_rows]
        outlier_frac = [float(r["outlier_frac"]) for r in seg_rows]

        fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
        axes[0].plot(windows, bpm, color="#4c72b0", marker="o", markersize=3)
        axes[0].axhline(gt_by_segment[seg], color="#c44e52", linestyle="--", label="GT")
        axes[0].set_ylabel("BPM")
        axes[0].legend(loc="best")
        axes[0].grid(alpha=0.25)

        axes[1].plot(windows, n_kept, color="#55a868", marker="o", markersize=3)
        axes[1].set_ylabel("Kept tones")
        axes[1].grid(alpha=0.25)

        axes[2].plot(windows, mean_pr, color="#8172b2", marker="o", markersize=3, label="mean pr")
        axes[2].plot(windows, outlier_frac, color="#ccb974", marker=".", label="outlier frac")
        axes[2].set_ylabel("Quality")
        axes[2].set_xlabel("Window index")
        axes[2].legend(loc="best")
        axes[2].grid(alpha=0.25)

        fig.suptitle(f"{scenario_id} segment {seg} - Liu 2016 paper window diagnostics")
        fig.tight_layout()
        fig.savefig(figures_dir / f"liu_2016_paper_{scenario_id}_segment_{seg}_window_diagnostics.png", dpi=200)
        plt.close(fig)


def plot_skip_reason_counts(figures_dir: Path, scenario_id: str, rows: list[dict]) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        reason = row.get("skip_reason", "") or "valid"
        counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return
    labels = sorted(counts)
    vals = [counts[k] for k in labels]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(labels, vals, color="#dd8452", edgecolor="#333333")
    ax.set_xlabel("Preprocessing status")
    ax.set_ylabel("Tone count")
    ax.set_title(f"{scenario_id} - preprocessing diagnostics")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(figures_dir / f"liu_2016_paper_{scenario_id}_preprocessing_status.png", dpi=200)
    plt.close(fig)


def plot_cross_summary(figures_dir: Path, rows: list[dict]) -> None:
    by_scenario = {}
    for row in rows:
        if row.get("skip_reason", "") or not np.isfinite(row["mean_rel_err_pct"]):
            continue
        by_scenario.setdefault(row["scenario"], []).append(row["mean_rel_err_pct"])
    if not by_scenario:
        return
    labels = sorted(by_scenario)
    vals = [float(np.mean(by_scenario[s])) for s in labels]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(labels, vals, color="#55a868", edgecolor="#333333")
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Mean relative error (%)")
    ax.set_title("Paper-faithful Liu 2016 on BLE amplitude tones")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(figures_dir / "liu_2016_paper_cross_scenario_summary.png", dpi=200)
    plt.close(fig)


def plot_coverage_heatmap(figures_dir: Path, rows: list[dict]) -> None:
    scenarios = sorted({r["scenario"] for r in rows})
    segments = [s for s in SEGMENT_ORDER if any(r["segment"] == s for r in rows)]
    if not scenarios or not segments:
        return
    mat = np.full((len(scenarios), len(segments)), np.nan)
    for i, scenario in enumerate(scenarios):
        for j, segment in enumerate(segments):
            match = next((r for r in rows if r["scenario"] == scenario and r["segment"] == segment), None)
            if match is None:
                continue
            mat[i, j] = 1.0 if not match.get("skip_reason", "") else 0.0
    fig, ax = plt.subplots(figsize=(9, 3))
    im = ax.imshow(mat, vmin=0, vmax=1, cmap="YlGn")
    ax.set_xticks(range(len(segments)), segments)
    ax.set_yticks(range(len(scenarios)), scenarios)
    ax.set_title("Liu 2016 paper reproduction coverage")
    for i in range(len(scenarios)):
        for j in range(len(segments)):
            label = "valid" if mat[i, j] == 1 else "skip"
            ax.text(j, i, label, ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, ticks=[0, 1], label="valid segment")
    fig.tight_layout()
    fig.savefig(figures_dir / "liu_2016_paper_coverage_heatmap.png", dpi=200)
    plt.close(fig)


def _format_pct(value) -> str:
    return "无" if not np.isfinite(value) else f"{value:.2f}%"


def write_markdown_results_report(path: Path, rows: list[dict]) -> None:
    valid_rows = [r for r in rows if not r.get("skip_reason", "") and np.isfinite(r["mean_rel_err_pct"])]
    skipped_rows = [r for r in rows if r.get("skip_reason", "")]
    scenario_stats = {}
    for row in valid_rows:
        scenario_stats.setdefault(row["scenario"], []).append(row["mean_rel_err_pct"])
    cross_mean = float(np.mean([r["mean_rel_err_pct"] for r in valid_rows])) if valid_rows else np.nan
    total = len(rows)
    valid = len(valid_rows)

    lines = [
        "# Liu 2016 严格复现实验结果报告",
        "",
        "## 结果摘要",
        "",
        f"- 严格复现方法：`liu_2016_paper`。",
        f"- 主输入变量：`amplitudes`。",
        f"- 有效呼吸段：{valid}/{total}。",
        f"- 有效段跨场景平均相对误差：{_format_pct(cross_mean)}。",
        "- 无效段主要来自 BLE 低采样率下 `db4` level 4 小波分解样本数不足。",
        "",
        "## 分场景结果",
        "",
        "| 场景 | 有效段数 | 平均相对误差 | 说明 |",
        "|---|---:|---:|---|",
    ]
    for scenario in sorted({r["scenario"] for r in rows}):
        vals = scenario_stats.get(scenario, [])
        n_valid = len(vals)
        n_total = sum(1 for r in rows if r["scenario"] == scenario)
        mean = float(np.mean(vals)) if vals else np.nan
        note = "可计算" if vals else "全部跳过"
        lines.append(f"| `{scenario}` | {n_valid}/{n_total} | {_format_pct(mean)} | {note} |")

    lines.extend([
        "",
        "## 段落级结果",
        "",
        "| 场景 | 段落 | 真实 BPM | 预测 BPM | 相对误差 | 窗口数 | 保留频点数中位数 | 跳过原因 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for row in rows:
        bpm_pred = "无" if not np.isfinite(row["bpm_pred"]) else f"{row['bpm_pred']:.2f}"
        lines.append(
            f"| `{row['scenario']}` | `{row['segment']}` | {row['bpm_gt']:.3f} | "
            f"{bpm_pred} | {_format_pct(row['mean_rel_err_pct'])} | "
            f"{row['n_windows']} | {row['median_n_kept']} | {row.get('skip_reason', '')} |"
        )

    lines.extend([
        "",
        "## 分步图表",
        "",
        "- `outputs/figures/liu_2016_paper/liu_2016_paper_coverage_heatmap.png`：显示每个场景/段落是否满足严格预处理并产生有效结果。",
        "- `outputs/figures/liu_2016_paper/liu_2016_paper_{scenario}_preprocessing_status.png`：统计每个场景逐频点预处理状态。",
        "- `outputs/figures/liu_2016_paper/liu_2016_paper_{scenario}_segment_errors.png`：段落级相对误差，跳过段以灰色斜线标注。",
        "- `outputs/figures/liu_2016_paper/liu_2016_paper_{scenario}_segment_{segment}_window_diagnostics.png`：窗口级 BPM、保留频点数量、`pr` 与离群比例。",
        "- `outputs/figures/liu_2016_paper/liu_2016_paper_cross_scenario_summary.png`：有效段的跨场景误差摘要。",
        "",
        "### 推荐主图",
        "",
        "**图 1：严格复现有效段覆盖情况**",
        "",
        "![严格复现有效段覆盖情况](../../figures/liu_2016_paper/liu_2016_paper_coverage_heatmap.png)",
        "",
        "**图 2：有效段跨场景平均误差**",
        "",
        "![有效段跨场景平均误差](../../figures/liu_2016_paper/liu_2016_paper_cross_scenario_summary.png)",
        "",
        "**图 3：各场景段落级误差**",
        "",
        "![cs_091339 段落级误差](../../figures/liu_2016_paper/liu_2016_paper_cs_091339_segment_errors.png)",
        "",
        "![cs_095806 段落级误差](../../figures/liu_2016_paper/liu_2016_paper_cs_095806_segment_errors.png)",
        "",
        "![cs_102621 段落级误差](../../figures/liu_2016_paper/liu_2016_paper_cs_102621_segment_errors.png)",
        "",
        "**图 4：逐频点预处理状态**",
        "",
        "![cs_091339 逐频点预处理状态](../../figures/liu_2016_paper/liu_2016_paper_cs_091339_preprocessing_status.png)",
        "",
        "![cs_095806 逐频点预处理状态](../../figures/liu_2016_paper/liu_2016_paper_cs_095806_preprocessing_status.png)",
        "",
        "![cs_102621 逐频点预处理状态](../../figures/liu_2016_paper/liu_2016_paper_cs_102621_preprocessing_status.png)",
        "",
        "## 结果解释",
        "",
        "当前结果更像是一次严格复现约束下的可行性验证，而不是优化后的 BLE 算法性能展示。Liu 2016 原始数据约 20 Hz，而当前 BLE CS 数据约 1.7-1.9 Hz；在严格保留 `db4` level 4 且不降级的前提下，短段或频点样本不足会被跳过。因此，有效段数量本身就是一个重要结论。",
        "",
        "从有效段看，预测 BPM 往往偏向较低频率，尤其在较高真实 BPM 段落上误差较大。这说明 Liu 2016 的原始预处理和频率细化流程在 BLE 低采样率、短段、稀疏频点条件下会受到明显限制。后续如果要提升 BLE 表现，应另列为 `liu_eta_rho_adapted` 或其它 BLE 适配方法，不能混入 `liu_2016_paper`。",
        "",
        "## 输出表格",
        "",
        "- `outputs/reports/liu_2016_paper/summary/liu_2016_paper_{scenario}_summary.csv`",
        "- `outputs/reports/liu_2016_paper/windows/liu_2016_paper_{scenario}_window_results.csv`",
        "- `outputs/reports/liu_2016_paper/diagnostics/liu_2016_paper_{scenario}_diagnostics.csv`",
        "- `outputs/reports/liu_2016_paper/liu_2016_paper_cross_scenario_summary.csv`",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_one(scenario_id: str, variable: str, cfg: Liu2016PaperConfig, reports_dir: Path, figures_dir: Path) -> list[dict]:
    scenario = load_scenario(scenario_id, project_root=project_root)
    print(f"\n{'=' * 70}")
    print_scenario_summary(scenario)
    _data, frames = load_ble_frames(scenario.resolve_data_path(project_root), verbose=False)
    bench = run_liu_2016_paper_benchmark(
        frames,
        scenario.segment_config,
        variable=variable,
        config=cfg,
        verbose=True,
    )
    summary = _summary_rows(scenario_id, variable, bench)
    windows = _window_rows(scenario_id, variable, bench)
    diagnostics = _diagnostic_rows(scenario_id, variable, bench)
    write_csv(reports_dir / "summary" / f"liu_2016_paper_{scenario_id}_summary.csv", summary, SUMMARY_FIELDS)
    write_csv(reports_dir / "windows" / f"liu_2016_paper_{scenario_id}_window_results.csv", windows)
    write_csv(reports_dir / "diagnostics" / f"liu_2016_paper_{scenario_id}_diagnostics.csv", diagnostics)
    npy_dir = reports_dir / "npy"
    npy_dir.mkdir(parents=True, exist_ok=True)
    np.save(npy_dir / f"liu_2016_paper_{scenario_id}_results.npy", bench, allow_pickle=True)
    plot_segment_errors(figures_dir, scenario_id, summary)
    plot_window_diagnostics(figures_dir, scenario_id, windows)
    plot_skip_reason_counts(figures_dir, scenario_id, diagnostics)
    return summary


def main() -> None:
    args = parse_args()
    env = init_notebook(project_root)
    reports_dir = env["REPORTS_DIR"] / "liu_2016_paper"
    figures_dir = env["FIGURES_DIR"] / "liu_2016_paper"
    reports_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    cfg = Liu2016PaperConfig()
    scenario_ids = list(DEFAULT_SCENARIOS) if args.all or args.scenario is None else [args.scenario]
    all_rows = []
    for scenario_id in scenario_ids:
        all_rows.extend(run_one(scenario_id, args.variable, cfg, reports_dir, figures_dir))
    if len(scenario_ids) > 1:
        write_csv(reports_dir / "liu_2016_paper_cross_scenario_summary.csv", all_rows, SUMMARY_FIELDS)
        plot_cross_summary(figures_dir, all_rows)
        plot_coverage_heatmap(figures_dir, all_rows)
    results_report = reports_dir / "liu_2016_paper_results_report.md"
    write_markdown_results_report(results_report, all_rows)
    print("\nDone.")
    print("Method report: docs/reports/liu_2016_report.md")
    print(f"Generated results report: {results_report}")


if __name__ == "__main__":
    main()
