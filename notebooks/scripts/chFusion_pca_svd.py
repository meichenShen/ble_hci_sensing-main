"""chFusion PCA/SVD — multi-channel breath waveform extraction via PCA / SVD.

Overview
========

代替"按能量比选最优单信道"的策略，利用 PCA 和 SVD
从 72 道 BLE CS tone 中提取所有信道的共同呼吸模式。

Methods
-------

- **PCA Remote/Local/Total Amp** : 远程/本地/总幅值 72 道实 PCA
- **SVD Remote/Local/Total Amp** : 远程/本地/总幅值 72 道实 SVD
- **PCA Phase**              : 总相位 72 道实 PCA
- **SVD Phase**              : 总相位 72 道实 SVD
- **SVD Complex Total/Remote/Local** : 总/远程/本地幅值 + j·总相位 72 道复 SVD
- **PCA Stacked**            : 三种幅值堆叠 216 道实 PCA

Run: ``python notebooks/scripts/chFusion_pca_svd.py``
"""

# %% [markdown]
# # chFusion PCA/SVD — 多信道呼吸波形提取
#
# | Step | Content |
# |------|---------|
# | 0 | Bootstrap + parameters |
# | 1 | Multi-channel filtering (4 variables x 72 channels) |
# | 2 | Baseline BPM (Single / Uniform / q_energy_peak) |
# | 3 | PCA / SVD BPM estimation |
# | 4 | Text + bar-chart leaderboard |
# | 5 | Segment x method heatmap |
# | 6 | PC1 variance ratio analysis |
# | 7 | Save results |
# | 8 | Cross-scenario aggregate leaderboard |

# %% [markdown]
# ## 0. Environment bootstrap

# %%
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

_env = init_notebook(project_root)
project_root = _env["project_root"]
FIGURES_DIR = _env["FIGURES_DIR"]
REPORTS_DIR = _env["REPORTS_DIR"]

# %% [markdown]
# ## 0b. Parameters

# %%
from ble_analysis.chfusion import (
    CS_SIGNAL_VARIABLES,
    build_plan2_leaderboard_rows,
    estimate_segment_bpm_methods,
    run_multichannel_segment_filtering,
    run_plan2_validation,
)
from ble_analysis.data import load_ble_frames
from ble_analysis.pca_svd_pipeline import (
    COMPARE_SCENARIO_IDS,
    DIAG_SCENARIO_ID,
    METHOD_CATEGORY_COLORS,
    PCA_SVD_EXPERIMENTS,
    aggregate_cross_domain_rows,
    build_leaderboard,
    category_color as _category_color,
    ensure_scenario_report as _ensure_scenario_report,
    make_default_pipeline_config,
    pca_svd_category as _pca_svd_category,
    print_cross_domain_table,
    run_harmonic_diagnosis,
    run_pca_svd_bpm,
    run_pca_v2_suite,
    save_cross_domain_aggregate,
    save_worst_seg_spectrum_figure,
    segment_rel_err_pct as _segment_rel_err_pct,
)
from ble_analysis.scenarios import load_scenario, print_scenario_summary

SCENARIO_ID = "cs_102621"

scenario = load_scenario(SCENARIO_ID, project_root=project_root)
filepath = scenario.resolve_data_path(project_root)
segment_config = scenario.segment_config
print_scenario_summary(scenario)

pipe_cfg = make_default_pipeline_config()
filter_params = pipe_cfg.filter_params
metric_params = pipe_cfg.metric_params
chfusion_config = pipe_cfg.chfusion_config
plan2_config = pipe_cfg.plan2_config
pca_svd_config = pipe_cfg.pca_svd_config
pca_hp_config = pipe_cfg.pca_hp_config

variables = [v[0] for v in CS_SIGNAL_VARIABLES]
print("Variables:", ", ".join(f"{k} ({lbl})" for k, lbl in CS_SIGNAL_VARIABLES))
print("PCA/SVD normalize:", pca_svd_config.normalize)
print("PCA/SVD min_channels:", pca_svd_config.min_channels)

# %% [markdown]
# ## 1. Multi-channel filtering (4 variables x 72 channels)

# %%
# data 为原始 DataFrame，仅 frames 参与后续处理
data, frames = load_ble_frames(filepath, verbose=False)

multichannel_by_var = {}
fs = None
for variable in variables:
    mc, fs = run_multichannel_segment_filtering(
        frames,
        segment_config,
        variable=variable,
        filter_params=filter_params,
        verbose=True,
    )
    multichannel_by_var[variable] = mc

