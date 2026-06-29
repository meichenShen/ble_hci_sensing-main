"""Achievement-report summary figures for PCA→Voting method evolution.

Generates PNG figures listed in
``docs/achievements/pca_voting_comprehensive_achievement_report.md`` §9.3.
Uses descriptive method names (§5.2 / §9.1), not internal codes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np

from ble_analysis.chfusion import _overall_rel_error

PCA_DESCRIPTIVE_NAMES: Dict[str, str] = {
    "Modal top2 equal": "逐模态最优信道 → Top2 等权谱融合",
    "Modal η-weight": "逐模态最优信道 → η 加权谱融合",
    "Single Remote amplitude": "单信道 Remote 幅值（max-η 选道）",
    "Uniform Remote amplitude": "远程 72 信道均匀谱融合",
    "PCA-Modal3 η/ch-η": "PCA-Modal3（PCA per modal → η 加权融合）",
    "PCA-Modal3 top16/ch-η": "PCA-Modal3 top16（PCA per modal → η 加权）",
    "PCA-Modal3 top8/ch-η": "PCA-Modal3 top8（PCA per modal → η 加权）",
    "PCA-Modal3 top2/ch-η": "PCA-Modal3 top2（PCA per modal → η 加权）",
    "PCA-HP Remote ch-η": "PCA-HP Remote（高通 PCA → η 加权选道）",
    "PCA-HP Remote top8/ch-η": "PCA-HP Remote top8（高通 PCA）",
    "PCA Total Amp": "PCA 总幅值（72 信道降维）",
    "PCA-Cmplx η-blend ch-η": "复 PCA η-blend（幅值+相位联合）",
    "PCA-Cmplx-Modal rem+loc top2": "复 PCA 双幅值 → Top2 模态融合",
    "PCA-Cmplx Total ch-η": "复 PCA 总幅值（η 加权选道）",
    "PCA-Cmplx Total top8/ch-η": "复 PCA 总幅值 top8",
    "PCA-Cmplx-Modal rem+loc η": "复 PCA 双幅值 → η 加权模态融合",
}

PC1_CATEGORY_COLORS: Dict[str, str] = {
    "PCA": "#5A9BD5",
    "SVD": "#70AD47",
    "SVD Complex": "#BF8FBF",
    "Stacked": "#EDB144",
}

PCA_VS_VOTING_SCENARIOS: Tuple[Tuple[str, str], ...] = (
    ("cs_091339", "091339"),
    ("cs_095806", "095806"),
    ("cs_102621", "102621"),
)

# --- Descriptive name mapping (§9.1 / §5.2) ---

VOTING_DESCRIPTIVE_NAMES: Dict[str, str] = {
    "t0_v3_eta_rho_weighted": "远程单模态 Per-Tone η·ρ 投票",
    "b2_modal_top2_equal": "逐模态最优信道 → Top2 等权谱融合",
    "b3_modal_eta_weight": "逐模态最优信道 → η 加权谱融合",
    "t3_voting_modal_hybrid": "逐模态 Voting → 跨模态 η 加权中位数",
    "b0_single_remote": "单信道 Remote 幅值（max-η 选道）",
    "t2_cross_modal_median": "逐模态最优信道 → 跨模态中位数",
    "t0_v1_simple": "远程单模态 Per-Tone 等权投票",
    "t0_v2_eta_weighted": "远程单模态 Per-Tone η 加权投票",
    "t1_k4_v2": "远程 Top-4 Per-Tone η 加权投票",
    "t1_k8_v2": "远程 Top-8 Per-Tone η 加权投票",
    "t1_k16_v2": "远程 Top-16 Per-Tone η 加权投票",
    "b1_uniform_remote": "远程 72 信道均匀谱融合",
}

PHASE_COLORS: Dict[str, str] = {
    "P0": "#4C72B0",
    "P1": "#DD8452",
    "P2": "#55A868",
    "P3": "#8172B3",
}

# Mainline 8 methods: (method_key, descriptive_name, phase, data_source)
MAINLINE_METHODS: Tuple[Tuple[str, str, str, str], ...] = (
    ("b1_vote_modal_equal", "逐模态 Voting → 三模态等权谱融合", "P2", "systematic"),
    ("c2_uniform_modal_eta", "逐模态均匀 → η 加权融合", "P2", "systematic"),
    ("b2_vote_modal_eta", "逐模态 Voting → η 加权融合", "P2", "systematic"),
    ("t0_v3_eta_rho_weighted", "远程单模态 Per-Tone η·ρ 投票", "P1", "voting"),
    ("b2_modal_top2_equal", "逐模态最优信道 → Top2 等权谱融合", "P1", "voting"),
    ("b3_vote_modal_top2", "逐模态 Voting → Top2 融合", "P2", "systematic"),
    ("b0_single_remote", "单信道 Remote 幅值（max-η 选道）", "P0", "voting"),
    ("pca_modal3_eta", "PCA-Modal3（PCA per modal → η 加权融合）", "P0", "pca"),
)

PCA_MODAL3_LABEL = "PCA-Modal3 η/ch-η"
PCA_MODAL3_KEY = "pca_modal3_eta"

EVOLUTION_TIMELINE: Tuple[Tuple[str, str, str, float], ...] = (
    ("P0", "PCA/SVD", "PCA-Modal3（PCA per modal → η 加权融合）", 10.922),
    ("P1", "Per-Tone 投票", "远程单模态 Per-Tone η·ρ 投票", 9.20),
    ("P2", "系统性融合", "逐模态 Voting → 三模态等权谱融合", 8.45),
    ("P3", "机制诊断", "物理机制确认（无新方法）", 8.45),
)

SCENARIO_IDS: Tuple[str, ...] = ("cs_091339", "cs_095806", "cs_102621")
SCENARIO_COLORS: Tuple[str, ...] = ("#4C72B0", "#55A868", "#C44E52")

__all__ = [
    "VOTING_DESCRIPTIVE_NAMES",
    "PHASE_COLORS",
    "MAINLINE_METHODS",
    "setup_cjk_font",
    "load_voting_cross_domain",
    "load_systematic_cross_domain",
    "load_pca_cross_domain",
    "lookup_cross_domain_mean",
    "plot_voting_fusion_leaderboard",
    "plot_voting_fusion_cross_domain_bars",
    "plot_method_evolution_timeline",
    "plot_method_evolution_full_leaderboard",
    "plot_pca_svd_cross_domain_bars",
    "plot_pca_svd_pc1_variance_ratio",
    "plot_pca_vs_voting_comparison",
    "plot_all_achievement_figures",
    "plot_pca_achievement_figures",
]


def setup_cjk_font() -> None:
    """Configure matplotlib for Chinese labels on Windows/Linux."""
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def _load_npy(path: Path):
    data = np.load(path, allow_pickle=True)
    if isinstance(data, np.ndarray) and data.shape == ():
        return data.item()
    return data


def load_voting_cross_domain(reports_dir: Path) -> np.ndarray:
    return _load_npy(reports_dir / "voting_fusion_cross_domain.npy")


def load_systematic_cross_domain(reports_dir: Path) -> np.ndarray:
    return _load_npy(reports_dir / "systematic_fusion_cross_domain.npy")


def load_pca_cross_domain(reports_dir: Path) -> dict:
    return _load_npy(reports_dir / "chfusion_pca_svd_cross_domain.npy")


def _voting_descriptive(row: dict) -> str:
    key = row.get("method_key", "")
    return VOTING_DESCRIPTIVE_NAMES.get(key, row.get("label", key))


def _pca_descriptive(label: str) -> str:
    return PCA_DESCRIPTIVE_NAMES.get(label, label)


def lookup_cross_domain_mean(
    method_key: str,
    *,
    voting_cd: np.ndarray,
    systematic_cd: np.ndarray,
    pca_cd: dict,
) -> float:
    """Resolve cross-domain mean for a mainline method key."""
    if method_key == PCA_MODAL3_KEY:
        for row in pca_cd["cross_rows"]:
            if row["label"] == PCA_MODAL3_LABEL:
                return float(row["mean_across_domains"])
        raise KeyError(f"PCA label not found: {PCA_MODAL3_LABEL}")

    for row in systematic_cd:
        if row["method_key"] == method_key:
            return float(row["cross_domain_mean"])
    for row in voting_cd:
        if row["method_key"] == method_key:
            return float(row["cross_domain_mean"])
    raise KeyError(f"Method key not found: {method_key}")


def _save_fig(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight", format="png")
    plt.close(fig)
    return path


def plot_voting_fusion_leaderboard(
    cross_domain: Sequence[dict],
    figures_dir: Path,
    *,
    top_n: Optional[int] = None,
) -> Path:
    """Phase 1 cross-domain leaderboard (horizontal bars, descriptive names)."""
    rows = list(cross_domain)
    if top_n is not None:
        rows = rows[:top_n]

    labels = [_voting_descriptive(r) for r in rows]
    means = [r["cross_domain_mean"] for r in rows]
    stds = [r.get("cross_domain_std", 0.0) for r in rows]
    colors = [r.get("color", "#888888") for r in rows]

    fig, ax = plt.subplots(figsize=(13, 7))
    y_pos = np.arange(len(labels))
    ax.barh(y_pos, means, xerr=stds, color=colors, alpha=0.85, capsize=3)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("跨域 mean BPM 相对误差 (%)")
    ax.set_title("Phase 1 Per-Tone 投票 — 跨域排行榜（三金属板场景）")
    ax.axvline(9.45, color="gray", linestyle="--", linewidth=1, label="Modal top2 参考 (9.45%)")
    ax.legend(loc="lower right")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    return _save_fig(fig, figures_dir / "voting_fusion_leaderboard.png")


def plot_voting_fusion_cross_domain_bars(
    cross_domain: Sequence[dict],
    results_by_scenario: dict,
    figures_dir: Path,
    *,
    top_n: int = 8,
) -> Path:
    """Phase 1 top methods — per-scenario grouped bars with descriptive names."""
    rows = list(cross_domain)[:top_n]
    labels = [_voting_descriptive(r) for r in rows]
    x = np.arange(len(labels))
    width = 0.25

    fig, ax = plt.subplots(figsize=(15, 6))
    for i, sid in enumerate(SCENARIO_IDS):
        vals = []
        for row in rows:
            stats = _overall_rel_error(results_by_scenario[sid]["results"], row["method_key"])
            vals.append(stats["mean_rel_err_pct"])
        ax.bar(
            x + (i - 1) * width,
            vals,
            width,
            label=sid,
            color=SCENARIO_COLORS[i],
            alpha=0.85,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=28, ha="right", fontsize=8)
    ax.set_ylabel("mean BPM 相对误差 (%)")
    ax.set_title("Phase 1 Per-Tone 投票 — 各场景 Top-8 方法对比")
    ax.legend(title="场景")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    return _save_fig(fig, figures_dir / "voting_fusion_cross_domain_aggregate_bars.png")


def plot_method_evolution_timeline(figures_dir: Path) -> Path:
    """Best mainline method per phase: P0→P1→P2→P3 vs cross-domain mean err%."""
    phases = [t[0] for t in EVOLUTION_TIMELINE]
    means = [t[3] for t in EVOLUTION_TIMELINE]
    names = [t[2] for t in EVOLUTION_TIMELINE]
    colors = [PHASE_COLORS[p] for p in phases]

    fig, ax = plt.subplots(figsize=(11, 6))
    x = np.arange(len(phases))
    ax.plot(x, means, "o-", color="#333333", linewidth=2, markersize=10, zorder=2)
    for i, (phase, mean, name, color) in enumerate(
        zip(phases, means, names, colors)
    ):
        ax.scatter(i, mean, s=180, color=color, zorder=3, edgecolors="white", linewidths=1.5)
        ax.annotate(
            f"{mean:.2f}%",
            (i, mean),
            textcoords="offset points",
            xytext=(0, 12),
            ha="center",
            fontsize=10,
            fontweight="bold",
        )
        ax.annotate(
            name,
            (i, mean),
            textcoords="offset points",
            xytext=(0, -28 if i % 2 == 0 else -42),
            ha="center",
            fontsize=7.5,
            color="#444444",
            wrap=True,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(phases)
    ax.set_xlabel("阶段")
    ax.set_ylabel("跨域 mean BPM 相对误差 (%)")
    ax.set_title("方法演进时间线 — 各阶段最优主线方法")
    ax.set_ylim(7.5, 12.0)
    ax.grid(True, alpha=0.3)

    from matplotlib.patches import Patch

    legend_handles = [
        Patch(facecolor=PHASE_COLORS[p], label=f"{p} {EVOLUTION_TIMELINE[i][1]}")
        for i, p in enumerate(phases)
    ]
    ax.legend(handles=legend_handles, loc="upper right", fontsize=8)
    fig.tight_layout()
    return _save_fig(fig, figures_dir / "method_evolution_timeline.png")


def plot_method_evolution_full_leaderboard(
    voting_cd: Sequence[dict],
    systematic_cd: Sequence[dict],
    pca_cd: dict,
    figures_dir: Path,
) -> Path:
    """All 8 mainline methods sorted by cross-domain mean, colored by phase."""
    entries: List[dict] = []
    for method_key, name, phase, _source in MAINLINE_METHODS:
        mean = lookup_cross_domain_mean(
            method_key,
            voting_cd=voting_cd,
            systematic_cd=systematic_cd,
            pca_cd=pca_cd,
        )
        entries.append(
            {
                "name": name,
                "phase": phase,
                "mean": mean,
                "color": PHASE_COLORS[phase],
            }
        )
    entries.sort(key=lambda e: e["mean"])

    labels = [e["name"] for e in entries]
    means = [e["mean"] for e in entries]
    colors = [e["color"] for e in entries]

    fig, ax = plt.subplots(figsize=(13, 7))
    y_pos = np.arange(len(labels))
    bars = ax.barh(y_pos, means, color=colors, alpha=0.88)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("跨域 mean BPM 相对误差 (%)")
    ax.set_title("全阶段排行榜 — 主线 8 方法（按跨域 mean 升序）")

    for bar, val in zip(bars, means):
        ax.text(val + 0.08, bar.get_y() + bar.get_height() / 2, f"{val:.2f}%", va="center", fontsize=8)

    from matplotlib.patches import Patch

    phase_legend = [
        Patch(facecolor=PHASE_COLORS[p], label=label)
        for p, label in [("P0", "Phase 0: PCA/SVD"), ("P1", "Phase 1: Per-Tone 投票"),
                         ("P2", "Phase 2: 系统性融合"), ("P3", "Phase 3: 机制诊断")]
    ]
    ax.legend(handles=phase_legend, loc="lower right", fontsize=8)
    ax.axvline(8.45, color="gray", linestyle="--", linewidth=1, alpha=0.6)
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    return _save_fig(fig, figures_dir / "method_evolution_full_leaderboard.png")


def _collect_pc1_records(reports_dir: Path, scenario_tag: str = "091339") -> List[dict]:
    """Recompute PC1 variance ratio stats from cached multichannel (primary scenario)."""
    from ble_analysis.pca_svd_pipeline import (
        PCA_SVD_EXPERIMENTS,
        make_default_pipeline_config,
        pca_svd_category,
        run_pca_svd_bpm,
    )

    cache_path = reports_dir / f"chfusion_pca_svd_{scenario_tag}.npy"
    cached = _load_npy(cache_path)
    mc = cached["multichannel_by_var"]
    seg_cfg = cached["segment_config"]
    fs = cached["fs"]
    pipe_cfg = make_default_pipeline_config()

    records: List[dict] = []
    for exp_name, exp_cfg in PCA_SVD_EXPERIMENTS.items():
        per_seg = run_pca_svd_bpm(
            mc,
            seg_cfg,
            method=exp_cfg["method"],
            variable_or_vars=exp_cfg["variable"],
            complex_amp_var=exp_cfg.get("complex_amp_var"),
            fs=fs,
            metric_params=pipe_cfg.metric_params,
            pca_svd_config=pipe_cfg.pca_svd_config,
            verbose=False,
        )
        ratios = [
            float(seg_stats["mean_pc1_ratio"])
            for seg_stats in per_seg.values()
            if isinstance(seg_stats, dict)
            and np.isfinite(seg_stats.get("mean_pc1_ratio", np.nan))
        ]
        if not ratios:
            continue
        arr = np.asarray(ratios, dtype=float)
        records.append(
            {
                "label": exp_name,
                "category": pca_svd_category(exp_name),
                "mean": float(np.mean(arr)),
                "std": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
            }
        )
    records.sort(key=lambda r: -r["mean"])
    return records


def plot_pca_svd_cross_domain_bars(pca_cd: dict, figures_dir: Path) -> Path:
    """PCA/SVD cross-domain leaderboard (PNG, descriptive Chinese labels)."""
    cross_rows = pca_cd["cross_rows"]
    labels = [_pca_descriptive(r["label"]) for r in cross_rows]
    means = [r["mean_across_domains"] for r in cross_rows]
    stds = [r["std_across_domains"] for r in cross_rows]

    fig, ax = plt.subplots(figsize=(12, max(6.0, 0.38 * len(cross_rows) + 1.5)))
    y = np.arange(len(labels))
    ax.barh(y, means, xerr=stds, color="#7B9FD4", edgecolor="black", alpha=0.85, height=0.72, capsize=3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("跨场景 mean BPM 相对误差 (%)")
    ax.set_title("PCA/SVD 系列 — 跨域排行榜（越低越好）")
    ax.grid(True, axis="x", alpha=0.25)
    for i, (m, s) in enumerate(zip(means, stds)):
        ax.text(m + s + 0.25, i, f"{m:.1f}±{s:.1f}%", va="center", fontsize=7)
    fig.tight_layout()
    return _save_fig(fig, figures_dir / "pca_svd_cross_domain_aggregate_bars.png")


def plot_pca_svd_pc1_variance_ratio(
    reports_dir: Path,
    figures_dir: Path,
    *,
    scenario_tag: str = "091339",
) -> Path:
    """PC1 explained variance ratio bar chart (primary scenario)."""
    records = _collect_pc1_records(reports_dir, scenario_tag=scenario_tag)
    labels = [r["label"] for r in records]
    means = np.asarray([r["mean"] for r in records], dtype=float)
    colors = [PC1_CATEGORY_COLORS.get(r["category"], "#CCCCCC") for r in records]

    fig, ax = plt.subplots(figsize=(10, max(5.5, 0.36 * len(records) + 1.5)))
    y = np.arange(len(records))
    ax.barh(y, means, color=colors, edgecolor="black", alpha=0.85, height=0.72)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("PC1 解释方差占比")
    ax.set_title(f"PCA/SVD — PC1 方差占比（场景 {scenario_tag}，越高=共同模式越强）")
    ax.grid(True, axis="x", alpha=0.25)
    ax.axvline(0.30, color="red", ls="--", alpha=0.6, label="30% 阈值")
    ax.legend(fontsize=8)
    for i, m in enumerate(means):
        ax.text(m + 0.02, i, f"{m:.2f}", va="center", fontsize=8)
    fig.tight_layout()
    return _save_fig(fig, figures_dir / "pca_svd_pc1_variance_ratio.png")


def plot_pca_vs_voting_comparison(
    pca_cd: dict,
    voting_results: dict,
    figures_dir: Path,
) -> Path:
    """Dual-line chart: PCA-Modal3 vs Per-Tone η·ρ voting across three scenarios."""
    pca_row = next(r for r in pca_cd["cross_rows"] if r["label"] == PCA_MODAL3_LABEL)
    pca_errs = pca_row["domain_errs"]

    vote_errs = []
    for sid, _short in PCA_VS_VOTING_SCENARIOS:
        stats = _overall_rel_error(voting_results[sid]["results"], "t0_v3_eta_rho_weighted")
        vote_errs.append(stats["mean_rel_err_pct"])

    x_labels = [short for _sid, short in PCA_VS_VOTING_SCENARIOS]
    x = np.arange(len(x_labels))

    pca_name = _pca_descriptive(PCA_MODAL3_LABEL)
    vote_name = VOTING_DESCRIPTIVE_NAMES["t0_v3_eta_rho_weighted"]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.plot(x, pca_errs, "o-", color=PHASE_COLORS["P0"], linewidth=2, markersize=9, label=pca_name)
    ax.plot(x, vote_errs, "s-", color=PHASE_COLORS["P1"], linewidth=2, markersize=9, label=vote_name)

    for i, (pv, vv) in enumerate(zip(pca_errs, vote_errs)):
        ax.annotate(f"{pv:.1f}%", (i, pv), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=8, color=PHASE_COLORS["P0"])
        ax.annotate(f"{vv:.1f}%", (i, vv), textcoords="offset points", xytext=(0, -14), ha="center", fontsize=8, color=PHASE_COLORS["P1"])

    ax.set_xticks(x)
    ax.set_xticklabels(x_labels)
    ax.set_xlabel("验证场景")
    ax.set_ylabel("mean BPM 相对误差 (%)")
    ax.set_title("PCA/SVD 与 Per-Tone 投票 — 三场景对比")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return _save_fig(fig, figures_dir / "pca_vs_voting_comparison.png")


def plot_pca_achievement_figures(
    *,
    reports_dir: Path,
    figures_dir: Path,
) -> Dict[str, Path]:
    """Generate §9.3 PCA-related achievement figures."""
    setup_cjk_font()
    pca_cd = load_pca_cross_domain(reports_dir)
    voting_results = _load_npy(reports_dir / "voting_fusion_results.npy")
    return {
        "pca_cross_domain_bars": plot_pca_svd_cross_domain_bars(pca_cd, figures_dir),
        "pca_pc1_variance": plot_pca_svd_pc1_variance_ratio(reports_dir, figures_dir),
        "pca_vs_voting": plot_pca_vs_voting_comparison(pca_cd, voting_results, figures_dir),
    }


def plot_all_achievement_figures(
    *,
    reports_dir: Path,
    figures_dir: Path,
    include_pca: bool = True,
) -> Dict[str, Path]:
    """Generate all §9.3 achievement figures (high-priority + optional PCA)."""
    setup_cjk_font()

    voting_cd = load_voting_cross_domain(reports_dir)
    systematic_cd = load_systematic_cross_domain(reports_dir)
    pca_cd = load_pca_cross_domain(reports_dir)
    voting_results = _load_npy(reports_dir / "voting_fusion_results.npy")

    paths = {
        "voting_leaderboard": plot_voting_fusion_leaderboard(voting_cd, figures_dir),
        "voting_cross_domain_bars": plot_voting_fusion_cross_domain_bars(
            voting_cd, voting_results, figures_dir
        ),
        "evolution_timeline": plot_method_evolution_timeline(figures_dir),
        "evolution_full_leaderboard": plot_method_evolution_full_leaderboard(
            voting_cd, systematic_cd, pca_cd, figures_dir
        ),
    }
    if include_pca:
        paths.update(plot_pca_achievement_figures(reports_dir=reports_dir, figures_dir=figures_dir))
    return paths
