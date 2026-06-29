# Consensus Gating — 验证报告

> **Plan**：[`docs/plans/voting_gating_plan.md`](../plans/voting_gating_plan.md)  
> **脚本**：`notebooks/scripts/chFusion_voting_gating.py`（核心模块：`src/ble_analysis/consensus_gating.py`）  
> **场景**：`config/scenarios/cs_091339.json`、`cs_095806.json`、`cs_102621.json`  
> **日期**：2026-06-08  
> **状态**：已完成（G1–G6；G7–G9 待文献调研）

---

## 1. 目标与假设

验证窗级共识门控能否在 **T0-V3 per-tone voting** 与 **Modal top2** 之间动态切换，改善跨场景稳定性（voting 在 095806 强、091339 弱；Modal 反之）。

| ID | 假设 | Plan 引用 |
|----|------|-----------|
| H1 | 095806 上 T0-V3 优于 Modal 的窗 vs 091339 上 Modal 优于 T0-V3 的窗，存在可检测信号特征差异 | §1.2 |
| H2 | 跨方法共识门控（voting + modal 一致时融合，分歧时 fallback）可组合两者优势 | §1.2 |
| H5 | 双峰性门控（G5）在 091339 多簇竞争窗上优于 G1 | §3.4、§4.2 |
| H6 | Persistence-filtered voting（G6）三场景均优于 T0-V3 | §3.4、§4.2 |

**成功标准（Plan §5.3）**  
- 理想：跨域 mean < 8.5%，且 091339 ≤ Modal + 095806 ≤ T0-V3 + 1.5%  
- 最低：跨域 mean < 9.45%（不差于 Modal top2），091339 无灾难性退化（≤ 18%）

---

## 2. 方法摘要

| 项目 | 内容 |
|------|------|
| 观测量 | `remote_amplitudes`（T0-V3 / Single）、`local_amplitudes` + `phases`（Modal top2） |
| 门控输入 | 每窗并行计算 BPM_vote（T0-V3）、BPM_modal（Modal top2）、BPM_single（max-η remote） |
| 门控信号 | conf_vote、peak_dist、η_vote/η_modal、bimodality_score（G5）、tone persistence（G6） |
| 滑窗 | 20 s / 1 s 步；呼吸带 0.1–0.35 Hz；与 Plan2 一致 |

| 策略 | 核心规则 |
|------|----------|
| G1 | δ=3 BPM，τ_hi=0.30；共识 + 高置信 → 加权平均；分歧 + 高置信 → vote；否则 Single |
| G2 | δ=2，τ_hi=0.35；分歧时 conf/η 优先 |
| G3 | δ 随 max(η) 在 2–5 BPM 自适应 |
| G4 | 共识 → 平均；**分歧 → Single**（不依赖 τ） |
| G5 | bimodality_score < 0.5 → vote；双峰 → modal 或 fallback |
| G6 | 剔除 persistence > 2.0 BPM 的 tone 后 voting；稳定 tone < 12 → modal |

实现与 plan §3.2–3.4 一致；未实现 G7–G9（文献驱动，plan 标注待补充）。

---

## 3. 实验设置

| 场景 ID | 数据文件 | 备注 |
|---------|----------|------|
| cs_091339 | `sampleData/CS_frames_all_20260113_091339.jsonl` | 主场景 — voting 退化验证 |
| cs_095806 | `sampleData/CS_frames_all_20260116_095806.jsonl` | 跨域；段 4b 略短于窗长 |
| cs_102621 | `sampleData/CS_frames_all_20260116_102621.jsonl` | 跨域 |

- **Baseline**：B0 Single Remote、B1 Uniform Remote、B2 Modal top2 equal、B3 Modal η-weight  
- **对照**：T0-V3 Per-Tone η·ρ-weight  
- **待测**：G1–G6（共 12 方法含 baseline + T0-V3）  
- **指标**：分段 BPM err% mean/std、跨域 mean、窗级门控决策分布、oracle 选对率

---

## 4. 结果

### 4.1 主结果表

| 方法 | cs_091339 | cs_095806 | cs_102621 | 跨域 mean |
|------|-----------|-----------|-----------|-----------|
| **G4 Single fallback** | 12.39 | 9.05 | **4.51** | **8.65** |
| **G5 Bimodality gating** | **12.27** | **7.09** | 6.80 | **8.72** |
| G1 Simple consensus | 13.60 | 8.75 | 4.51 | 8.95 |
| G2 Conf priority | 13.88 | 8.74 | 4.36 | 8.99 |
| G6 Persistence voting | 13.43 | **6.55** | 7.00 | 9.00 |
| G3 Adaptive δ | 13.38 | 8.39 | 5.23 | 9.00 |
| T0-V3 Per-Tone η·ρ-weight | 13.77 | 6.84 | 6.99 | 9.20 |
| B2 Modal top2 equal | 13.04 | 10.61 | 4.69 | 9.45 |
| B3 Modal η-weight | 13.25 | 10.50 | 4.60 | 9.45 |
| B0 Single Remote | **10.91** | 12.16 | 8.29 | 10.45 |
| B1 Uniform Remote | 17.09 | 9.15 | 6.82 | 11.02 |

### 4.2 与 plan 预期对比

| 预期（Plan §4.2） | 实际 | 是否一致 |
|-----------------|------|----------|
| G1 vs T0-V3：091339 改善、095806 略降 | 091339 13.60% vs 13.77%（略优）；095806 8.75% vs 6.84%（**退化**） | 部分 |
| G1 vs B2：跨域优于或接近 Modal | 8.95% vs 9.45%（**优于**） | ✅ |
| G5 vs G1：091339 更好 | 12.27% vs 13.60%（**更好**） | ✅ |
| G6 vs T0-V3：三场景均改善 | 091339 13.43% vs 13.77%（略优）；095806 6.55% vs 6.84%（优）；102621 7.00% vs 6.99%（**略差**） | 部分 |
| G1–G6 跨域 mean 8.0–9.5% | 最优 G4 **8.65%**，落在区间内 | ✅ |