print(f"\n采样率: {fs:.2f} Hz")

# %% [markdown]
# ## 2. Baseline BPM (Single / Uniform / q_energy_peak)

# %%
baseline_methods = ("single", "uniform", "q_energy_peak")
baseline_results = estimate_segment_bpm_methods(
    multichannel_by_var["remote_amplitudes"],
    variable="remote_amplitudes",
    config=chfusion_config,
    metric_params=metric_params,
    methods=baseline_methods,
    single_channel_metric="energy_ratio",
    verbose=True,
)

print(f"Baseline ({len(baseline_results)} segments) completed")

# %% [markdown]
# ## 3b. Run PCA/SVD BPM estimation (12 methods)
#
# BPM 辅助与 pipeline 见 ``ble_analysis.pca_svd_pipeline``。

# %%

pca_svd_results = {}
for exp_name, exp_cfg in PCA_SVD_EXPERIMENTS.items():
    print(f"\n{'=' * 60}")
    print(f"Running: {exp_name}")
    print(f"{'=' * 60}")
    result = run_pca_svd_bpm(
        multichannel_by_var,
        segment_config,
        method=exp_cfg["method"],
        variable_or_vars=exp_cfg["variable"],
        complex_amp_var=exp_cfg.get("complex_amp_var"),
        fs=fs,
        metric_params=metric_params,
        pca_svd_config=pca_svd_config,
        verbose=True,
    )
    pca_svd_results[exp_name] = result

print(f"\nOK {len(pca_svd_results)} PCA/SVD methods completed")

# %% [markdown]
# ## 3c. PCA v2 — highpass + channel η-weight + PCA modal / complex PCA
#
# 默认用 ``highpass_filtered``；PCA 作多信道提取，再按 Plan2 框架做模态谱融合。

# %%


pca_v2_results = run_pca_v2_suite(
    multichannel_by_var, segment_config, fs, metric_params, pca_hp_config, verbose=True
)
pca_svd_results.update(pca_v2_results)
print(f"\nOK PCA v2: {len(pca_v2_results)} additional methods")

# %% [markdown]
# ## 3d. Plan 2 validation (same scenario, same metrics)

# %%

plan2 = run_plan2_validation(
    frames,
    segment_config,
    filter_params=filter_params,
    metric_params=metric_params,
    config=chfusion_config,
    plan2_config=plan2_config,
    reference_variable="phases",
    verbose=True,
)

plan2_leaderboard = build_plan2_leaderboard_rows(plan2)
print(f"Plan 2 methods: {len(plan2_leaderboard)} entries")

# %% [markdown]
# ## 4. Unified leaderboard  —  PCA/SVD + baseline + Plan 2
#
# 误差指标与 Plan 2 一致：各 breath 段窗级相对误差均值，再对段取平均，单位为 %。

# %%

leaderboard = build_leaderboard(pca_svd_results, baseline_results, plan2_leaderboard)

# ---- 文本排名 ----
print("\n" + "=" * 72)
print(f"  chFusion PCA/SVD  —  Leaderboard")
print(f"  Scenario: {scenario.tag} ({SCENARIO_ID})")
print("=" * 72)
print(f"  {'Rank':>4}  {'方法':<32} {'err%':>7} {'±std%':>7}  {'类别':<10} {'来源'}")
print("  " + "-" * 72)
for r in leaderboard:
    e = f"{r['mean_rel_err_pct']:.2f}" if np.isfinite(r["mean_rel_err_pct"]) else "  ---"
    s = f"{r['std_rel_err_pct']:.2f}"
    mark = " ★" if r["rank"] == 1 else ""
    print(
        f"  {r['rank']:>4}{mark} {r['label']:<32} {e:>7} {s:>7}  "
        f"{r['category']:<10} {r.get('source', '')}"
    )

best = leaderboard[0]
print(f"\n  ★ 全局最优: {best['label']}  →  {best['mean_rel_err_pct']:.2f}%")
pca_only = [r for r in leaderboard if r.get("source") == "pca_svd"]
if pca_only:
    print(f"  PCA/SVD 最优: {pca_only[0]['label']} ({pca_only[0]['mean_rel_err_pct']:.2f}%)")
    print(f"  PCA/SVD 最差: {pca_only[-1]['label']} ({pca_only[-1]['mean_rel_err_pct']:.2f}%)")
