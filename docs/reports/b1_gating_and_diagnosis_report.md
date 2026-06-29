# B1 联合门控与 Vote→Equal 机制诊断 — 验证报告

> **Plan**：[`docs/plans/b1_gating_and_diagnosis_plan.md`](../plans/b1_gating_and_diagnosis_plan.md)  
> **脚本**：`notebooks/scripts/chFusion_b1_gating_diagnosis.py`（核心模块：`src/ble_analysis/b1_gating_diagnosis.py`、`src/ble_analysis/consensus_gating.py`）  
> **场景**：`cs_091339` / `cs_095806` / `cs_102621`  
> **日期**：2026-06-08  
> **状态**：已完成

---

## 1. 目标与假设

验证 B1（Vote→Equal modal）能否通过 G4 三候选门控进一步降低跨域 mean，并诊断 Equal vs Top2 机制差异及 091339 双峰性失效模式。

| ID | 假设 | Plan 引用 |
|----|------|-----------|
| H1 | G4-B1 三候选门控跨域 mean < 8.3% | §3.1 |
| H2 | Voting→谱模态间相似度高于 Single-best→谱 | §3.2.1 |
| H3 | 091339 双峰窗是 B1 误差主源；G5-B1 可改善 | §3.2.2 / §3.3 |
| H4 | winning-bin 谱可改变 B1/B3 相对排名 | §3.2.3 |

---

## 2. 方法摘要

| 项目 | 内容 |
|------|------|
| 观测量 | remote / local / phases |
| 主实验 | G4-B1 v1–v4：三候选（B1、T0-V3、Modal top2）+ Single fallback，δ=3 BPM |
| 诊断 D1 | 每窗三模态频谱余弦相似度（Vote path vs Single-best path） |
| 诊断 D2 | 091339 per-modal bimodality；双峰/单峰窗 B1 error 对比 |
| 诊断 D3 | 谱构造 ablation：conf-weighted / winning-bin / top-K (16,24) × Equal/Top2 |
| G5-B1 | 091339 专项：双峰模态剔除后 Equal 融合 |

---

## 3. 实验设置

| 场景 ID | 数据文件 | 备注 |
|---------|----------|------|
| cs_091339 | `sampleData/CS_frames_all_20260113_091339.jsonl` | 主诊断场景 |
| cs_095806 | `sampleData/CS_frames_all_20260116_095806.jsonl` | B1 优势场景 |
| cs_102621 | `sampleData/CS_frames_all_20260116_102621.jsonl` | G4 优势场景 |

- **Baseline**：B1 8.45%、G4 8.65%、G5 8.72%、T0-V3 9.20%、Modal top2 9.45%（本 run 复现）
- **指标**：分段 BPM 相对误差 % mean/std、跨域 mean

---

## 4. 结果

### 4.1 主结果表

| 方法 | cs_091339 | cs_095806 | cs_102621 | 跨域 mean |
|------|-----------|-----------|-----------|-----------|
| **G4-B1-v2 Top2 consensus** | 12.36 | **6.31** | 5.50 | **8.05** |
| G4-B1-v1 Triple consensus | 12.38 | 7.56 | **4.80** | 8.25 |
| G4-B1-v3 B1 fallback | 12.38 | 7.56 | **4.80** | 8.25 |
| B1 Vote→Equal | 13.22 | 6.50 | 5.63 | 8.45 |
| G4 Single fallback | 12.39 | 9.05 | **4.51** | 8.65 |
| G4-B1-v4 B1 vs Modal | 12.73 | 8.63 | 4.63 | 8.67 |
| G5 Bimodality | 12.27 | 7.09 | 6.80 | 8.72 |
| D3-A B1 (winning-bin) | — | — | — | 8.24 |
| D3-A B3 (winning-bin) | — | — | — | 9.40 |
| G5-B1 (仅 091339) | **15.74** | — | — | — |

### 4.2 与 plan 预期对比

| 预期（Plan §5.3） | 实际 | 是否一致 |
|-------------------|------|----------|
| 理想：G4-B1-v1 < 8.0% 且三场景均最优 | v1 = 8.25%；102621 上 4.80% 仍差于 G4 4.51% | ❌ |
| 良好：G4-B1 < 8.3% 且 102621 不差于 G4 | v2 = **8.05%**；102621 5.50% **差于 G4 4.51%** | 部分 |
| 最低：跨域 < B1 且 D1/D2 有机制解释 | v2/v1 均 < 8.45%；D1 支持 H2 | ✅ |
| G5-B1 改善 091339 | 15.74% >> B1 13.22% | ❌ |
| D3-A 使 B3 优于 conf B3 | D3-A B3 9.40% vs conf B3 9.92%（systematic）略优但跨域仍差于 B1 | 部分 |

### 4.3 诊断摘要

**D1 模态频谱相似度（跨场景 mean cosine）**

| 场景 | Vote→谱 (B1 path) | Single-best→谱 (Modal path) |
|------|-------------------|----------------------------|
| 091339 | 0.864 | 0.772 |
| 095806 | 0.991 | 0.930 |
| 102621 | 0.959 | 0.885 |