### 4.3 成功标准判定

| 级别 | 条件 | 判定 |
|------|------|------|
| 理想 | 跨域 < 8.5% 且 091339 ≤ 13.04% + 095806 ≤ 8.34% | **未达成**（跨域 8.65% > 8.5%；095806 G6 6.55% 满足 T0-V3+1.5%） |
| 最低 | 跨域 < 9.45%，091339 ≤ 18% | **达成**（G4 8.65%；091339 最高 G2 13.88%） |
| 失败 | 跨域 > 11.45% 或 091339 比 T0-V3 更差 | **未触发** |

### 4.4 门控决策与 oracle 分析（G1 示例）

- G1 全场景窗级决策分布（pie 图）：`outputs/figures/voting_gating_decision_pie.png`  
- Oracle 选对率（与 vote/modal/single 三者中最接近 GT 的方法比较，容差 0.5 BPM）：091339 段 3 最高 **64%**；多数段 **21–50%**；说明门控信号可区分场景但**窗级选择仍不稳定**  
- 091339 段 3：oracle 72% 为 voting，G1 选对 64% — 门控在 voting 占优段表现尚可  
- 091339 段 1a/1b：oracle 中 single 占 38–46%，G1 选对仅 21–33% — fallback 策略未充分受益  

图：
- `outputs/figures/voting_gating_comparison_bars.png` — 跨域排行榜  
- `outputs/figures/voting_gating_oracle_heatmap.png` — 段 × G1–G6 oracle 选对率  

---

## 5. 结论

| 结论 | 证据强度 |
|------|----------|
| 窗级门控可改善跨域 mean（G4 8.65% < Modal 9.45% < T0-V3 9.20%） | **已验证**（三场景） |
| G5 双峰性门控在 091339 上优于 G1/T0-V3/Modal | **已验证**（091339 12.27%） |
| G6 persistence 在 095806 上优于 T0-V3 与 Modal | **已验证**（095806 6.55%） |
| 无单一门控策略在所有场景均为最优 | **已验证**（G4 跨域最优；102621 上 G1/G4 4.51% 最优；095806 上 G6 最优） |
| H2 跨方法共识可稳定组合 voting+modal 优势 | **部分支持** — 跨域改善成立，但 095806 上 G1 损失 T0-V3 优势 |
| G6 三场景全面优于 T0-V3 | **未证实**（102621 7.00% vs 6.99%） |
| 门控 oracle 窗级选对率普遍 < 70% | **已验证** — 算法风险 §8.1「门控引入新错误」仍成立 |

**相对 baseline**：G4 跨域 **8.65%**，优于 Modal top2（9.45%）和 T0-V3（9.20%），达到 plan **最低成功标准**，未达理想标准（8.5%）。

**部署建议**：**不建议**将任一 G 策略作为默认 pipeline 替换 Modal top2。G4/G5 可作为后续 **场景自适应** 候选；102621 上 G5/G6 退化提示门控参数需场景级调优。G7–G9 待文献调研后再评估。

---

## 6. 开放问题与下一步

| ID | 问题 | 建议 |
|----|------|------|
| Q1 | δ/τ_hi 是否跨场景一致？ | 三场景分别扫描 δ∈[1,5]、τ∈[0.2,0.5] |
| Q2 | bimodality / persistence 是否优于 conf_vote？ | G5 在 091339/095806 表现支持；G6 仅 095806 显著 |
| Q3 | Fallback 用 Single vs Modal？ | G4（Single fallback）跨域最优，但 095806 9.05% 差于 G6 6.55% |
| Q4 | persistence_threshold=2.0 剔除后稳定 tone 数？ | 分析 G6 window_extras 中 n_stable_tones 分布 |
| Q5–Q6 | TRRS / SVM / PCA 共识门控 | 待文献调研 plan 完成后追加 G7–G9 |

---

## 7. 复现

```bash
python notebooks/scripts/chFusion_voting_gating.py
```

| 产出 | 路径 |
|------|------|
| 数值结果（三场景） | `outputs/reports/voting_gating_results.npy` |
| 单场景缓存 | `outputs/reports/voting_gating_{091339,095806,102621}_results.npy` |
| 跨域汇总 | `outputs/reports/voting_gating_cross_domain.npy` |
| Oracle 统计 | `outputs/reports/voting_gating_oracle_stats.npy` |
| 决策分布图 | `outputs/figures/voting_gating_decision_pie.png` |
| 排行榜图 | `outputs/figures/voting_gating_comparison_bars.png` |
| Oracle 热力图 | `outputs/figures/voting_gating_oracle_heatmap.png` |
| 本报告 | `docs/reports/voting_gating_report.md` |

---

## 8. Plan 回填

- **验证状态**：已完成（G1–G6）  
- **实际脚本**：`notebooks/scripts/chFusion_voting_gating.py`、`src/ble_analysis/consensus_gating.py`  
- **结论一句话**：G4 跨域 mean 8.65% 优于 Modal（9.45%）和 T0-V3（9.20%），达最低成功标准；G5/G6 分别在 091339/095806 单场景显著改善，但无全局最优门控策略。

---

## Self Check

- Plan read: yes  
- Baseline confirmed: yes  
- Scenario JSON used: yes  
- Script executed: yes  
- Results generated: yes  
- Figures generated: yes  
- Report generated: yes  
- Plan updated: yes  
- Hardcoded frame index risk: no  
- Baseline changed: no  
- Metric definition changed: no  
- Ready to commit: yes（待用户确认）