plan2_only = [r for r in leaderboard if r.get("source") == "plan2"]
if plan2_only:
    print(f"  Plan2 最优: {plan2_only[0]['label']} ({plan2_only[0]['mean_rel_err_pct']:.2f}%)")
print()

# ---- 横向柱状图 ----
fig_h = max(5.5, 0.36 * len(leaderboard) + 2.0)
fig, ax = plt.subplots(figsize=(10.5, fig_h))
labels = [r["label"] for r in leaderboard]
means = np.asarray([r["mean_rel_err_pct"] for r in leaderboard], dtype=float)
colors = [r["color"] for r in leaderboard]
y = np.arange(len(leaderboard))

ax.barh(y, means, color=colors, edgecolor="black", alpha=0.85, height=0.72)
ax.set_yticks(y)
ax.set_yticklabels(labels, fontsize=9)
ax.invert_yaxis()
ax.set_xlabel("Mean relative BPM error (%)")
ax.set_title("chFusion unified leaderboard — PCA/SVD vs baseline vs Plan 2")
ax.grid(True, axis="x", alpha=0.25)

for i, (m, r) in enumerate(zip(means, leaderboard)):
    txt = f"{m:.2f}%" if np.isfinite(m) else "---"
    ax.text(m + 0.25, i, txt, va="center", fontsize=8)

# 分类图例
seen_cats = set()
handles = []
for r in leaderboard:
    cat = r["category"]
    if cat not in seen_cats:
        seen_cats.add(cat)
        handles.append(plt.Rectangle(
            (0, 0), 1, 1, color=r["color"], ec="black",
            alpha=0.85, label=cat
        ))
ax.legend(handles=handles, loc="lower right", fontsize=8, title="Category")

plt.tight_layout()
bar_path = FIGURES_DIR / f"pca_svd_{scenario.tag}_leaderboard_bars.pdf"
fig.savefig(bar_path, dpi=150, bbox_inches="tight")
print(f"  Fig 1: Leaderboard bars  ->  {bar_path.name}")
plt.show()

# %% [markdown]
# ## 5. Segment × method heatmap
#
# 每行=呼吸段, 每列=方法, 格子=该段该方法 mean rel err%。

# %%

seg_names = sorted(
    k for k, v in pca_svd_results.get("PCA Total Amp", {}).items() if v is not None
)
all_meth_labels = [r["label"] for r in leaderboard]
matrix = np.full((len(seg_names), len(all_meth_labels)), np.nan)

for j, row_data in enumerate(leaderboard):
    label = row_data["label"]
    source = row_data.get("source")
    if source == "pca_svd" and label in pca_svd_results:
        per_seg = pca_svd_results[label]
        for i, seg_name in enumerate(seg_names):
            stats = per_seg.get(seg_name)
            if stats is not None:
                err = stats.get("bpm_rel_err", np.nan)
                matrix[i, j] = float(err) * 100.0 if np.isfinite(err) else np.nan
    elif source == "baseline":
        bmap = {
            "Single (remote amp)": "fft_single_max_energy",
            "Uniform (remote amp)": "fft_uniform_fusion",
            "q_energy_peak (remote amp)": "fft_q_energy_peak_fusion",
        }
        bkey = bmap.get(label)
        if bkey:
            for i, seg_name in enumerate(seg_names):
                seg_out = baseline_results.get(seg_name)
                if seg_out is not None and bkey in seg_out:
                    err = seg_out[bkey].get("bpm_rel_err", np.nan)
                    matrix[i, j] = float(err) * 100.0 if np.isfinite(err) else np.nan
    elif source == "plan2":
        plan2_lookup = {r["label"]: r for r in plan2_leaderboard}
        spec = plan2_lookup.get(label)
        if spec is None:
            continue
        results = (
            plan2["variable_baselines"][spec["baseline_var"]]
            if spec.get("baseline_var") is not None
            else plan2["modal_benchmark"]["results"]
        )
        result_key = spec["result_key"]
        for i, seg_name in enumerate(seg_names):
            row = results.get(seg_name)
            if row is None:
                continue
            block = row.get(result_key)
            if block is None:
                continue
            err = block.get("bpm_rel_err", np.nan)
            matrix[i, j] = float(err) * 100.0 if np.isfinite(err) else np.nan

row_labels = []
for seg in seg_names:
    gt = segment_config[seg].get("bpm_gt", np.nan)
    row_labels.append(f"{seg}\nGT={gt:.1f}" if np.isfinite(gt) else seg)

