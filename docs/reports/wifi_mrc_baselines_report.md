# WiFi MRC 方法迁移 — 验证报告

> **Plan**：[`docs/plans/wifi_mrc_baselines_plan.md`](../plans/wifi_mrc_baselines_plan.md)  
> **脚本**：`notebooks/scripts/chFusion_wifi_mrc_baselines.py`（核心模块：`src/ble_analysis/wifi_mrc.py`）  
> **场景**：`config/scenarios/cs_091339.json`、`cs_095806.json`、`cs_102621.json`  
> **日期**：2026-06-16  
> **状态**：已完成

---

## 1. 目标与假设

验证 WiFi 文献中的时域 η-MRC（Fan 2024）与 √η-MRC + PCA 符号校正（WiFi-Sleep / Yu 2021）迁移到 BLE CS 后，BPM 估计能否达到或超越当前谱域 baseline B1（8.45% 跨域 mean）。

| ID | 假设 | Plan 引用 |
|----|------|-----------|
| H1 | Fan-BLE（Best modal）弱于 B1，因丢弃多模态互补 | §4.3 |
| H2 | MRC-PCA-η-sqrt 优于 MRC-PCA-no-sign → BLE 存在 tone 间反相 | §8.4 Q1 |
| H3 | Fan-η-equal 接近 B1 → Voting vs MRC 信道融合非关键差异 | §4.3 |
| H4 | 时域 signed MRC 可挑战谱域 B1 | §1.1 核心问题 |

**成功标准（Plan §5.3）**  
- 最低：某 MRC 方法跨域 mean ≤ 12%  
- 合格：跨域 mean ≤ 10%  
- 良好：跨域 mean ≤ 9%  
- 优秀：跨域 mean ≤ 8.5%（达到 B1）

---

## 2. 方法摘要

| 项目 | 内容 |
|------|------|
| 观测量 | `remote_amplitudes`、`local_amplitudes`、`phases`（各 72 tone） |
| Fan-BLE | 每模态 η 加权时域 MRC → Best modal 或三模态 BPM 等权 |
| MRC-PCA-BLE | √η 加权 + NumPy PCA 第一主成分符号校正（top-36 tone）→ Best modal 或 Equal |
| BPM 估计（MRC 方法） | Welch PSD 寻峰 + parabolic 细化，呼吸带 0.1–0.35 Hz |
| 滑窗 | 20 s / 1 s，与 B1 相同滤波链 |

**实现说明**：未引入 sklearn；PCA 符号校正使用 `np.linalg.eigh` 协方差特征分解。Baseline 复用既有 `chfusion` / `systematic_fusion` / `voting_fusion` 实现。

---

## 3. 实验设置

| 场景 ID | 数据文件 | 备注 |
|---------|----------|------|
| cs_091339 | `sampleData/CS_frames_all_20260113_091339.jsonl` | 最困难场景 |
| cs_095806 | `sampleData/CS_frames_all_20260116_095806.jsonl` | 段 4b 略短于窗长，MRC 跳过 |
| cs_102621 | `sampleData/CS_frames_all_20260116_102621.jsonl` | 跨域对照 |

- **Baseline**：B0 Single Remote、B1 Uniform Remote、Modal top2 equal、B1 Vote→Equal modal  
- **待测**：Fan-η-linear / sqrt / equal；MRC-PCA-η-sqrt / equal / no-sign  
- **指标**：分段 BPM 相对误差 % mean/std、跨域 mean、90th percentile、within 1/2 BPM ratio

---

## 4. 结果

### 4.1 主结果表

| 排名 | 方法 | cs_091339 | cs_095806 | cs_102621 | **跨域 mean** |
|------|------|-----------|-----------|-----------|---------------|
| **1** | **B1 Vote→Equal modal** | 13.22 | **6.50** | **5.63** | **8.45%** |
| 2 | Modal top2 equal | 13.04 | 10.61 | **4.69** | 9.45% |
| 3 | B0 Single Remote | 10.91 | 12.16 | 8.29 | 10.45% |
| 4 | MRC-PCA-η-equal | 17.63 | 7.29 | 7.41 | 10.78% |
| 5 | B1 Uniform Remote | 17.09 | 9.15 | 6.82 | 11.02% |
| 6 | MRC-PCA-η-sqrt | 19.09 | 8.41 | 8.33 | 11.95% |
| 7 | Fan-η-equal | 18.78 | 11.79 | 9.97 | 13.51% |
| 8 | Fan-η-linear | 20.31 | 13.37 | 11.95 | 15.21% |
| 9 | Fan-η-sqrt | 21.17 | 14.06 | 12.23 | 15.82% |
| 10 | MRC-PCA-no-sign | 21.17 | 14.06 | 12.23 | 15.82% |

数据来源：`outputs/reports/wifi_mrc_baselines_results.npy`

### 4.2 与 plan 预期对比