Voting 路径的模态间相似度** consistently 高于** Single-best 路径 → **支持 H2**（Top2 选择性退化）。

**D2 091339 双峰性 vs B1 error**

| 窗类型 | B1 窗级 error mean (%) |
|--------|------------------------|
| 双峰窗 (≥1 模态 bimodality≥0.5) | 15.17 |
| 单峰窗 | 17.20 |

双峰窗 error **并未高于**单峰窗 → **H3 主假设未证实**（091339 退化不能简单归因于双峰 conf 污染）。

### 4.4 图表

- `outputs/figures/b1_gating_leaderboard.png` — 跨域排行榜
- `outputs/figures/b1_gating_decision_pie.png` — G4-B1-v1 窗级决策分布
- `outputs/figures/b1_diag_spectral_similarity.png` — D1 相似度直方图
- `outputs/figures/b1_diag_bimodal_error.png` — D2 091339 boxplot
- `outputs/figures/b1_diag_spectrum_mode.png` — D3 谱构造 ablation

---

## 5. 结论

### 已验证

- **G4-B1-v2** 跨域 **8.05%**，优于 B1（8.45%）和 G4（8.65%），达到 plan「良好」档位的跨域 mean 目标。
- **H2**：Voting→谱在三场景上模态间余弦相似度均显著高于 Single-best→谱，机制上解释 B3（Top2）相对 B1（Equal）的退化。
- **D3 winning-bin**：D3-A B1 跨域 8.24%，略优于 conf B1 8.45%，但未改变 B1 整体最优地位。

### 仅单场景

- G4-B1-v2 在 **095806**（6.31% vs B1 6.50%）和 **091339**（12.36% vs B1 13.22%）优于 B1；**102621** 上 5.50% 差于 G4 4.51% 和 B1 5.63%。

### 未证实

- **H1 全局最优组合**：无变体在三场景均不差于各自单一最优（102621 仍由 G4 主导）。
- **H3 / G5-B1**：091339 专项门控 **15.74%**，显著差于 B1。
- **H4 排名反转**：winning-bin 未使 B3 超越 B1。

### 已废弃

- **G5-B1** 作为 091339 改善手段（本实验数据下）。

**相对 baseline**：G4-B1-v2 为当前跨域最优（8.05%），但 **102621 部署仍应优先 G4**。

---

## 6. 开放问题与下一步

| ID | 问题 | 建议 |
|----|------|------|
| Q1 | 102621 上 v2 Consensus 为何弱于 G4？ | 分析 v2 在 vote–modal 接近窗的决策 |
| Q2 | 091339 退化根因若非双峰，是什么？ | 补 η/ρ 分布与多径诊断 |
| Q3 | 是否场景自适应门控（102621→G4，其余→v2）？ | 新 plan，避免硬编码场景 |

---

## 7. 复现

```bash
python notebooks/scripts/chFusion_b1_gating_diagnosis.py
```

| 产出 | 路径 |
|------|------|
| 数值结果 | `outputs/reports/b1_gating_diagnosis_{091339,095806,102621}_results.npy` |
| 跨域汇总 | `outputs/reports/b1_gating_diagnosis_cross_domain.npy` |
| 图表 | `outputs/figures/b1_gating_*.png`, `outputs/figures/b1_diag_*.png` |
| 本报告 | `docs/reports/b1_gating_and_diagnosis_report.md` |

---

## 附录 A：方法代号与信道/模态融合对照

本附录说明报告中各方法代号的 **信道融合** 与 **模态融合** 含义，便于 Review 与成果汇报引用。

### A.1 两层（+ 可选门控）结构

```text
72 信道 ──[信道融合]──► 每模态一条谱/BPM ──[模态融合]──► 候选 BPM
                                              ↑
                              （可选）窗级门控在多个候选 BPM 间选择
```

三模态固定为：**remote 幅值 / local 幅值 / 总相位**（`remote_amplitudes`, `local_amplitudes`, `phases`）。

### A.2 信道融合（Channel）策略

| 代号 | 名称 | 做法 |
|------|------|------|
| **Single** | 单信道 | 每模态选 **η 最大** 的一个信道，只用它的谱/BPM |
| **Uniform** | 均匀融合 | 每模态 **72 信道谱等权平均** |
| **Vote (T0-V3)** | Per-tone 投票 | 每个 tone 先算 BPM + η·ρ 权重 → **直方图投票**得 BPM；谱侧用 conf 加权平均（方案 B） |
| **VoteP** | 持久性投票 | 在 Vote 基础上去掉 **跨窗 BPM 跳变大** 的不稳定 tone，再投票 |
| **Single-best per modal** | Modal top2 的信道侧 | 每个模态各自选 **能量比最高信道**（Plan2 Single），不做跨信道融合 |

### A.3 模态融合（Modal）策略