fig_w = max(12.0, 0.55 * len(all_meth_labels) + 4.0)
fig, ax = plt.subplots(figsize=(fig_w, max(4.5, 0.55 * len(seg_names) + 2.0)))
vmax = float(np.nanpercentile(matrix, 95)) if np.any(np.isfinite(matrix)) else 30.0
vmax = max(vmax, 2.0)
im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd", vmin=0.0, vmax=vmax)
ax.set_xticks(np.arange(len(all_meth_labels)))
ax.set_yticks(np.arange(len(seg_names)))
ax.set_xticklabels(all_meth_labels, rotation=45, ha="right", fontsize=8)
ax.set_yticklabels(row_labels, fontsize=9)
ax.set_title("chFusion PCA/SVD — segment × method (cell = mean rel err%)")

for i in range(matrix.shape[0]):
    for j in range(matrix.shape[1]):
        val = matrix[i, j]
        if np.isfinite(val):
            tc = "white" if val > vmax * 0.6 else "black"
            ax.text(j, i, f"{val:.1f}", ha="center", va="center",
                    fontsize=7, color=tc)

cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
cbar.set_label("Rel. error (%)")
plt.tight_layout()
heatmap_path = FIGURES_DIR / f"pca_svd_{scenario.tag}_segment_method_heatmap.pdf"
fig.savefig(heatmap_path, dpi=150, bbox_inches="tight")
print(f"  Fig 2: Heatmap  ->  {heatmap_path.name}")
plt.show()

# %% [markdown]
# ## 6. PC1 variance ratio  —  table + bar chart
#
# PC1 方差占比越高说明呼吸信号在所有信道中的"共同模式"越明显。

# %%

pc1_records = []
for exp_name, per_seg in pca_svd_results.items():
    ratios = []
    for seg_name, seg_stats in per_seg.items():
        if seg_stats is None:
            continue
        r = seg_stats.get("mean_pc1_ratio", np.nan)
        if np.isfinite(r):
            ratios.append(r)
    if not ratios:
        continue
    arr = np.array(ratios)
    pc1_records.append({
        "label": exp_name,
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr, ddof=1)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
    })
pc1_records.sort(key=lambda x: -x["mean"])

print("\n  === PC1 方差占比统计 ===\n")
print(f"  {'方法':<25} {'Mean':>7} {'Std':>7} {'Min':>7} {'Max':>7}")
print("  " + "-" * 55)
for rec in pc1_records:
    print(f"  {rec['label']:<25} {rec['mean']:7.3f} {rec['std']:7.3f} "
          f"{rec['min']:7.3f} {rec['max']:7.3f}")
print()

# 柱状图
pc1_colors = {
    "PCA": "#5A9BD5", "SVD": "#70AD47",
    "SVD Complex": "#BF8FBF", "Stacked": "#EDB144",
}

fig, ax = plt.subplots(figsize=(10, max(5.5, 0.36 * len(pc1_records) + 1.5)))
labels_pc1 = [r["label"] for r in pc1_records]
means_pc1 = np.asarray([r["mean"] for r in pc1_records], dtype=float)
colors_pc1 = [
    pc1_colors.get(_pca_svd_category(r["label"]), "#CCCCCC") for r in pc1_records
]
y_pc1 = np.arange(len(pc1_records))

ax.barh(y_pc1, means_pc1, color=colors_pc1, edgecolor="black",
        alpha=0.85, height=0.72)
ax.set_yticks(y_pc1)
ax.set_yticklabels(labels_pc1, fontsize=9)
ax.invert_yaxis()
ax.set_xlabel("PC1 explained variance ratio")
ax.set_title("chFusion PCA/SVD — PC1 Variance Ratio (higher = stronger common mode)")
ax.grid(True, axis="x", alpha=0.25)
ax.axvline(0.30, color="red", ls="--", alpha=0.6, label="30% threshold")
ax.legend(fontsize=8)

for i, m in enumerate(means_pc1):
    ax.text(m + 0.02, i, f"{m:.2f}", va="center", fontsize=8)

plt.tight_layout()
pc1_path = FIGURES_DIR / f"pca_svd_{scenario.tag}_pc1_variance_ratio.pdf"
fig.savefig(pc1_path, dpi=150, bbox_inches="tight")
print(f"  Fig 3: PC1 variance  ->  {pc1_path.name}")
plt.show()

