# 模态×信道 系统性融合 — 验证报告

> **Plan**：[`docs/plans/systematic_modal_channel_fusion_plan.md`](../plans/systematic_modal_channel_fusion_plan.md)  
> **脚本**：`notebooks/scripts/chFusion_systematic_fusion.py`（核心模块：`src/ble_analysis/systematic_fusion.py`）  
> **场景**：`config/scenarios/cs_091339.json`、`cs_095806.json`、`cs_102621.json`  
> **日期**：2026-06-08  
> **状态**：已完成（P0 Block A/B/C）

---

## 1. 目标与假设

验证「模态融合 × 信道融合」二维策略网格中的关键盲区，分离信道策略与模态策略的独立贡献。

| ID | 假设 | Plan 引用 |
|----|------|-----------|
| H1 | Phase voting 跨域优于 Remote voting | §1.3 |
| H2 | 最优模态策略取决于信道策略（交互效应） | §1.3 |
| H3 | Voting per modal + Modal top2 跨域优于 T0-V3（9.20%）和 Modal top2（9.45%） | §1.3 |
| H4 | Phase voting 在 095806 场景特别有效 | §1.3 |
| H5 | Persistence voting 在 phases 上同样有效 | §1.3 |

**成功标准（Plan §5.3）**  
- 理想：任一新增方法跨域 < 8.5%  
- 良好：< 9.0%  
- 最低：B3（Vote→Top2）< T0-V3 且 < Modal top2  
- 失败：所有新增 > 9.45%

---

## 2. 方法摘要

| 项目 | 内容 |
|------|------|
| 观测量 | `remote_amplitudes`、`local_amplitudes`、`phases`（各 72 tone） |
| 信道策略（新增） | C-Vote（η·ρ voting + conf 加权全 tone 谱）、C-VoteP（persistence 筛选后 voting）、C-Uniform（72 信道谱等权） |
| 模态策略（新增） | M-Phase only、M-Equal、M-η、M-Top2（谱融合逻辑与 Plan2 Modal 一致） |
| Voting→谱构造 | 方案 B：所有 tone 的归一化谱按 voting 权重加权平均 |
| 滑窗 | 20 s / 1 s 步；呼吸带 0.1–0.35 Hz；与 Plan2 一致 |

**新增方法（P0）**

| ID | 方法 | 信道 × 模态 |
|----|------|-------------|
| A1 | Phase η·ρ voting | C-Vote × M-Phase |
| A2 | Phase persistence voting | C-VoteP × M-Phase |
| B1 | Vote→Equal modal | C-Vote per modal × M-Equal |
| B2 | Vote→η modal | C-Vote per modal × M-η |
| B3 | Vote→Top2 modal | C-Vote per modal × M-Top2 |
| B4 | VoteP→Top2 modal | C-VoteP per modal × M-Top2 |
| C1 | Uniform→Top2 modal | C-Uniform per modal × M-Top2 |
| C2 | Uniform→η modal | C-Uniform per modal × M-η |

---

## 3. 实验设置

| 场景 ID | 数据文件 | 备注 |
|---------|----------|------|
| cs_091339 | `sampleData/CS_frames_all_20260113_091339.jsonl` | voting 退化场景 |
| cs_095806 | `sampleData/CS_frames_all_20260116_095806.jsonl` | 段 4b 略短于窗长 |
| cs_102621 | `sampleData/CS_frames_all_20260116_102621.jsonl` | 跨域对照 |

- **Baseline**：B0–B3、T0-V3、T3、G4、Single/Uniform Phase（复用既有 benchmark）  
- **待测**：A1–A2、B1–B4、C1–C2（8 个新方法）  
- **指标**：分段 BPM err% mean/std、跨域 mean、消融对比、二维热力图

---

## 4. 结果

### 4.1 主结果表

