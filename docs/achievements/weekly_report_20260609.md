# BLE CS 呼吸检测 — 工作周报

> **周期**：2026-06-05 → 2026-06-09 | **日期**：2026-06-09

## 摘要

从 BLE CS 72 tone × 3 变量中提取呼吸信号。经五轮迭代，**最优方案回归到了项目最初的方向**：逐 tone 质量加权谱融合 + 三模态等权融合（B1, **8.45%**）。Deng et al. (2024) 的 Per-Tone Voting 在此过程中扮演了**催化剂**角色——启发了 per-tone 独立处理范式，但最终胜出的不是 Voting 本身（BPM 投票 T0-V3 仅 9.20%），而是 Voting 启发下的谱级融合。B1 在架构上与早期 Plan1 的 `fft_q_energy_peak` 几乎同构，区别仅在于三个关键改进：raw η·ρ 权重（→ log-mapped q）、三变量（→ 单变量）、去掉 consensus gate。

![演进时间线](../../outputs/figures/method_evolution_timeline.png)

**图 1**：方法演进。从 PCA（~10.92%）到 B1（8.45%），降低 2.47pp。

---

## 项目全貌：信道融合策略的螺旋演进

### 早期 Plan1（基线）

| 方法 | 怎么做 | 091339 | 发现 |
|------|--------|--------|------|
| **Single Remote** | 选 η 最大的一个 tone → FFT → BPM | 10.91% | 单 tone > 等权平均 |
| Uniform Remote | 72 tone 谱等权平均 → BPM | 17.09% | 引入差 tone 反而有害 |
| **fft_q_energy_peak** | 72 tone 谱 × log-mapped η·ρ 加权 → BPM | 劣于 Single | B1 的原型，但被单变量+log压缩掩盖 |

早期核心结论：多信道加权不如单选最佳信道。**但当时未意识到：问题不在"多信道"，而在权重函数和变量范围。**

### 主线一：PCA/SVD — 方差≠信号

用 PCA 从 72 信道时域矩阵提取第一主成分作为呼吸波形。跨域 **~10.92%**，未超越 baseline。根因：短窗内噪声也能产生高方差，PCA 无法区分"高方差=呼吸"还是"高方差=多径噪声"。

![PCA PC1 方差占比](../../outputs/figures/pca_svd_pc1_variance_ratio.png)

**图 2**：PC1 方差占比集中在 0.3–0.6——呼吸并非方差的压倒性主导成分。

### 主线二：Per-Tone 独立处理 — Voting 的启发与超越

Deng et al. (2024) 指出 OFDM 子载波间噪声强相关 → 先融合再估计有系统性缺陷 → 应每 tone 独立处理再融合。这启发了两条路径：

| 路径 | 方法 | 每 tone 产出 | 融合 | 跨域 |
|------|------|-------------|------|------|
| BPM 投票 | T0-V3 | 一个 BPM 数字 | η·ρ 直方图投票 | 9.20% |
| **谱融合** | **B1** | **完整 FFT 谱** | **η·ρ 加权平均 + 三模态 Equal** | **8.45%** |

![全阶段排行榜](../../outputs/figures/method_evolution_full_leaderboard.png)

**图 3**：主线排行榜。B1（8.45%）登顶。关键发现：**谱融合（B1）> BPM 投票（T0-V3）**——保留完整谱信息比坍缩到峰频更好。

### B1 与早期原型的对比

B1 的谱构造——逐 tone FFT × 质量权重 → 加权平均——与 Plan1 的 `fft_q_energy_peak` **几乎同构**：

| | 早期 fft_q_energy_peak | B1 |
|--|-----------------------|-----|
| 权重 | $\sqrt{q_{\text{energy}} \cdot q_{\text{peak}}}$（log-mapped, [0,1]） | $\eta \cdot \rho$（raw, unbounded） |
| 变量 | 仅 remote | remote + local + phase → Equal |
| 共识门 | 有（Gaussian 窗） | 无 |
| 跨域 | 劣于 Single | **8.45%** |

**三个改进**：① raw 权重保留动态范围（好/差 tone 权重比 20:1 vs 3:1）；② 三变量 Equal 融合（最大改善来源）；③ 投票替代 consensus gate。

---

## ⭐ 核心机制：谱融合下 Equal > Top2

**问题**：为什么 Voting 谱融合下 Equal（8.45%）优于 Top2（9.92%），而 Single-best 下恰恰相反？

**诊断**：每窗计算三模态融合谱的两两余弦相似度。

| 场景 | 谱融合路径 | Single-best 路径 |
|------|:----------:|:---------------:|
| 091339 | **0.864** | 0.772 |
| 095806 | **0.991** | 0.930 |
| 102621 | **0.959** | 0.885 |

![D1 频谱相似度](../../outputs/figures/b1_diag_spectral_similarity.png)

**图 4**：🟢 谱融合路径（olive）整体偏右——模态间高度一致；🔵 Single-best（steelblue）偏左——更分化。

**解释**：三种模态的融合谱都在平均同一组 72 tone 的 FFT 谱 → 天然趋同。这不是神秘效应，是构造方式的结构性必然。因此 Top2（选择性踢模态）失去意义，Equal（等权降方差）最优。

**更精确的表述**：此发现只与谱加权融合（B1/B3）有关，与 BPM 投票（T0-V3）无关——后者坍缩为 BPM 数字，没有谱可比较。真正的 insight：**保留完整谱信息优于坍缩到峰频**（B1 8.45% < T0-V3 9.20%）。

---

## 固化基线

以下方法固化为后续工作的固定对比基线：

| 基线 | 方法 | 跨域 | 定位 |
|------|------|------|------|
| **Deng et al. (2024)** | T0-V3：每 tone 独立 BPM → η·ρ 直方图投票（仅 remote） | 9.20% | 论文原始 Voting；后续 Voting 变种以论文名区分 |
| Single Remote | max-η 选单 tone | 10.45% | 最简基线 |
| Modal top2 | 逐模态 max-η 单 tone → Top2 等权 | 9.45% | Plan2 最优 |
| PCA-Modal3 | PCA per modal → η 加权 | ~10.92% | 失败参照 |

---

## 下一步

后续计划待阅读文献后确定。已安排的方向：

| 方向 | 内容 |
|------|------|
| **权重函数系统对比** | 在 B1 架构下 ablation：raw η·ρ vs log-mapped q vs η only vs ρ only |
| **多径诊断** | 091339 退化根因（>12%） |
| **泛化验证** | 新场景上验证 B1 和 Equal>Top2 机制 |
| **文献阅读** | [`docs/plans/literature_review_plan.md`](../plans/literature_review_plan.md) — 读完后确定新 Voting 变种 |

---

## 产出清单

| 类型 | 路径 |
|------|------|
| 综合报告 | `docs/achievements/pca_voting_comprehensive_achievement_report.md` |
| 周报 | `docs/achievements/weekly_report_20260609.md` |
| 图表脚本 | `notebooks/scripts/chFusion_achievement_figures.py`、`src/ble_analysis/achievement_figures.py` |
| 图表 | `method_evolution_*.png`、`pca_svd_*.png`、`b1_diag_spectral_similarity.png` 等 |