# %% [markdown]
# ## 7. Save results

# %%
output = {
    "scenario_id": SCENARIO_ID,
    "scenario_tag": scenario.tag,
    "segment_config": segment_config,
    "baseline_results": baseline_results,
    "pca_svd_results": pca_svd_results,
    "plan2_results": plan2,
    "plan2_leaderboard": plan2_leaderboard,
    "leaderboard": leaderboard,
    "pc1_analysis": pc1_records,
    "pca_svd_config": {
        "normalize": pca_svd_config.normalize,
        "min_channels": pca_svd_config.min_channels,
        "min_variance_ratio": pca_svd_config.min_variance_ratio,
    },
    "plan2_config": {"channel_metric": plan2_config.channel_metric},
}

report_path = REPORTS_DIR / f"chfusion_pca_svd_{scenario.tag}.npy"
np.save(report_path, output, allow_pickle=True)

print(f"\n{'=' * 60}")
print("  DONE — chFusion PCA/SVD")
print(f"{'=' * 60}")
print(f"  场景: {scenario.tag} ({SCENARIO_ID})")
print(f"  最优: {best['label']}  ({best['mean_rel_err_pct']:.2f}%)")
print(f"  图表: {bar_path.name}, {heatmap_path.name}, {pc1_path.name}")
print(f"  报告: {report_path.name}")
print(f"{'=' * 60}")

# %% [markdown]
# ## 8. Cross-scenario aggregate (cs_091339 / cs_095806 / cs_102621)
#
# 对三场景各方法 mean err% 取跨域均值；误差线为跨场景标准差。

# %%



def ensure_scenario_report(scenario_id: str, *, verbose: bool = False) -> dict:
    return _ensure_scenario_report(
        scenario_id,
        project_root=project_root,
        reports_dir=REPORTS_DIR,
        pipe_cfg=pipe_cfg,
        current_report=output if scenario_id == SCENARIO_ID else None,
        verbose=verbose,
    )


results_by_tag: dict[str, dict] = {}
for sid in COMPARE_SCENARIO_IDS:
    sc = load_scenario(sid, project_root=project_root)
    if sid == SCENARIO_ID:
        results_by_tag[sc.tag] = output
    else:
        results_by_tag[sc.tag] = ensure_scenario_report(sid, verbose=False)

compare_tags = [load_scenario(sid, project_root=project_root).tag for sid in COMPARE_SCENARIO_IDS]
cross_rows = aggregate_cross_domain_rows(results_by_tag, compare_tags)
print_cross_domain_table(cross_rows, compare_tags)
_, cross_path = save_cross_domain_aggregate(
    cross_rows, results_by_tag, reports_dir=REPORTS_DIR, figures_dir=FIGURES_DIR,
    scenario_ids=COMPARE_SCENARIO_IDS, compare_tags=compare_tags,
)
print(f"\n  Fig 4: Cross-domain aggregate  ->  {cross_path.name}")
plt.show()

# %% [markdown]
# ## 9. cs_091339 复 PCA 整合失败诊断（η-blend / Dual-Amp）
#
# 统计窗级 BPM 与 GT 比值：fundamental / double / half / other，解释 091339 高误差来源。

# %%

diag_sc = load_scenario(DIAG_SCENARIO_ID, project_root=project_root)
diag_tag = diag_sc.tag
if diag_tag not in results_by_tag:
    results_by_tag[diag_tag] = ensure_scenario_report(DIAG_SCENARIO_ID, verbose=False)
diag_mc = results_by_tag[diag_tag]["multichannel_by_var"]

diag_summary = run_harmonic_diagnosis(diag_mc, pipe_cfg=pipe_cfg, verbose=True)
np.save(
    REPORTS_DIR / f"chfusion_pca_svd_{diag_tag}_harmonic_diag.npy",
    {"scenario_id": DIAG_SCENARIO_ID, "summary": diag_summary},
    allow_pickle=True,
)
print(f"\n  Saved: chfusion_pca_svd_{diag_tag}_harmonic_diag.npy")

spec_path = save_worst_seg_spectrum_figure(
    diag_mc, scenario_tag=diag_tag, figures_dir=FIGURES_DIR, pipe_cfg=pipe_cfg,
)
if spec_path:
    print(f"\n  Fig 5: Worst-seg PC1 spectrum  ->  {spec_path.name}")
else:
    print("\n  Skip PC1 spectrum plot: no valid worst segment")
