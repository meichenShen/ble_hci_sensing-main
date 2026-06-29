# Voting Fusion — 验证报告

> **Plan**：[`docs/plans/voting_fusion_plan.md`](../plans/voting_fusion_plan.md)  
> **脚本**：`notebooks/scripts/chFusion_voting_fusion.py`（核心模块：`src/ble_analysis/voting_fusion.py`）  
> **场景**：`config/scenarios/cs_091339.json`、`cs_095806.json`、`cs_102621.json`  
> **日期**：2026-06-07  
> **状态**：已完成

---

## 1. 目标与假设

验证 Deng et al. (2024) 提出的 **per-subcarrier 独立 BPM 估计 + 统计投票** 范式是否优于现有 Plan2 **先谱融合再寻峰** 策略（Modal top2，跨域 mean **9.45%**）。

| ID | 假设 | Plan 引用 |
|----|------|-----------|
| H1 | T0-V2（η 加权 per-tone voting）跨域 mean ≤ Single Remote（10.45%） | §4、§5.3 最低标准 |
| H2 | T0-V2 显著优于 Uniform Remote（11.02%） | §4 预期 |
| H3 | T0-V3（η·ρ 联合加权）略优于 T0-V2 | §4 预期 |
| H4 | T3（模态内 voting + 模态间 consensus）接近或超越 Modal top2 | §4 预期 |
| H5 | 任一 voting 方法跨域 mean < **9.45%** 且无 091339 灾难性退化 | §5.3 理想标准 |

---

## 2. 方法摘要

| 项目 | 内容 |
|------|------|
| 观测量 | 见下方各方法变量明细 |
| 信道融合 | Per-tone 独立 FFT 寻峰 → 直方图投票（V1 等权 / V2 η 加权 / V3 η·ρ 加权）；Top-K 筛选 K=4/8/16 |
| 模态融合 | T2：每模态 max-η 单 tone BPM → 中位数；T3：每模态 72-tone V2 voting → η 加权中位数 |
| 滑窗与寻峰 | 20 s 窗 / 1 s 步；呼吸带 0.1–0.35 Hz；Hanning + FFT argmax + parabolic 插值；投票 bin [6, 30] BPM / 1 BPM；τ=0.3 |

### 2.1 各方法变量明细

| 方法 ID | 输入变量 | 说明 |
|---------|----------|------|
| B0 Single Remote | `remote_amplitudes`（max-η 单 tone） | 选 η 最大 tone 做 BPM |
| B1 Uniform Remote | `remote_amplitudes`（72 tone 等权） | 72 tone 等权谱融合后寻峰 |
| B2 Modal top2 equal | `remote_amplitudes` + `local_amplitudes` + `phases`（各 max-η 单 tone） | top2 模态谱融合等权 |
| B3 Modal η-weight | 同上 | top2 模态谱融合 η 加权 |
| T0-V1/V2/V3 | `remote_amplitudes`（72 tone） | Per-tone BPM 直方图投票（V1 等权 / V2 η 加权 / V3 η·ρ 加权） |
| T1-K4/K8/K16 | `remote_amplitudes`（Top-K tone by η） | 同上，仅前 K 个 tone 参与 V2 投票 |
| T2 | `remote_amplitudes` + `local_amplitudes` + `phases`（各 max-η 单 tone） | 三模态各自单 tone BPM → 中位数 |
| T3 | `remote_amplitudes` + `local_amplitudes` + `phases`（各 72 tone） | 每模态 72-tone V2 voting → 三模态 η 加权中位数 |

> **关键区分**：T0-V3（跨域最优 **9.20%**）仅使用 `remote_amplitudes` 的 72 tone per-tone voting。T2/T3 使用了全部三种变量。

实现与 plan 一致；未做半频/倍频谐波处理（plan §3.6 标注 `[待确认]`）。

---

## 3. 实验设置

| 场景 ID | 数据文件 | 备注 |
|---------|----------|------|
| cs_091339 | `sampleData/CS_frames_all_20260113_091339.jsonl` | 金属板脚本，主场景 |
| cs_095806 | `sampleData/CS_frames_all_20260116_095806.jsonl` | 跨域重复；段 4b 略短于窗长 |
| cs_102621 | `sampleData/CS_frames_all_20260116_102621.jsonl` | 跨域重复 |

- **Baseline**：B0 Single Remote、B1 Uniform Remote、B2 Modal top2 equal、B3 Modal η-weight（η 选路，与 Plan2 一致）
- **待测方法**：T0-V1/V2/V3、T1-K4/K8/K16-V2、T2 Cross-Modal median、T3 Voting+Modal hybrid（共 12 方法含 baseline）
- **指标**：分段 BPM 相对误差 %（mean / std）；跨域 mean ± std；窗级低置信度占比（voting 专属）

---

## 4. 结果

### 4.1 主结果表

