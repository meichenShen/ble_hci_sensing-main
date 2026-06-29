# 信号级自适应门控与退化根因追查 — 验证报告

> **Plan**：[`docs/plans/signal_adaptive_gating_plan.md`](../plans/signal_adaptive_gating_plan.md)  
> **脚本**：`notebooks/scripts/chFusion_signal_adaptive_gating.py`（核心模块：`src/ble_analysis/signal_adaptive_gating.py`、`src/ble_analysis/consensus_gating.py`）  
> **场景**：`cs_091339` / `cs_095806` / `cs_102621`  
> **日期**：2026-06-08  
> **状态**：已完成

---

## 1. 目标与假设

验证去除硬编码 Remote fallback 的信号级自适应门控能否在跨域上优于 B1（8.45%），并追查 102621 B1 偏离条件与 091339 退化根因。

| ID | 假设 | Plan 引用 |
|----|------|-----------|
| H1 | B1 搅局窗上 `per_modal_bpm_spread` 显著高于改善窗 | §1.4 |
| H2 | 三候选一致性门控 + per-window best-single fallback 跨域优于 B1 | §1.4 |
| H3 | 091339 退化与 per-tone η 系统性偏低相关 | §1.4 |

---

## 2. 方法摘要

| 项目 | 内容 |
|------|------|
| 观测量 | remote / local / phases（不含 total amplitudes） |
| 新增 baseline | Single Remote/Local/Phase（max-η 选道）、Best Single（per-window max η·ρ 动态选道） |
| SA-v1 | 三候选一致性门控 + best-single fallback；consensus_score 阈值 0.4，δ=3 BPM |
| SA-v1-noB1 | 候选池移除 B1 |
| SA-v2 | remote per-tone η 质量三级门控；阈值在 102621 标定后 hold-one-scene-out 应用于 091339/095806 |
| SA-v1+SingleRemote | 消融：全分歧→Single Remote（硬编码 fallback 对照） |
| P1 | 102621 窗级 B1 偏离条件后分析 |
| P3 | 三场景 per-tone η 分布 + 091339 max-η 分组 B1 error |

---

## 3. 实验设置

| 场景 ID | 数据文件 | 备注 |
|---------|----------|------|
| cs_091339 | `sampleData/CS_frames_all_20260113_091339.jsonl` | P3 诊断主场景 |
| cs_095806 | `sampleData/CS_frames_all_20260116_095806.jsonl` | SA 验证 |
| cs_102621 | `sampleData/CS_frames_all_20260116_102621.jsonl` | P1 追查 + SA-v2 阈值标定 |

- **Baseline（引用）**：B1 8.45%、T0-V3 9.20%、Modal top2 9.45%、Single Remote 10.45%
- **SA-v2 标定（102621）**：τ_high=0.728、τ_low=0.759、cv_thresh=0.169
- **指标**：分段 BPM 相对误差 % mean/std、跨域 mean

---

## 4. 结果

### 4.1 主结果表

| 方法 | cs_091339 | cs_095806 | cs_102621 | 跨域 mean |
|------|-----------|-----------|-----------|-----------|
| **B1 Vote→Equal** | 13.22 | **6.50** | **5.63** | **8.45** |
| T0-V3 | 13.77 | 6.84 | 6.99 | 9.20 |
| Modal top2 | 13.04 | 10.61 | **4.69** | 9.45 |
| SA-v1+SingleRemote | 11.05 | 11.77 | 7.73 | 10.18 |
| Single Remote | 10.91 | 12.16 | 8.29 | 10.45 |
| **SA-v2** | 17.48 | **6.99** | 7.52 | 10.66 |
| SA-v1 | 18.66 | 7.25 | 8.34 | 11.42 |
| SA-v1-noB1 | 19.67 | 7.08 | 8.99 | 11.91 |
| Best Single (η·ρ) | 20.40 | 7.63 | 9.26 | 12.43 |
| Single Phase | 15.13 | 11.12 | 12.55 | 12.93 |
| Single Local | **30.49** | 13.17 | 7.32 | 16.99 |

### 4.2 与 plan 预期对比

| 预期（Plan §5.3） | 实际 | 是否一致 |
|-------------------|------|----------|
| 理想：SA-v1 跨域 < 7.8% | SA-v1 = 11.42% | ❌ |
| 良好：SA-v1 跨域 < 8.0% | SA-v1 = 11.42% | ❌ |
| 最低：至少一个 SA 变体跨域 < B1 | 最优 SA-v2 = 10.66% > 8.45% | ❌ |
| P1 产出 B1 偏离明确信号特征 | 102621 上 b1_disruptor 占比 **0%** | ❌ |
| P3：low-η 窗 B1 error > high-η 窗 | low=10.15% < mid=21.15% > high=15.37%（非单调） | 部分 |

### 4.3 关键发现

**P1（102621 B1 偏离条件）**

| 窗类型 | 占比 |
|--------|------|
| B1 搅局窗（b1_deviation>3 且 modal_vote_divergence≤3） | **0.0%** |
| B1 改善窗（error_b1 < error_pair − 0.5pp） | 37.7% |
| 三者分散窗 | 0.0% |
| 其他 | 62.3% |

102621 上**不存在** plan 定义的「双候选已共识但 B1 偏离」搅局窗 → **H1 未证实**。B1 在 102621 多数窗为改善或中性，与 G4-B1-v2 在 102621 上略差于 G4（5.50% vs 4.51%）的现象不能通过「B1 搅局」机制解释。

