# B2 成果汇报制图任务

> **给**：Cursor Composer `BLE CS 执行 Agent`  
> **来源**：Claude/DeepSeek Review — B2 成果汇报需要 2 张新图  
> **数据源**：`outputs/reports/b2_coherent_mrc_all_cross_domain.npy`（含补充消融后共 13 条）  
> **日期**：2026-06-23

---

## ⚠️ 执行顺序

```
第一步 → docs/plans/b2_sign_first_level_hilbert_second_ablation.md
          补充 B2-A0-D / B2-A1-D 两个消融变体，重跑三场景 + 跨域

第二步 → 本文件（制图任务）
          基于更新后的 cross_domain.npy（含 A0-D/A1-D），生成 2 张成果图
```

**本文件应在第一步完成后执行。**

---

## 任务

为 `docs/achievements/b2_coherent_mrc_waveform_fusion_achievement_report.md` 补充 2 张图。报告中已标注 `📊 需要新图` 的位置。

### 图 1：第二级贡献分解图

**路径**：`outputs/figures/b2_coherent_mrc_two_level_contribution.png`

**数据**（直接来自 cross_domain.npy）：

```python
methods = ["b2_b_gamma", "b2_d_eq", "b2_d_two_level"]
labels  = ["B2-Bγ\n(单级, 无二级)", "B2-D-eq\n(两级, 无对齐, 等权)", "B2-D\n(两级, Hilbert对齐+ηγ加权)"]
colors  = ["darkcyan", "lightblue", "crimson"]

# Per-scenario + cross-domain bar chart
# cs_091339: 17.85, 17.85, 15.01
# cs_095806:  5.67,  5.67,  5.82
# cs_102621:  9.17,  9.17,  7.45
# cross_domain: 10.89, 10.89, 9.43
```

**要求**：
- 4 面板（3 场景 + 跨域汇总），共享 y 轴（BPM err%）
- Bγ 和 D-eq 同色系（它们数值完全相同），D 用醒目对比色
- Bγ→D 之间标注 Δ（跨域 −1.46 pp，091339 −2.84 pp，102621 −1.72 pp, 095806 +0.15 pp）
- 在 B2-D 柱上方标注跨域 9.43%
- 风格与既有 `b2_coherent_mrc_leaderboard.png` 一致（字体、dpi、配色）

### 图 2：B2 内部提升路径瀑布图

**路径**：`outputs/figures/b2_coherent_mrc_waterfall_decomposition.png`

**数据**：

```python
steps = [
    ("A0\nPCA sign",        12.33),
    ("A1\nCorr sign",       11.06),
    ("B\nHilbert η·ρ",      10.91),
    ("Bγ\n+coherence gate", 10.89),
    ("D\n+二级Hilbert对齐",  9.43),
]
deltas = [None, -1.27, -0.15, -0.02, -1.46]
```

**要求**：
- 瀑布图（waterfall / cascade），每个柱子从上一个值开始，展示增量变化
- 绿 = 改善（Δ < 0），灰 = 接近零或无变化，红 = 退化（Δ > 0，本图仅 095806 第二级有微退化但不在跨域瀑布中）
- 每步标注 Δ 值
- 在 8.45% 处画 B1 基准水平虚线
- 标注 A0→D 总提升 = −2.90 pp

---

## 实现建议

- 在 `notebooks/scripts/chFusion_b2_coherent_mrc_cross_domain.py` 末尾新增 `plot_b2_achievement_figures()` 函数
- 复用已有的 cross_domain 数据加载逻辑（`np.load(...)` + 索引）
- 不需要重新跑实验——所有数据已存在于 `outputs/reports/b2_coherent_mrc_all_cross_domain.npy`

## 产出

- `outputs/figures/b2_coherent_mrc_two_level_contribution.png`
- `outputs/figures/b2_coherent_mrc_waterfall_decomposition.png`

完成后在成果汇报 `docs/achievements/b2_coherent_mrc_waveform_fusion_achievement_report.md` 中将 `📊 需要新图` 占位符替换为实际 `![]()` 引用。

---

## 验证状态

| 字段 | 内容 |
|------|------|
| **状态** | 已完成（2026-06-23） |
| **产出** | `b2_coherent_mrc_two_level_contribution.png`、`b2_coherent_mrc_waterfall_decomposition.png` |