| 排名 | 方法 | cs_091339 | cs_095806 | cs_102621 | **跨域 mean** |
|------|------|-----------|-----------|-----------|---------------|
| **1** | **B1 Vote→Equal modal** | 13.22 | 6.50 | **5.63** | **8.45%** |
| 2 | G4 Single fallback | 12.39 | 9.05 | 4.51 | 8.65% |
| 3 | C2 Uniform→η modal | 13.43 | 7.93 | 6.10 | 9.15% |
| 4 | B2 Vote→η modal | 15.65 | 6.47 | 5.35 | 9.16% |
| 5 | T0-V3 Per-Tone η·ρ | 13.77 | **6.84** | 6.99 | 9.20% |
| 6 | B2 Modal top2 equal | **13.04** | 10.61 | **4.69** | 9.45% |
| 7 | B3 Modal η-weight | 13.25 | 10.50 | 4.60 | 9.45% |
| 8 | T3 Voting+Modal hybrid | 14.92 | 7.94 | 6.24 | 9.70% |
| 9 | C1 Uniform→Top2 modal | 13.85 | 8.64 | 7.10 | 9.86% |
| 10 | B3 Vote→Top2 modal | 17.86 | 6.44 | 5.47 | 9.92% |
| — | A1 Phase η·ρ voting | 17.37 | **5.81** | 10.05 | 11.07% |
| — | A2 Phase persistence voting | 28.06 | 5.88 | 18.52 | 17.49% |
| — | B4 VoteP→Top2 modal | 29.56 | 6.39 | 13.81 | 16.59% |

### 4.2 消融分析（Plan §5.2）

| 消融对比 | 固定 | 变化 | 跨域 Δ | 结论 |
|----------|------|------|--------|------|
| A1 vs T0-V3 | C-Vote | Phase vs Remote | +1.87% | Phase voting **跨域更差** |
| B3 vs T0-V3 | C-Vote | Top2 vs Remote-only | +0.72% | 加模态融合 **未改善** voting |
| B3 vs Modal top2 | M-Top2 | Voting vs Single-best | +0.48% | Voting 替代 single-best **更差** |
| B4 vs B3 | M-Top2 | VoteP vs Vote | +6.66% | Persistence **严重退化** |
| C1 vs Modal top2 | M-Top2 | Uniform vs Single-best | +0.42% | Uniform 信道 **略差** |
| **B1 vs T0-V3** | C-Vote | Equal-3 vs Remote-only | **−0.75%** | **三模态等权谱融合有效** |
| **B1 vs G4** | — | Vote→Equal vs 门控 | **−0.20%** | **B1 为当前跨域最优** |

### 4.3 成功标准判定

| 级别 | 条件 | 判定 |
|------|------|------|
| 理想 | 跨域 < 8.5% | **达成**（B1 = **8.45%**） |
| 良好 | 跨域 < 9.0% | **达成**（B1、G4、C2、B2） |
| 最低 | B3 Vote→Top2 < T0-V3 且 < Modal top2 | **未达成**（B3 = 9.92%） |
| 失败 | 所有新增 > 9.45% | **未触发**（B1/B2/C2 均优于 9.45%） |

### 4.4 二维热力图与现象

图：
- `outputs/figures/systematic_fusion_leaderboard.png` — 跨域排行榜  
- `outputs/figures/systematic_fusion_2d_heatmap.png` — 信道×模态二维网格  
- `outputs/figures/systematic_fusion_ablation_waterfall.png` — 消融瀑布图  
- `outputs/figures/systematic_fusion_modal_selection.png` — B3 模态选择分布  

**关键现象：**