| 代号 | 名称 | 做法 |
|------|------|------|
| **Equal** | 等权 | remote / local / phase 三条谱 **1:1:1 融合** |
| **Top2** | 模态 top2 | 按各模态 score（η 或 conf）排序，**保留 top2 模态等权融合**，踢掉最弱模态 |
| **η-weight** | 能量比加权 | 三模态按 **η score 加权** 融合谱 |
| **Phase only** | 仅相位 | 只用 phase 模态（A 组实验） |

### A.4 Systematic 系列（Block A/B/C）

| 代号 | 全称 | 信道融合 | 模态融合 |
|------|------|----------|----------|
| **A1** | Phase η·ρ voting | Vote（仅 phase） | Phase only |
| **A2** | Phase persistence voting | VoteP（仅 phase） | Phase only |
| **B1** | **Vote→Equal modal** | **每模态 Vote → 一条谱** | **三模态 Equal** |
| **B2** | Vote→η modal | 每模态 Vote → 谱 | 三模态 η 加权 |
| **B3** | **Vote→Top2 modal** | **每模态 Vote → 谱** | **三模态 Top2** |
| **B4** | VoteP→Top2 modal | 每模态 VoteP → 谱 | Top2 |
| **C1** | Uniform→Top2 modal | 每模态 Uniform 平均谱 | Top2 |
| **C2** | Uniform→η modal | 每模态 Uniform | η 加权 |

> **命名注意**：Systematic **B1**（`b1_vote_modal_equal`）与 Baseline **B1 Uniform Remote**（`b1_uniform_remote`）是不同方法。

### A.5 Baseline 对照组

| 代号 | 全称 | 信道融合 | 模态融合 |
|------|------|----------|----------|
| **B0 Single Remote** | 单信道 remote | Single（仅 remote） | 无（单模态） |
| **B1 Uniform Remote** | remote 均匀 | Uniform（仅 remote） | 无 |
| **B2 Modal top2 equal** | Plan2 模态 top2 | Single-best per modal | Top2 等权 |
| **B3 Modal η-weight** | Plan2 模态 η | Single-best per modal | η 加权 |
| **T0-V3** | Per-Tone η·ρ vote | Vote（**仅 remote**） | 无 |
| **T3** | Voting+Modal hybrid | Vote + Modal 混合 | 见 `voting_fusion` 模块 |

### A.6 门控系列（G1–G6）

门控 **不再做新的信道/模态融合**，只在每 20 s 滑窗内对已有 BPM 候选做决策：

| 代号 | 候选来源 | 门控逻辑 |
|------|----------|----------|
| **G1–G3** | T0-V3 vs Modal top2 | 峰频差 ≤δ 则共识；否则按 conf/η 选择 |
| **G4** | T0-V3 vs Modal top2 | 共识则平均；**全分歧 → Single Remote** |
| **G5** | T0-V3 vs Modal top2 | voting 直方图 **双峰** 时选 modal 或 single |
| **G6** | T0-V3 vs Modal top2 | 仅用 **BPM 稳定 tone** 重投票 |

### A.7 本报告新增：G4-B1 系列

在 G4 上增加第三候选 **B1（Vote→Equal modal）**：

| 代号 | 三个候选 BPM | 门控差异 |
|------|--------------|----------|
| **G4-B1-v1** | T0-V3 / Modal top2 / **B1** | 两两或三者 BPM 差 ≤δ 则平均，否则 Single |
| **G4-B1-v2** | 同上 | 取 **最接近的一对** 共识，否则 Single |
| **G4-B1-v3** | 同上 | 同 v1，全分歧时 **fallback → B1** |
| **G4-B1-v4** | **B1 vs Modal top2** | 双候选 G4，去掉 T0-V3 |

各候选内部分别为：T0-V3 = remote Vote；Modal top2 = Single-best per modal + Top2；B1 = 每模态 Vote + Equal。

### A.8 D3 谱构造 Ablation

只改 B1/B3 内 **72 tone 谱如何合成**（信道仍为 Vote，模态仍为 Equal 或 Top2）：

| 代号 | 谱构造 | 含义 |
|------|--------|------|
| **conf B（默认）** | conf-weighted 全谱 | 所有 tone 谱按 voting 权重加权平均 |
| **D3-A winning-bin** | 窄带谱 | voting **最高票 bin ±2 BPM** 内 tone 平均谱 |
| **D3-C top-K** | Top-K 平均 | voting 权重 **Top-16/24** tone 等权平均谱 |

### A.9 G5-B1（091339 专项）

| 步骤 | 做法 |
|------|------|
| 信道+模态 | 同 B1（Vote→Equal） |
| 额外门控 | 每窗检测三模态 voting 双峰性；**剔除双峰模态** 后对剩余 Equal；多数双峰则 Single |

### A.10 本报告主要方法速查

```text
B1 (8.45%)       = Vote(每模态) → Equal(三模态)
B3 (9.92%)       = Vote(每模态) → Top2(三模态)
G4 (8.65%)       = 窗级: T0-V3 vs Modal_top2 → 分歧则 Single
G4-B1-v2 (8.05%) = 窗级: T0-V3 vs Modal_top2 vs B1 → 最近一对共识
Modal top2       = Single(每模态) → Top2
T0-V3            = Vote(仅 remote，无模态融合)
```
