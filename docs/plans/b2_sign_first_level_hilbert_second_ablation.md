# B2 补充消融：第一级符号校正 + 第二级 Hilbert 对齐

> **给**：Cursor Composer `BLE CS 执行 Agent`  
> **来源**：Claude/DeepSeek Review — B2 缺少"第一级仅符号校正 + 第二级 Hilbert 模态对齐"的组合  
> **日期**：2026-06-23  
> **优先级**：🔴 第一步（先完成本 plan，再执行 `b2_achievement_figures_task.md` 制图）

---

## 缺口分析

现有 B2 方法矩阵：

| 第一级 (tone-level) | 第二级 (modal-level) | 方法 |
|---------------------|---------------------|------|
| PCA sign | 无 (等权平均) | B2-A0 ✅ |
| Corr sign | 无 (等权平均) | B2-A1 ✅ |
| Hilbert η·ρ | 无 (等权平均) | B2-B ✅ |
| Hilbert η·ρ·γ | 无 (等权平均) | B2-Bγ ✅ |
| FFT 互谱 + B1 f₀ | 无 (等权平均) | B2-C ✅ |
| Hilbert η·ρ·γ | Hilbert 对齐 + η·γ 加权 | **B2-D** ✅ |
| Hilbert η·ρ·γ | 二级结构, 等权, 无对齐 | B2-D-eq ✅ |
| **PCA sign** | **Hilbert 对齐 + η·γ 加权** | **缺失 ❌** |
| **Corr sign** | **Hilbert 对齐 + η·γ 加权** | **缺失 ❌** |

**缺失的消融回答了关键问题**：如果第一级 tone 间只有 0/π 相位差（符号校正已足够），第二级 modal 间 Hilbert 对齐的 −1.46 pp 增益是否仍然成立？还是说第二级增益依赖第一级 Hilbert 提供的连续相位信息？

## 新增方法（2 个）

| 代号 | 描述性名称 | phase_method | use_two_level | use_modal_phase_align | weight_mode |
|------|-----------|-------------|---------------|----------------------|-------------|
| **B2-A0-D** | PCA sign (第一级) → Hilbert 模态对齐 + η·γ 加权 (第二级) | `"pca_sign"` | `True` | `True` | `"eta_rho"` |
| **B2-A1-D** | Corr sign (第一级) → Hilbert 模态对齐 + η·γ 加权 (第二级) | `"corr_sign"` | `True` | `True` | `"eta_rho"` |

- 第一级权重：η·ρ（与 B2-A0/A1 一致，不加 coherence gating——因为 coherence gating 已证实无增益）
- 第二级权重：η·γ（与 B2-D 一致）

## 实现步骤

### 1. 修改 `src/ble_analysis/coherent_mrc.py`

**① 在 `B2_ALL_SPECS` 中新增两条**（约第 58 行后）：

```python
B2_ALL_SPECS: Tuple[Tuple[str, str, str], ...] = B2_PHASE1_SPECS + (
    ("B2-B Hilbert η·ρ → equal modal", "b2_b_hilbert", "teal"),
    ("B2-Bγ Hilbert coherence-gated → equal modal", "b2_b_gamma", "darkcyan"),
    ("B2-C FFT cross-spectrum → equal modal", "b2_c_fft_cross", "purple"),
    ("B2-D Two-level Hilbert-MRC", "b2_d_two_level", "crimson"),
    ("B2-D-eq Two-level equal modal", "b2_d_eq", "indianred"),
    # 新增：
    ("B2-A0-D PCA sign → two-level Hilbert modal align", "b2_a0_d_two_level", "darkorange"),
    ("B2-A1-D Corr sign → two-level Hilbert modal align", "b2_a1_d_two_level", "orange"),
)
```

**② 在 `estimate_b2_segment()` 的 method configs dict 中新增**（约第 679 行后）：

```python
"b2_a0_d_two_level": {
    "label": "B2-A0-D PCA sign → two-level Hilbert modal",
    "phase_method": "pca_sign",
    "weight_mode": "eta_rho",
    "use_two_level": True,
    "use_modal_phase_align": True,
    "modal_weight_mode": "eta_coherence",
},
"b2_a1_d_two_level": {
    "label": "B2-A1-D Corr sign → two-level Hilbert modal",
    "phase_method": "corr_sign",
    "weight_mode": "eta_rho",
    "use_two_level": True,
    "use_modal_phase_align": True,
    "modal_weight_mode": "eta_coherence",
},
```

### 2. 运行实验

```bash
# 三场景
python notebooks/scripts/chFusion_b2_coherent_mrc.py --scenario cs_091339
python notebooks/scripts/chFusion_b2_coherent_mrc.py --scenario cs_095806
python notebooks/scripts/chFusion_b2_coherent_mrc.py --scenario cs_102621

# 跨域汇总
python notebooks/scripts/chFusion_b2_coherent_mrc_cross_domain.py
```

### 3. 更新报告

在 `docs/reports/b2_coherent_mrc_waveform_fusion_report.md` 中：

- 主结果表（§4.1）新增 B2-A0-D / B2-A1-D 两行
- 假设验证表（§4.2）补充讨论：第一级符号校正 + 第二级 Hilbert 对齐 vs 全 Hilbert 路线（B2-D）
- 如关键结论变化，同步更新 §5 结论和 §6 部署建议

### 4. 更新成果汇报

在 `docs/achievements/b2_coherent_mrc_waveform_fusion_achievement_report.md` 中更新对应数据。

---

## 预期分析

若 A1-D ≈ D（9.43%）→ 第一级 Hilbert 连续相位补偿是冗余的，符号校正 + 第二级对齐已足够，"低采样率下符号校正已够用"的结论进一步强化。

若 A1-D 明显劣于 D（如 > 10%）→ 第一级 Hilbert 提供的连续相位信息是第二级对齐的前提，"仅第一级需要连续相位"的假设被推翻——第二级也需要第一级提供精确的连续相位。

最可能的中间结果：A1-D 介于 A1（11.06%）和 D（9.43%）之间，第二级 −1.46 pp 增益在第一级为符号校正时部分保留（约 −1.0 pp），但不完全等价。

---

## 产出

- 更新 `src/ble_analysis/coherent_mrc.py`（+2 方法 spec + 2 config entry）
- 更新 `outputs/reports/b2_coherent_mrc_all_results.npy`（重跑后三场景 + 跨域均会新增两列）
- 更新 `outputs/figures/b2_coherent_mrc_leaderboard.png`（+2 方法）
- 更新 `docs/reports/b2_coherent_mrc_waveform_fusion_report.md`

---

## 验证状态

| 字段 | 内容 |
|------|------|
| **状态** | 已完成（2026-06-23） |
| **跨域结果** | A0-D 11.09%，A1-D 11.15%（均远劣于 B2-D 9.43%） |
| **结论** | **实际结果接近「A1-D 明显劣于 D」分支**：第二级 Hilbert 对齐增益依赖第一级连续相位；A1-D ≈ A1（+0.09 pp），符号校正 + 第二级对齐无法复现 B2-D |
