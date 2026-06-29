"""分段结果与 Ground Truth 的误差评估。

收集 BPM / IE / apnea 估计值与 GT 的对比数据，
绘制散点图、相对误差柱状图、窗级箱线图/小提琴图，并保存 ``.npy`` 报告。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np


def _resolve_gt(seg_name, seg_proc, segment_config, segment_data, key_meta):
    metadata = seg_proc.get("metadata", {})
    v = metadata.get(key_meta)
    if v is not None:
        return v
    sc = segment_config.get(seg_name) if segment_config else None
    if isinstance(sc, dict):
        v = sc.get(key_meta)
        if v is not None:
            return v
    sd = segment_data.get(seg_name) if segment_data else None
    if isinstance(sd, dict):
        return sd.get(key_meta)
    return None


def collect_error_metrics(
    segment_processed: Dict,
    segment_config: Optional[Dict] = None,
    segment_data: Optional[Dict] = None,
) -> Tuple[list, list, list]:
    """从 segment_processed 收集可与 GT 对比的 BPM / IE / apnea 误差条目。

    Returns
    -------
    bpm_data, ie_data, apnea_data : list
        供 ``plot_error_analysis`` 使用的元组列表。
    """
    segment_config = segment_config or {}
    segment_data = segment_data or {}
    bpm_data, ie_data, apnea_data = [], [], []

    for seg_name in sorted(segment_processed.keys()):
        seg_proc = segment_processed[seg_name]
        if seg_proc is None:
            continue

        bpm_gt = _resolve_gt(seg_name, seg_proc, segment_config, segment_data, "bpm_gt")
        ie_gt = _resolve_gt(seg_name, seg_proc, segment_config, segment_data, "ie_gt")
        apnea_gt = _resolve_gt(
            seg_name, seg_proc, segment_config, segment_data, "apnea_gt_sec"
        )

        if "breathing_analysis" in seg_proc:
            for var_name, analysis in seg_proc["breathing_analysis"].items():
                bpm_est = analysis.get("breathing_rate", np.nan)
                bpm_rel_err = analysis.get("bpm_rel_err")
                bpm_rel_err_std = analysis.get("bpm_rel_err_std", 0.0)
                if bpm_gt is not None and not np.isnan(bpm_est):
                    if bpm_rel_err is None:
                        bpm_rel_err = abs(bpm_est - bpm_gt) / bpm_gt if bpm_gt > 0 else np.nan
                    bpm_data.append(
                        (seg_name, var_name, bpm_est, bpm_gt, bpm_rel_err, bpm_rel_err_std)
                    )

                ie_est = analysis.get("ie_ratio", np.nan)
                ie_rel_err = analysis.get("ie_rel_err")
                ie_rel_err_std = analysis.get("ie_rel_err_std", 0.0)
                if ie_gt is not None and not np.isnan(ie_est):
                    if ie_rel_err is None:
                        ie_rel_err = abs(ie_est - ie_gt) / ie_gt if ie_gt > 0 else np.nan
                    ie_data.append(
                        (seg_name, var_name, ie_est, ie_gt, ie_rel_err, ie_rel_err_std)
                    )

        if "apnea_analysis" in seg_proc:
            aa = seg_proc["apnea_analysis"]
            apnea_est = aa.get("apnea_est_sec", np.nan)
            final_gt = aa.get("apnea_gt_sec") or apnea_gt
            if final_gt is not None and not np.isnan(apnea_est):
                rel = abs(apnea_est - final_gt) / final_gt if final_gt > 0 else np.nan
                apnea_data.append((seg_name, apnea_est, final_gt, rel))

    return bpm_data, ie_data, apnea_data


def _scatter_with_ideal(ax, gt_vals, est_vals, xlabel, ylabel, title):
    ax.scatter(
        gt_vals, est_vals, s=100, alpha=0.7, edgecolors="black", linewidths=1.5
    )
    min_val = min(min(gt_vals), min(est_vals))
    max_val = max(max(gt_vals), max(est_vals))
    ax.plot([min_val, max_val], [min_val, max_val], "r--", linewidth=2, alpha=0.8)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontweight="bold")
    ax.grid(True, alpha=0.3)


def _bar_rel_error(ax, data_rows, color, title):
    rel_errors = [
        d[4] * 100 if d[4] is not None and not np.isnan(d[4]) else 0 for d in data_rows
    ]
    yerr = [
        (d[5] * 100) if len(d) > 5 and d[5] is not None and not np.isnan(d[5]) else 0.0
        for d in data_rows
    ]
    labels = [f"{d[0]}\n({d[1]})" for d in data_rows]
    ax.bar(
        range(len(rel_errors)),
        rel_errors,
        yerr=yerr,
        capsize=4,
        alpha=0.7,
        color=color,
        edgecolor="black",
    )
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Relative Error (%)")
    ax.set_title(f"{title} (mean {np.mean(rel_errors):.1f}%)", fontweight="bold")
    ax.grid(True, alpha=0.3, axis="y")


def plot_error_analysis(
    bpm_data,
    ie_data,
    apnea_data,
    *,
    save_path: Optional[Path] = None,
    show: bool = True,
) -> Optional[plt.Figure]:
    """绘制 BPM/IE/apnea 的 GT 对比散点图与相对误差柱状图。"""
    n_panels = (2 if bpm_data else 0) + (2 if ie_data else 0) + (2 if apnea_data else 0)
    if n_panels == 0:
        print("⚠️  无 GT 数据可绘制误差图")
        return None

    n_rows = max(1, (n_panels + 1) // 2)
    fig = plt.figure(figsize=(16, 4 * n_rows))
    plot_idx = 1

    if bpm_data:
        ax = plt.subplot(n_rows, 2, plot_idx)
        _scatter_with_ideal(
            ax,
            [d[3] for d in bpm_data],
            [d[2] for d in bpm_data],
            "Ground Truth BPM",
            "Estimated BPM",
            f"BPM (n={len(bpm_data)})",
        )
        plot_idx += 1
        ax = plt.subplot(n_rows, 2, plot_idx)
        _bar_rel_error(ax, bpm_data, "steelblue", "BPM Relative Error")
        plot_idx += 1

    if ie_data:
        ax = plt.subplot(n_rows, 2, plot_idx)
        _scatter_with_ideal(
            ax,
            [d[3] for d in ie_data],
            [d[2] for d in ie_data],
            "Ground Truth IE",
            "Estimated IE",
            f"IE Ratio (n={len(ie_data)})",
        )
        plot_idx += 1
        ax = plt.subplot(n_rows, 2, plot_idx)
        _bar_rel_error(ax, ie_data, "coral", "IE Relative Error")
        plot_idx += 1

    if apnea_data:
        ax = plt.subplot(n_rows, 2, plot_idx)
        _scatter_with_ideal(
            ax,
            [d[2] for d in apnea_data],
            [d[1] for d in apnea_data],
            "GT Apnea (s)",
            "Est Apnea (s)",
            f"Apnea (n={len(apnea_data)})",
        )
        plot_idx += 1
        ax = plt.subplot(n_rows, 2, plot_idx)
        rel = [d[3] * 100 if not np.isnan(d[3]) else 0 for d in apnea_data]
        labels = [d[0] for d in apnea_data]
        ax.bar(range(len(rel)), rel, alpha=0.7, color="mediumpurple", edgecolor="black")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_ylabel("Relative Error (%)")
        ax.set_title(f"Apnea Relative Error (mean {np.mean(rel):.1f}%)", fontweight="bold")
        ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path)
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig


def plot_window_error_distribution(
    segment_processed,
    segment_config=None,
    segment_data=None,
    *,
    save_path: Optional[Path] = None,
    show: bool = True,
) -> Optional[plt.Figure]:
    """绘制各滑窗 BPM/IE 相对误差的箱线图与小提琴图。"""
    segment_config = segment_config or {}
    segment_data = segment_data or {}
    bpm_series, bpm_labels, ie_series, ie_labels = [], [], [], []

    for seg_name in sorted(segment_processed.keys()):
        proc = segment_processed[seg_name]
        if proc is None or "breathing_analysis" not in proc:
            continue
        bpm_gt = _resolve_gt(seg_name, proc, segment_config, segment_data, "bpm_gt")
        ie_gt = _resolve_gt(seg_name, proc, segment_config, segment_data, "ie_gt")
        for var_name, analysis in proc["breathing_analysis"].items():
            ab = analysis.get("bpm_per_window")
            if bpm_gt and ab is not None and len(ab) > 0:
                ab = np.asarray(ab, float)
                m = np.isfinite(ab)
                rel = np.abs(ab[m] - bpm_gt) / bpm_gt * 100.0
                if rel.size > 0:
                    bpm_series.append(rel)
                    bpm_labels.append(f"{seg_name}\n({var_name})")
            ai = analysis.get("ie_per_window")
            if ie_gt and ai is not None and len(ai) > 0:
                ai = np.asarray(ai, float)
                m = np.isfinite(ai)
                rel = np.abs(ai[m] - ie_gt) / ie_gt * 100.0
                if rel.size > 0:
                    ie_series.append(rel)
                    ie_labels.append(f"{seg_name}\n({var_name})")

    if not bpm_series and not ie_series:
        print("⚠️  无窗级误差数据")
        return None

    nrows = int(bool(bpm_series)) + int(bool(ie_series))
    fig, axes = plt.subplots(nrows, 2, figsize=(14, 4.5 * nrows), squeeze=False)
    row = 0
    if bpm_series:
        axes[row, 0].boxplot(bpm_series, labels=bpm_labels)
        axes[row, 0].set_title("BPM window rel. error (%)")
        axes[row, 0].tick_params(axis="x", rotation=45)
        axes[row, 1].violinplot(bpm_series, showmeans=True)
        axes[row, 1].set_title("BPM window rel. error violin")
        row += 1
    if ie_series:
        axes[row, 0].boxplot(ie_series, labels=ie_labels)
        axes[row, 0].set_title("IE window rel. error (%)")
        axes[row, 0].tick_params(axis="x", rotation=45)
        axes[row, 1].violinplot(ie_series, showmeans=True)
        axes[row, 1].set_title("IE window rel. error violin")

    plt.tight_layout()
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path)
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig


def save_error_results(
    bpm_data,
    ie_data,
    apnea_data,
    output_path: Path,
    *,
    verbose: bool = True,
) -> dict:
    """将误差汇总字典保存为 reports 目录下的 .npy 文件。"""
    error_results = {}
    for seg_name, var_name, est, gt, rel, std in bpm_data:
        error_results.setdefault(seg_name, {})["bpm"] = {
            "est": est,
            "gt": gt,
            "rel_err": rel * 100 if rel is not None else np.nan,
            "rel_err_std": (std or 0.0) * 100,
            "var_name": var_name,
        }
    for seg_name, var_name, est, gt, rel, std in ie_data:
        error_results.setdefault(seg_name, {})["ie"] = {
            "est": est,
            "gt": gt,
            "rel_err": rel * 100 if rel is not None else np.nan,
            "rel_err_std": (std or 0.0) * 100,
            "var_name": var_name,
        }
    for seg_name, est, gt, rel in apnea_data:
        error_results.setdefault(seg_name, {})["apnea"] = {
            "est": est,
            "gt": gt,
            "rel_err": rel * 100 if rel is not None else np.nan,
        }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, error_results, allow_pickle=True)
    if verbose:
        print(f"✓ 误差结果已保存 {output_path.name} ({len(error_results)} 段)")
    return error_results


def run_error_analysis(
    segment_processed,
    segment_config=None,
    segment_data=None,
    *,
    figures_dir: Optional[Path] = None,
    reports_dir: Optional[Path] = None,
    show: bool = True,
    save: bool = True,
) -> dict:
    """收集误差、绘图并保存报告。

    从 ``segment_processed`` 中读取 breathing/apnea 分析结果，
    与 ``segment_config`` 中的 GT 对比，生成图表与 ``.npy`` 报告。

    Returns
    -------
    dict
        ``bpm_data``, ``ie_data``, ``apnea_data``, ``error_results``。
    """
    bpm_data, ie_data, apnea_data = collect_error_metrics(
        segment_processed, segment_config, segment_data
    )
    print(
        f"误差数据: BPM={len(bpm_data)} IE={len(ie_data)} apnea={len(apnea_data)}"
    )

    if figures_dir:
        plot_error_analysis(
            bpm_data,
            ie_data,
            apnea_data,
            save_path=figures_dir / "segment_error_analysis.png",
            show=show,
        )
        plot_window_error_distribution(
            segment_processed,
            segment_config,
            segment_data,
            save_path=figures_dir / "segment_window_error_distribution.png",
            show=show,
        )
    else:
        plot_error_analysis(bpm_data, ie_data, apnea_data, show=show)
        plot_window_error_distribution(
            segment_processed, segment_config, segment_data, show=show
        )

    error_results = {}
    if save and reports_dir:
        error_results = save_error_results(
            bpm_data,
            ie_data,
            apnea_data,
            reports_dir / "segment_error_results.npy",
        )

    return {
        "bpm_data": bpm_data,
        "ie_data": ie_data,
        "apnea_data": apnea_data,
        "error_results": error_results,
    }