| 预期（Plan §4.3） | 实际 | 是否一致 |
|-------------------|------|----------|
| Fan-η-linear 略差于 B1 | 15.21% vs 8.45% | ✅ 显著更差 |
| Fan-η-equal vs B1 为关键对比 | 13.51% vs 8.45% | ✅ MRC 信道融合 + Equal 仍明显差于 Voting + Equal |
| MRC-PCA-η-sqrt > MRC-PCA-no-sign | 11.95% vs 15.82% | ✅ PCA 符号校正有效（Δ≈−3.9%） |
| MRC-PCA vs B1 不确定 | 最优 MRC 10.78%，仍差 B1 | ✅ 谱域 B1 仍优 |
| Fan-η-linear 差于 Fan-η-equal | 15.21% vs 13.51% | ✅ 多模态互补重要 |

### 4.3 成功标准判定

| 级别 | 条件 | 判定 |
|------|------|------|
| 最低（≤12%） | 某 MRC 跨域 ≤ 12% | **达成**（MRC-PCA-η-equal = 10.78%） |
| 合格（≤10%） | Fan 或 MRC-PCA ≤ 10% | **未达成**（10.78% 略超） |
| 良好（≤9%） | 接近 Modal top2 | **未达成** |
| 优秀（≤8.5%） | 达到 B1 | **未达成** |

注：MRC-PCA-η-equal 跨域 10.78%，仅比合格线高 0.78%；在 cs_095806 / cs_102621 两场景分别为 7.29% / 7.41%，表现尚可，但 cs_091339 拖高至 17.63%。

### 4.4 消融与窗口级指标

图：
- `outputs/figures/wifi_mrc_baselines_leaderboard.png`
- `outputs/figures/wifi_mrc_baselines_cross_domain_summary.png`
- `outputs/figures/wifi_mrc_baselines_ablation.png`
- `outputs/figures/wifi_mrc_baselines_091339.png` / `095806.png` / `102621.png`

**关键现象：**

1. **PCA 符号校正必要**：MRC-PCA-η-sqrt（11.95%）显著优于 MRC-PCA-no-sign（15.82%），支持 BLE tone 间存在呼吸波形反相（Plan Q1）。
2. **Voting 信道融合不可替代**：Fan-η-equal（13.51%）仍远差于 B1（8.45%），说明在同样三模态 Equal 融合下，MRC 时域合并不如 η·ρ Voting 谱构造。
3. **Best modal 策略不稳定**：Fan-η-linear 在 cs_091339 达 20.31%，单模态丢弃互补信息。
4. **MRC-PCA-no-sign 与 Fan-η-sqrt 数值相同**：两者在 Best modal + √η 权重下产生相同 BPM 轨迹（无 PCA 符号时行为等价）。

---

## 5. 结论

### 已验证

- WiFi 时域 MRC 迁移在 BLE CS 上**可运行**，MRC-PCA-η-equal 跨域 10.78%，优于 Fan 系列（13.5–15.8%）。
- **PCA 符号校正**在 BLE 72 tone 上产生 measurable 收益（≈4% 跨域 mean 改善）。
- **多模态 Equal 融合**对 Fan 系列有收益（Fan-η-equal 优于 Fan-η-linear）。
- **谱域 B1（Vote→Equal）仍为跨域最优**（8.45%），时域 MRC 未能超越。

### 仅单场景

- MRC-PCA-η-sqrt 在 cs_095806（8.41%）和 cs_102621（8.33%）接近 B1 水平，但 cs_091339（19.09%）拉高跨域 mean — **不能**视为全局优于 B1。

### 未证实

- 时域 signed MRC 在 BLE 上全面优于或等同于谱域 B1。
- Fan-η-equal 与 B1 差距来自「仅 η vs η·ρ」——本次未跑 Fan η·ρ 变体（Plan Q5 可选消融）。

### 已废弃

- 无（本 plan 为 external baseline 验证，不废弃既有方法）。

**相对 baseline**：所有 WiFi MRC 方法跨域均差于 B1 Vote→Equal（8.45%）；最优 MRC-PCA-η-equal（10.78%）差 2.33%。

**部署建议**：不推荐将 Fan-BLE / MRC-PCA-BLE 作为默认 BPM pipeline；PCA 符号校正思路可留作 B2 波形融合参考。

---

## 6. 开放问题与下一步

| ID | 问题 | 建议 |
|----|------|------|
| Q1 | tone 间反相 | 已由 no-sign 消融支持；可进一步可视化 PC1 loading 分布 |
| Q2 | η vs η·ρ 权重 | 补 Fan η·ρ MRC 变体（Plan §8.4 Q5） |
| Q3 | cs_091339 MRC 失效机制 | 诊断该场景 modal 选择与 η 稳定性 |
| Q4 | B2 Coherent-MRC 优先级 | MRC BPM 未超越 B1，B2 波形融合可继续但 BPM 收益预期有限 |

---

## 7. 复现

```bash
python notebooks/scripts/chFusion_wifi_mrc_baselines.py --all
python notebooks/scripts/chFusion_wifi_mrc_cross_domain.py
```

| 产出 | 路径 |
|------|------|
| 数值结果 | `outputs/reports/wifi_mrc_baselines_results.npy` |
| 跨域汇总 | `outputs/reports/wifi_mrc_baselines_cross_domain.npy` |
| 图表 | `outputs/figures/wifi_mrc_baselines_*.png` |
| 本报告 | `docs/reports/wifi_mrc_baselines_report.md` |

---

## 8. Self Check

- Plan read: yes
- Baseline confirmed: yes（B0/B1 Uniform/Modal top2/B1 Vote→Equal）
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