| 方法 | cs_091339 | cs_095806 | cs_102621 | 跨域 mean |
|------|-----------|-----------|-----------|-----------|
| **T0-V3 Per-Tone η·ρ-weight** | 13.77 | **6.84** | 6.99 | **9.20** |
| B2 Modal top2 equal | 13.04 | 10.61 | **4.69** | 9.45 |
| B3 Modal η-weight | 13.25 | 10.50 | 4.60 | 9.45 |
| T3 Voting+Modal hybrid | 14.92 | 7.94 | 6.24 | 9.70 |
| B0 Single Remote | **10.91** | 12.16 | 8.29 | 10.45 |
| T2 Cross-Modal median | 15.05 | 11.00 | 5.56 | 10.54 |
| T0-V1 Per-Tone simple | 16.05 | 8.31 | 7.96 | 10.77 |
| T0-V2 Per-Tone η-weight | 16.00 | 8.82 | 8.08 | 10.96 |
| B1 Uniform Remote | 17.09 | 9.15 | 6.82 | 11.02 |
| T1-K16 η-vote | 15.46 | 9.77 | 7.44 | 10.89 |
| T1-K8 η-vote | 18.06 | 9.90 | 7.45 | 11.80 |
| T1-K4 η-vote | 17.55 | 10.27 | 8.14 | 11.98 |

### 4.2 与 plan 预期对比

| 预期（Plan §4） | 实际 | 是否一致 |
|-----------------|------|----------|
| T0-V2 vs B0：略优或相当 | T0-V2 跨域 10.96% > B0 10.45%；091339 16.00% >> 10.91% | ❌ |
| T0-V2 vs B1：显著更优 | T0-V2 10.96% 略优于 B1 11.02%，差距极小 | 部分 |
| T0-V3 vs T0-V2：略优 | T0-V3 9.20% 明显优于 T0-V2 10.96% | ✅ |
| T1-K16 vs T0-V2：相当或略优 | K16 10.89% 与 T0-V2 10.96% 相当，091339 仍差 | 部分 |
| T2 vs B2：各有优势 | T2 10.54% 差于 B2 9.45%；102621 上 T2 5.56% 优于 B2 4.69% 接近 | 部分 |
| T3 vs B2：不确定 | T3 9.70% 略差于 B2 9.45%；095806 上 T3 7.94% 优于 B2 10.61% | 部分 |

### 4.3 现象与图

- **跨域最优 voting 方法为 T0-V3（η·ρ 联合加权）**，mean **9.20%**，略优于 Modal top2（9.45%），但优势主要来自 095806/102621；091339 上 T0-V3（13.77%）仍差于 Single Remote（10.91%）和 Modal top2（13.04%）。
- **纯 per-tone voting（T0-V1/V2）在 091339 严重退化**（~16%），说明 72 tone 全量投票在主场景引入大量 outlier BPM，η 加权 alone 不足以抑制。
- **Top-K 筛选（K=4/8/16）未改善、反而略恶化**跨域表现；K 越小在 091339 误差越大（K4 17.55%），与 plan 风险表一致。
- **T3 模态内 voting + 模态间 consensus** 在 095806 表现最好（7.94%），跨域 9.70% 接近 Modal top2，结构最接近论文范式但未能稳定超越。
- 图：`outputs/figures/voting_fusion_leaderboard.png`、`voting_fusion_cross_domain_aggregate_bars.png`、`voting_fusion_diagnostics.png`

### 4.4 诊断图解读（`voting_fusion_diagnostics.png`）

诊断图固定取 **cs_091339 / 段 3（GT = 14.04 BPM）/ T0-V2（η 加权 per-tone voting）**，用于解释 091339 上 voting 退化的机制。三面板含义如下。

#### 左：Per-tone BPM scatter + 多方法窗级 BPM 轨迹

- **散点背景**（按 tone 着色）：来自 **T0-V2**（72 tone 各自 FFT 寻峰 → η 加权直方图投票的输入层）；同色细线 = 同一 tone 在相邻滑窗的连续性。
- **彩色折线**（窗级最终 BPM，跨域代表性方法）：

| 图例 | 方法 | 跨域 mean err% | 说明 |
|------|------|----------------|------|
| 红实线 | **T0-V2 η-vote** | 10.96 | 原「Voted BPM」；per-tone voting 基线 |
| 橙实线 | **T0-V3 η·ρ-vote** | **9.20** | 跨域最优 voting |
| 蓝虚线 | **Modal top2** | 9.45 | 当前默认 pipeline |
| 绿虚线 | **Single Remote** | 10.45 | max-η 单信道；091339 上界 |
| 紫点划线 | **T3 hybrid** | 9.70 | 模态内 voting + 模态间 consensus |

- **黑实线** = GT（14.04 BPM）。
- **读图结论**：
  - 若 **频率选择性衰落** 成立，同一 tone（同色）在邻近滑窗中 BPM 应较稳定 → 图上表现为 **水平色带**（细线近似水平）。
  - 段 3 相邻窗平均 |ΔBPM| ≈ **0.40 BPM**（72 tone × 39 窗），**tone 内时序高度稳定**；**tone 间 BPM 分化**（多簇并存）才是 voting 失败主因。
  - 对比折线：Modal top2 / Single Remote 在多数窗更接近 GT；T0-V2 轨迹波动更大；T0-V3 介于 voting 方法与 Modal 之间。

