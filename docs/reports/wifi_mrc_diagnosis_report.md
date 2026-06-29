# WiFi MRC cs_091339 失效诊断 — 验证报告

> **Plan**：[`docs/plans/wifi_mrc_diagnosis_plan.md`](../plans/wifi_mrc_diagnosis_plan.md)  
> **脚本**：`notebooks/scripts/chFusion_wifi_mrc_diagnosis.py`（核心模块：`src/ble_analysis/wifi_mrc.py`）  
> **场景**：`cs_091339` / `cs_095806` / `cs_102621`  
> **日期**：2026-06-16  
> **状态**：已完成

---

## 1. 目标与假设

补齐上一轮 WiFi MRC baseline 未执行的诊断（D1–D3）与消融（A1–A2），解释 cs_091339 上 MRC 系统性失效机制，并定量归因 B1 vs Fan 差距。

| ID | 假设 | Plan 引用 |
|----|------|-----------|
| H1 | cs_091339 的 per-tone η 稳定性差于另两场景 | D1 |
| H2 | Best-modal 在 091339 切换更频繁 | D2 |
| H3 | cs_091339 PCA loading 窗口间不一致 | D3 |
| H4 | Fan-ηρ-equal 接近 B1 → Voting 非关键；否则 Voting 有独立优势 | A1 |

---

## 2. 方法摘要

| 项目 | 内容 |
|------|------|
| D1 | 逐窗 72-tone η：相邻窗 Pearson r、CV、Top-10 Jaccard |
| D2 | Fan-η-linear / MRC-PCA-η-sqrt Best-modal 分布与切换率 |
| D3 | MRC-PCA loading 余弦相似度、解释方差比、符号稳定性 |
| A1 | Fan-ηρ-linear / Fan-ηρ-equal（η·ρ MRC 权重） |
| A2 | MRC-PCA-η-linear + Equal 模态融合 |

Baseline 数值引用 `outputs/reports/wifi_mrc_baselines_results.npy`（不重跑）。

---

## 3. 实验设置

三场景等权；滑窗 20 s / 1 s；滤波链与上一轮一致。

---

## 4. 结果

### 4.1 D1：η 稳定性

| 场景 | 模态 | mean adjacent r | Top-10 Jaccard | η CV |
|------|------|-----------------|----------------|------|
| cs_091339 | remote | 0.898 | 0.697 | 0.693 |
| cs_091339 | local | 0.869 | 0.611 | 0.711 |
| cs_091339 | phase | 0.892 | 0.667 | 0.697 |
| cs_095806 | remote | 0.845 | 0.633 | 0.487 |
| cs_095806 | local | 0.846 | 0.613 | 0.487 |
| cs_095806 | phase | 0.883 | 0.677 | 0.503 |
| cs_102621 | remote | 0.887 | 0.684 | 0.521 |
| cs_102621 | local | 0.879 | 0.700 | 0.515 |
| cs_102621 | phase | 0.864 | 0.656 | 0.533 |

**判定**：cs_091339 remote η adjacent r = 0.898，高于 cs_095806（0.845）。**H1 未支持**——091339 η 相邻窗相关性并不更差；但 η CV（0.693）显著高于 095806（0.487），窗间绝对波动更大。

图：`outputs/figures/wifi_mrc_diagnosis_eta_stability.png`、`wifi_mrc_diagnosis_summary.png`

### 4.2 D2：Best-modal 切换

| 场景 | 方法 | switch rate | remote% | local% | phase% |
|------|------|-------------|---------|--------|--------|
| cs_091339 | Fan-η-linear | 21.1% | 59% | 14% | 27% |
| cs_091339 | MRC-PCA-η-sqrt | 26.5% | 62% | 16% | 22% |
| cs_095806 | Fan-η-linear | 23.2% | 55% | 31% | 13% |
| cs_095806 | MRC-PCA-η-sqrt | 41.5% | 45% | 36% | 19% |
| cs_102621 | Fan-η-linear | 34.5% | 25% | 46% | 29% |
| cs_102621 | MRC-PCA-η-sqrt | 44.8% | 24% | 48% | 28% |