**单模态质量场景依赖性（验证 remote 非全局最优）**

| 场景 | Best Single 选道分布（窗数） |
|------|------------------------------|
| cs_102621 | local **81** / remote 50 / phase 15 |
| cs_091339 | remote **101** / phase 28 / local 19 |
| cs_095806 | phase **56** / local 55 / remote 32 |

三场景 remote 选中率分别为 33%、58%、27% — **硬编码 Remote fallback 确实不能泛化**（支持 plan §2.3 物理动机），但动态 best-single 本身跨域 12.43% 劣于 B1。

**SA-v1+SingleRemote 消融**

| 场景 | SA-v1 | SA-v1+SingleRemote |
|------|-------|-------------------|
| 102621 | 8.34% | **7.73%** |
| 091339 | 18.66% | **11.05%** |
| 095806 | **7.25%** | 11.77% |

硬编码 Remote fallback 在 102621/091339 上**降低** error，但在 095806 上**显著恶化**（+4.5pp）→ 跨域 10.18% 仍差于 B1。

**P3（091339 η 质量 vs B1 error，按 max-η 三等分）**

| max-η 分组 | B1 窗级 error mean |
|------------|-------------------|
| 低 η（下 1/3） | **10.15%** |
| 中 η（中 1/3） | **21.15%** |
| 高 η（上 1/3） | 15.37% |

低 η 窗 error 最低，但中 η 组反而最高 → η 质量与退化的关系**非简单单调**，H3 仅部分支持，不能作为可靠门控特征。

### 4.4 图表

- `outputs/figures/sa_leaderboard.png` — 跨域排行榜
- `outputs/figures/sa_p1_b1_deviation_scatter.png` — P1 散点（102621）
- `outputs/figures/sa_p1_window_type_pie.png` — P1 窗类型分布
- `outputs/figures/sa_decision_distribution.png` — SA-v1 门控决策分布
- `outputs/figures/sa_single_modality_comparison.png` — 单模态三场景对比
- `outputs/figures/sa_ablation_fallback_modality.png` — SA-v1 vs SA-v1+SingleRemote 消融
- `outputs/figures/sa_p3_eta_distribution.png` — 三场景 per-tone η 箱线图
- `outputs/figures/sa_p3_eta_vs_error.png` — 091339 max-η vs B1 error

---

## 5. 结论

| 结论 | 证据强度 |
|------|----------|
| 无 SA 变体跨域优于 B1（8.45%） | **已验证**（SA-v2 最优 10.66%） |
| remote/local/phase 最优模态场景依赖，硬编码 Remote fallback 不可泛化 | **已验证**（best-single 选道分布跨场景显著不同） |
| 102621 上 B1「搅局」机制不成立 | **已验证**（b1_disruptor = 0%） |
| 091339 退化与 η 质量简单相关 | **未证实**（三等分 error 非单调） |

**相对 baseline**：所有 SA 变体均**劣于** B1 Vote→Equal（跨域 +2.2pp 至 +3.0pp）。SA-v2 在 095806/102621 单场景接近 B1，但 091339 上 17.48% 严重拖累跨域。

**部署建议**：**不推荐**将 SA-v1/v2 纳入默认 pipeline。B1 无门控方案仍为当前全局最优无门控策略；门控层需另寻机制（上一轮 G4-B1-v2 8.05% 仍优于本次所有 SA 变体）。

---

## 6. 遗留问题

| ID | 问题 | 状态 |
|----|------|------|
| Q1 | 102621 上 B1 优于门控的真正原因是否在于共识窗上 B1 已足够好、门控引入额外 fallback 噪声？ | `[待确认]` |
| Q2 | 091339 中 η 组 error 呈「中>高>低」非单调，是否存在除 η 外的主导因素（如多径结构）？ | `[待确认]` |
| Q3 | SA-v2 仅用 remote η 是否在 local/phase 更优的窗上过度保守？ | `[待确认]` — plan §3.2.3 已标注 |

---

## 7. 产出清单

| 类型 | 路径 |
|------|------|
| 验证报告 | `docs/reports/signal_adaptive_gating_report.md` |
| 数值结果 | `outputs/reports/signal_adaptive_gating_{091339,095806,102621}_results.npy` |
| 跨域汇总 | `outputs/reports/signal_adaptive_gating_cross_domain.npy` |
| 图表 | `outputs/figures/sa_*.png` |
| 核心模块 | `src/ble_analysis/signal_adaptive_gating.py` |
| 扩展模块 | `src/ble_analysis/consensus_gating.py`（`compute_triplet_consensus_score`、`compute_per_tone_eta_stats`） |

---

## 8. Git commit 建议

```
Validate signal-adaptive gating (SA-v1/v2)

中文正文：
- 本次完成：实现并运行信号级自适应门控实验（P1/P2/P3），三场景全部执行。
- 对应 plan：docs/plans/signal_adaptive_gating_plan.md
- 修改脚本：notebooks/scripts/chFusion_signal_adaptive_gating.py
- 修改模块：src/ble_analysis/signal_adaptive_gating.py、src/ble_analysis/consensus_gating.py
- 输出结果：outputs/reports/signal_adaptive_gating_*.npy
- 输出图表：outputs/figures/sa_*.png
- 报告路径：docs/reports/signal_adaptive_gating_report.md
- 当前结论：无 SA 变体跨域优于 B1（8.45%）；remote 非全局最优已验证；H1/H3 未证实。
- 后续问题：门控层需另寻机制，或回到信道选择层改进 091339。
```