1. **B1（Vote per modal → 三模态等权谱融合）跨域 8.45%**，为所有已验证方法中的**全局最优**，略优于 G4（8.65%）。
2. **H3 的核心假设（Vote→Top2）未成立**：B3（9.92%）劣于 T0-V3 和 Modal top2；但 **Vote→Equal（B1）** 和 **Vote→η（B2）** 有效——说明模态融合权重模式是关键变量。
3. **Phase voting 场景分化极强**：A1 在 095806 为 5.81%（优于 T0-V3 6.84%），但在 091339 退化至 17.37%，跨域 11.07%。H4 **仅单场景支持**。
4. **Persistence 在模态融合框架下失效**：A2（17.49%）、B4（16.59%）均大幅退化；G6 的 persistence 优势未能迁移到 per-modal voting→谱融合。
5. **091339 是所有新方法的瓶颈**：B1 在 091339 仍为 13.22%，与 T0-V3（13.77%）接近；跨域改善主要来自 095806/102621。

---

## 5. 结论

| 结论 | 证据强度 |
|------|----------|
| Vote per modal + 三模态等权谱融合（B1）跨域最优 8.45% | **已验证**（三场景） |
| Vote→Top2（B3）不优于单模态 voting 或 Modal top2 | **已验证** |
| Phase voting 在 095806 优于 Remote voting | **仅单场景**（5.81% vs 6.84%） |
| Phase voting 跨域优于 Remote voting（H1） | **未证实**（11.07% vs 9.20%） |
| Persistence voting 可迁移到 phases / 模态融合（H5） | **已废弃**（A2/B4 大幅退化） |
| 信道策略与模态策略存在交互（H2） | **已验证** — Equal 融合有效但 Top2 无效 |
| 理想成功标准（< 8.5%）达成 | **已验证**（B1 = 8.45%） |

**相对 baseline**：B1（8.45%）优于 G4（8.65%）、T0-V3（9.20%）、Modal top2（9.45%），为当前**全局最优 pipeline 候选**。

**部署建议**：B1 值得进入下一轮 Review 作为默认 pipeline 候选，但 091339 上 13.22% 仍偏高；不建议部署 B3/B4/A2。Phase voting 仅可作为 095806 类场景的场景自适应选项。

---

## 6. 开放问题与下一步

| ID | 问题 | 建议 |
|----|------|------|
| Q1 | 为何 Vote→Equal 有效但 Vote→Top2 无效？ | 分析 B1/B3 窗级模态权重分布；top2 可能错误踢出有效模态 |
| Q2 | conf 加权谱 vs winning-bin 谱构造差异？ | Plan §8.2 Q1 ablation |
| Q3 | B1 在 091339 能否进一步改善？ | 结合 G5/G6 门控或场景自适应 |
| Q4 | B1 与 G4 能否组合？ | Vote→Equal 作为第三候选参与门控 |
| Q5 | 模态融合用 conf_vote 而非 η 作权重？ | B2（η）9.16% vs B1（conf via equal）8.45% 提示 equal 更稳 |

---

## 7. 复现

```bash
python notebooks/scripts/chFusion_systematic_fusion.py
```

| 产出 | 路径 |
|------|------|
| 数值结果（三场景） | `outputs/reports/systematic_fusion_results.npy` |
| 单场景缓存 | `outputs/reports/systematic_fusion_{091339,095806,102621}_results.npy` |
| 跨域汇总 | `outputs/reports/systematic_fusion_cross_domain.npy` |
| 排行榜图 | `outputs/figures/systematic_fusion_leaderboard.png` |
| 二维热力图 | `outputs/figures/systematic_fusion_2d_heatmap.png` |
| 消融瀑布图 | `outputs/figures/systematic_fusion_ablation_waterfall.png` |
| 模态选择图 | `outputs/figures/systematic_fusion_modal_selection.png` |
| 本报告 | `docs/reports/systematic_modal_channel_fusion_report.md` |

---

## 8. Plan 回填

- **验证状态**：已完成（P0 Block A/B/C）  
- **实际脚本**：`notebooks/scripts/chFusion_systematic_fusion.py`、`src/ble_analysis/systematic_fusion.py`  
- **结论一句话**：B1 Vote→Equal modal 跨域 8.45% 为全局最优，达理想标准；Vote→Top2 和 Persistence 模态融合未达预期；Phase voting 仅 095806 单场景有效。

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