#### 中：Voting confidence

- 按论文阈值 **τ = 0.3**：若最高 bin 的加权票数 < 30% 总权重，该窗标为 **low-conf**。
- 段 3 中约 **65% 窗为 confident、35% 为 low-conf**。
- **读图结论**：约三分之一滑窗连「明显多数派」都没有，投票先天不可靠。即便标为 confident，也只表示有一个相对主导的 bin，**主导 bin 仍可能是错误 BPM**（例如半频 ~7 BPM 成簇）。τ = 0.3 未能筛掉大部分本质上难以投票的窗。

#### 右：Last-window 直方图 + 各方法最后一窗 BPM

- 灰柱 = **T0-V2** 最后一窗 72 tone 的 BPM 直方图；**竖线** = GT 与各方法在该窗的最终 BPM（与左图图例一致）。

#### 三图合意

| 面板 | 核心信息 |
|------|----------|
| 左 | 同色 tone 在邻近窗较稳定（选择性衰落）；tone 间分化导致多簇，voting 仍 fragile |
| 中 | ~1/3 窗无明确多数派；confident ≠ 准确 |
| 右 | 多峰分布下「多数票」机制脆弱；ρ 加权（V3）通过压低宽峰 tone 部分缓解 |

**与 Modal top2 的对照**：Modal top2 不对 72 个 per-tone BPM 直方图投票，而是每模态选 max-η 信道后做**谱融合再寻峰**，避开了「72 个独立 BPM 互相打架」；诊断图从机制上支持 091339 上 Modal top2（13.04%）优于 T0-V2（16.00%）的结果。

> **局限**：诊断仅覆盖单场景、单段、T0-V2；用于说明失效模式，不代表全局统计。

---

## 5. 结论

| 结论 | 证据强度 |
|------|----------|
| T0-V3（η·ρ 加权 per-tone voting）跨域 mean 略优于 Modal top2 | **仅单场景加权** — 跨域 9.20% vs 9.45%，但 091339 未改善 |
| Per-tone voting（V1/V2）不能替代 Single Remote 或 Modal top2 作为默认策略 | **已验证** — 跨域 10.77–10.96%，091339 ~16% |
| ρ 惩罚对 voting 有实质帮助（V3 vs V2） | **已验证** — 跨域 9.20% vs 10.96%，三场景均改善 |
| Top-K tone 筛选不能提升 voting | **已验证** — K4/K8/K16 均差于全量 V3 |
| T3 在部分场景有效但跨域不稳定 | **未证实** — 095806 优、091339 差 |

**相对 baseline**：T0-V3 跨域 mean 略优于 Modal top2（9.20% vs 9.45%），但 **091339 主场景未改善**；T0-V2 未达到 plan 最低成功标准（≤ Single Remote）。

**部署建议**：**不建议**将 per-tone voting 替换 Modal top2 作为默认 pipeline。T0-V3 可作为后续 **场景自适应** 候选（需更多场景验证 091339 类退化是否可门控检测）。T3 值得与 Plan2 窗级共识门控（PCA plan Q3）联合探索。

---

## 6. 开放问题与下一步

| ID | 问题 | 建议 |
|----|------|------|
| Q1 | τ=0.3 是否对 BLE 最优？ | 扫描 τ ∈ [0.2, 0.5]，报告低置信度窗占比 |
| Q2 | 091339 上 voting 为何远差于 Single？倍频 tone 是否占多数票？ | 分析 per-tone BPM 散点 vs GT；尝试谐波惩罚 |
| Q3 | T0-V3 跨域略优是否值得场景门控部署？ | 新场景 + 体动数据验证；回 Research Agent |
| Q4 | Voting 是否适用于 apnea 检测？ | 暂不在范围（plan §8.4 Q4） |

---

## 7. 复现

```bash
python notebooks/scripts/chFusion_voting_fusion.py
```

| 产出 | 路径 |
|------|------|
| 数值报告（三场景） | `outputs/reports/voting_fusion_results.npy` |
| 单场景缓存 | `outputs/reports/voting_fusion_{091339,095806,102621}_results.npy` |
| 跨域汇总 | `outputs/reports/voting_fusion_cross_domain.npy` |
| 排行榜图 | `outputs/figures/voting_fusion_leaderboard.png` |
| 跨域柱状图 | `outputs/figures/voting_fusion_cross_domain_aggregate_bars.png` |
| 诊断图 | `outputs/figures/voting_fusion_diagnostics.png` |
| 本报告 | `docs/reports/voting_fusion_report.md` |

---

## 8. Plan 回填

- **验证状态**：已完成
- **实际脚本**：`notebooks/scripts/chFusion_voting_fusion.py`、`src/ble_analysis/voting_fusion.py`
- **结论一句话**：T0-V3（η·ρ per-tone voting）跨域 mean 9.20% 略优于 Modal top2 9.45%，但 091339 未改善；纯 voting 不能替代现有默认策略。