cs_091339 Fan switch rate = 21.1%，**低于** cs_095806（23.2%）和 cs_102621（34.5%）。**H2 未支持**——091339 模态切换并非更严重。

图：`outputs/figures/wifi_mrc_diagnosis_modal_switching.png`

### 4.3 D3：PCA loading 一致性

| 场景 | mean loading cosine | mean EVR | mean sign stability |
|------|---------------------|----------|---------------------|
| cs_091339 | 0.524 | 0.399 | 0.783 |
| cs_095806 | 0.439 | 0.474 | 0.756 |
| cs_102621 | 0.461 | 0.439 | 0.717 |

cs_091339 PCA cosine = 0.524，**高于**另两场景（0.439 / 0.461）。**H3 未支持**——091339 PCA loading 并非更不一致。

图：`outputs/figures/wifi_mrc_diagnosis_pca_loading.png`

### 4.4 A1/A2：消融 BPM

| 方法 | cs_091339 | cs_095806 | cs_102621 | 跨域 mean |
|------|-----------|-----------|-----------|-----------|
| B1 Vote→Equal（引用） | — | — | — | **8.45%** |
| Fan-η-equal（引用） | — | — | — | 13.51% |
| **Fan-ηρ-equal** | 16.85 | 6.80 | 8.69 | **10.78%** |
| Fan-ηρ-linear | 22.62 | 7.09 | 7.38 | 12.36% |
| MRC-PCA-η-linear | 17.51 | 7.18 | 7.28 | 10.66% |

### 4.5 消融分解

| 因素 | 跨域贡献 (pp) | 解读 |
|------|---------------|------|
| η·ρ vs η（Fan equal） | +2.73 | η·ρ 使 Fan equal 改善 2.73 pp（13.51%→10.78%） |
| Voting vs MRC（η·ρ equal） | +2.33 | MRC 仍差于 B1 2.33 pp（10.78% vs 8.45%）→ **Voting 有独立优势** |

图：`outputs/figures/wifi_mrc_diagnosis_ablation_leaderboard.png`、`wifi_mrc_diagnosis_ablation_decomposition.png`

数值：`outputs/reports/wifi_mrc_diagnosis_ablation.npy`、`wifi_mrc_diagnosis_diagnostics.npy`

---

## 5. 结论

### 已验证

- **A1**：η·ρ MRC 权重使 Fan equal 从 13.51% 改善至 10.78%（+2.73 pp）；Fan-ηρ-equal 跨域与 MRC-PCA-η-equal（10.78%）持平
- **A1**：Fan-ηρ-equal（10.78%）仍差于 B1（8.45%）2.33 pp → **谱域 Voting 有独立于 η·ρ 的优势**（H4：Voting 非可忽略）
- Fan-ηρ-equal 在 cs_095806（6.80%）已接近 B1（6.50%），差距仅 0.30 pp

### 仅单场景

- cs_091339 上 Fan-ηρ-equal 仍 16.85%（vs B1 13.22%），MRC 失效未由 D1–D3 三项假设解释；可能为主场景固有难度 + 时域合并损失谱结构

### 未证实

- Fan-ηρ-equal 跨域达到 B1 水平（差距 2.33 pp > 2 pp 阈值）
- cs_091339 MRC 失效由 η 不稳定 / 模态频繁切换 / PCA 不一致导致（三项诊断均未支持）

### 已废弃

- 无

**相对 baseline**：B1 仍为跨域最优；η·ρ MRC 可缩小与 B1 差距但未超越。

---

## 6. 产出清单

| 类型 | 路径 |
|------|------|
| 诊断数值 | `outputs/reports/wifi_mrc_diagnosis_diagnostics.npy` |
| 消融数值 | `outputs/reports/wifi_mrc_diagnosis_ablation.npy` |
| 图表 | `outputs/figures/wifi_mrc_diagnosis_*.png` |

---

## Self Check

- Plan read: yes
- Baseline confirmed: yes（引用既有 .npy）
- Scenario JSON used: yes
- Script executed: yes
- Results generated: yes
- Figures generated: yes
- Report generated: yes
- Plan updated: yes
- Hardcoded frame index risk: no
- Baseline changed: no
- Metric definition changed: no
- Ready to commit: yes