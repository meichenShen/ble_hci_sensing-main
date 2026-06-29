# chFusion PCA/SVD 多信道呼吸波形提取方案

## 1. 动机与背景

当前 chFusion 系列的多信道融合策略为：

- **Single**: 按能量比 η 或峰度 ρ 选**最优单信道**，其余信道丢弃
- **Uniform/q-weighted**: 所有信道加权融合，但权重基于单个信道的标量质量分数

这种方法的问题是：**每个信道的选择/加权是独立的**，没有利用信道之间的相关性结构。呼吸引起的胸腔位移会**同时影响所有信道**（幅值衰减 + 相位偏移），而电路噪声、多径干扰在不同信道上是非相关的。因此，呼吸信号在所有信道上表现为一个**共同的变化模式**。

**PCA/SVD 恰好能提取这种共同模式**：第一主成分（PC1）对应"所有信道中方差最大的共同方向"，理论上就是呼吸信号。

在 WiFi CSI 呼吸感知文献中，PCA 和 SVD 是标准的信号提取手段，用于从 30+ 子载波中去除静态环境噪声、分离呼吸主导成分。

## 2. 物理模型与变量选择

### 2.1 BLE CS 数据可用变量

| 变量名 | 含义 | 物理意义 |
|--------|------|----------|
| `amplitudes` | 总幅值 | 双向测量综合幅值响应 |
| `remote_amplitudes` | 远程幅值 | 远端设备单端幅值测量 |
| `local_amplitudes` | 本地幅值 | 本地设备单端幅值测量 |
| `phases` | 总相位（已 unwrap） | 双向测量差分相位（LO 漂移已抵消） |

### 2.2 为什么不使用本地/远程单端相位

单端相位包含本振 (LO) 相位漂移：

```
φ_local  = φ_prop + φ_LO_remote - φ_LO_local + φ_noise
φ_remote = φ_prop + φ_LO_local  - φ_LO_remote + φ_noise
```

只有功率相乘后的**总相位**（差分相位）能抵消 LO 漂移：

```
φ_total = φ_local + φ_remote = 2·φ_prop + φ_noise
```

因此只能用 `phases`（总相位）。不能直接用 local/remote 单端相位。

### 2.3 复矩阵构造：总幅值 + 总相位

**推荐方案**：`z = A_total · e^(j · φ_total)`

理由：
1. 总幅值和总相位都来自双向综合测量，处于同一参考系
2. 复数值完整保留了 CSI 的幅相信息，与 WiFi CSI 的复信道响应 `H(f)` 同构
3. 单独对幅值或相位做 PCA 只捕捉单一模态的呼吸信息

**不推荐**：`remote_amplitude · e^(j · φ_total)` 或 `local_amplitude · e^(j · φ_total)`

理由：remote/local 幅值是单端测量（包含各自的 LO 幅值响应），而 total phase 是差分测量（LO 已抵消）。将单端量（含 LO 漂移贡献）和差分量强行组合成复数在物理上不一致——它们不在同一个参考系中。

但 `remote_amplitudes` 和 `local_amplitudes` **单独作为实矩阵**做 PCA/SVD 是完全合理的（它们各自的多信道间仍然共享呼吸引起的相关变化）。

### 2.4 优化策略：堆叠所有有用信号

为提高 PCA/SVD 效果，可将多种信号的信道数据**横向堆叠**成更大的矩阵。

例如将 `amplitudes` 的 72 通道 + `remote_amplitudes` 的 72 通道 + `local_amplitudes` 的 72 通道 = 216 列的大矩阵。呼吸信号在所有 216 维上都有相关投影，PC1 的信噪比更高。

## 3. 架构设计

### 3.1 文件结构

```
src/ble_analysis/pca_svd.py          ← 新建：核心 PCA/SVD 提取算法（可复用模块）
notebooks/scripts/chFusion_pca_svd.py ← 新建：分段式实验脚本
docs/chFusion_pca_svd_plan.md        ← 本文档
```

### 3.2 模块职责划分

**`src/ble_analysis/pca_svd.py`（可复用模块）**

| 内容 | 说明 |
|------|------|
| `PcaSvdConfig` | dataclass 配置（方法、标准化策略、最小信道数、方差阈值等） |
| `PcaSvdMethod` | Literal 类型：`pca` / `svd_real` / `svd_complex` |
| `NormalizeMethod` | Literal 类型：`none` / `zscore` / `minmax` |
| `extract_breath_waveform_pca()` | 实矩阵 PCA，返回 PC1 时间序列 |
| `extract_breath_waveform_svd()` | 实矩阵 SVD，返回第一左奇异向量 |
| `extract_breath_waveform_complex_svd()` | 复矩阵 SVD，返回第一左奇异向量的幅值 |
| `_normalize_matrix()` | 标准化函数（zscore / minmax） |
| `align_waveform_sign()` | 跨窗口符号一致性对齐 |
| `pca_explained_variance()` | 返回各主成分的方差占比 |
| `build_multivariable_data_matrix()` | 将多种变量的多信道数据构造成 M×N 矩阵 |

**`notebooks/scripts/chFusion_pca_svd.py`（实验脚本）**

复用现有 pipeline 的分段式 py 脚本风格：

| 步骤 | 内容 |
|------|------|
| 0 | Bootstrap + 参数配置 |
| 1 | 运行多信道滤波（复用 `run_multichannel_segment_filtering`） |
| 2 | PCA/SVD 呼吸波形提取 + BPM 估计（调用 `pca_svd` 模块） |
| 3 | 与现有方法（Single/Uniform/q-weighted）的误差对比表 |
| 4 | PCA 解释方差分析（PC1 占比分布） |
| 5 | 波形对比图（best/worst window 的 PCA/FFT 并排图） |
| 6 | 跨场景一致性验证 |
| 7 | 保存结果 + 汇总图表 |

## 4. 核心算法

### 4.1 实矩阵 PCA 提取

```
输入: X ∈ R^{M×N}，M 帧，N 信道（已带通滤波）
步骤:
  1. 检查有效信道数 >= min_channels
  2. 按列 Z-score 标准化: Z_j = (X_j - μ_j) / σ_j
  3. 协方差矩阵: C = Z^T Z / (M-1)  ∈ R^{N×N}
  4. 特征分解: C = V diag(λ) V^T, λ 降序排列
  5. PC1 = Z · v_1  ∈ R^M
  6. 检查 λ_1 / Σλ >= min_variance_ratio（否则警告）
  7. 符号一致性（与前一窗口的 PC1 做相关，若负则翻转）
输出: PC1 时间序列 (M,)
```

### 4.2 实矩阵 SVD 提取

```
输入: X ∈ R^{M×N}
步骤:
  1. 按列 Z-score 标准化
  2. 紧凑 SVD: Z = U diag(s) V^T
  3. u_1 = U[:, 0] ∈ R^M（第一左奇异向量）
  4. 检查 s_1² / Σs_i² >= min_variance_ratio
  5. 符号一致性
输出: u_1 时间序列 (M,)
```

注：PCA 和 SVD 在数学上等价。PCA 走特征分解（N×N 协方差矩阵），SVD 直接对 M×N 数据矩阵分解。当 N << M 时（72 信道 << 数百帧），PCA 的特征分解更高效。

### 4.3 复矩阵 SVD 提取

```
输入: Z ∈ C^{M×N}, Z_{i,j} = A_{i,j} · e^{j·φ_{i,j}}
步骤:
  1. 每列中心化: Z̃ = Z - mean(Z, axis=0)
  2. 构造实矩阵: R = [Re(Z̃), -Im(Z̃); Im(Z̃), Re(Z̃)]
     或使用 np.linalg.svd 直接分解复矩阵
  3. SVD: Z̃ = U diag(s) V^H
  4. u_1 = U[:, 0] ∈ C^M
  5. waveform = |u_1| 或 Re(u_1)（取幅值更稳定）
  6. 符号一致性（对实值波形）
输出: 呼吸波形 (M,)
```

Python ≥ 3.9 的 `numpy.linalg.svd` 已原生支持复数矩阵，无需手动展开为实矩阵。

### 4.4 符号一致性算法

```
对齐窗口 t 的符号:
  if t == 0: cur 不变（或与参考信道做相关决定初始符号）
  else:
    corr = dot(prev_waveform, cur_waveform)
    if corr < 0: cur_waveform *= -1

参考信道选择: 取中间信道（如 ch=37）的带通波形作为初始符号参考
```

### 4.5 滑窗 BPM 估计整合

复用 `segments.py` 中的 `_sliding_window_indices` 逻辑：

```
对每段呼吸数据:
  all_windows_bpm = []
  for each sliding window:
    1. 取出 M×N 数据矩阵（M 帧，N 个有效信道）
    2. 调用 pca_svd.extract_breath_waveform_xxx(data_matrix)
    3. 对提取的 1D 波形做 FFT
    4. 在呼吸频带 [breath_freq_low, breath_freq_high] 找峰值频率
    5. BPM = freq × 60
    all_windows_bpm.append(bpm)
  return all_windows_bpm
```

## 5. 实验策略

### 5.1 受试方法

共比较以下方法（在 leaderboard 中排列）：

| 编号 | 方法 | 输入矩阵 |
|------|------|----------|
| 1 | PCA Remote Amp | `remote_amplitudes` 72 道实 PCA |
| 2 | PCA Local Amp | `local_amplitudes` 72 道实 PCA |
| 3 | PCA Total Amp | `amplitudes` 72 道实 PCA |
| 4 | SVD Remote Amp | `remote_amplitudes` 72 道实 SVD |
| 5 | SVD Local Amp | `local_amplitudes` 72 道实 SVD |
| 6 | SVD Total Amp | `amplitudes` 72 道实 SVD |
| 7 | PCA Phase | `phases` 72 道实 PCA |
| 8 | SVD Phase | `phases` 72 道实 SVD |
| 9 | SVD Complex Total | `amplitudes`·e^(j·`phases`) 72 道复 SVD |
| 10 | SVD Complex Remote | `remote_amplitudes`·e^(j·`phases`) |
| 11 | SVD Complex Local | `local_amplitudes`·e^(j·`phases`) |
| 12 | PCA Stacked | 三种幅值堆叠 (remote+local+total) 216 道实 PCA |
| 13 | Single (baseline) | 现有能量比最优单信道 (remote amp) |
| 14 | Uniform (baseline) | 现有等权融合 (remote amp) |
| 15 | q_energy_peak (baseline) | 现有质量加权融合 (remote amp) |

注：baseline 统一使用 `remote_amplitudes`（当前实验中最优的单变量），benchmark 脚本中额外包含全部 4 种变量的 baseline。

### 5.2 关键诊断指标

- **PC1 方差占比**: λ₁ / Σλ — 衡量呼吸信号的主导程度。理想值 > 0.5
- **跨窗口 PC1 相关性**: 相邻窗口 PC1 的相关系数 — 衡量提取的一致性
- **跨场景稳定性**: 不同金属板录制下的 mean_rel_err_pct 标准差

### 5.3 预期效果

- PCA/SVD 应优于 Single（因为它利用了所有信道的信息）
- PCA/SVD 应至少与 Uniform 持平或更好（PC1 是数据驱动的最优组合）
- ~~复 SVD 可能优于单独的幅值或相位 PCA~~ → **实验否定**：三种幅值+总相位复 SVD 均倍频失效（§8.5）
- Stacked PCA 可能最优（融合了多种信号的互补信息）

## 6. 文件生成计划

### `src/ble_analysis/pca_svd.py`

~200 行，包含：
- `PcaSvdConfig` dataclass
- `__all__` 导出列表
- `extract_breath_waveform_pca()`, `extract_breath_waveform_svd()`, `extract_breath_waveform_complex_svd()`
- `align_waveform_sign()`, `_normalize_matrix()`
- `pca_explained_variance()`, `build_multivariable_data_matrix()`
- 完整的 numpy-style docstring

### `notebooks/scripts/chFusion_pca_svd.py`

~300 行，分段式结构（`# %% [markdown]` + `# %%`），包含：
- 模块 docstring
- Step 0: 环境引导
- Step 0b: 参数配置（含 PcaSvdConfig）
- Step 1: 多信道滤波
- Step 2: PCA/SVD BPM 提取 + 滑窗循环
- Step 3: 误差对比表
- Step 4: 解释方差分析
- Step 5: 波形对比图
- Step 6: 跨场景验证
- Step 7: 保存结果

## 7. 风险与注意事项

| 风险 | 状态 | 缓解措施 |
|------|------|----------|
| 信道数少导致 PCA 不稳定 | ✅ 已排除 — BLE CS 有 72 信道 | — |
| PC1 不对应呼吸 | ⚠️ 待验证 | 检查 PC1 频谱是否在呼吸频带有峰值；若方差比 < 30% 则警告 |
| 符号翻转 | ⚠️ 待处理 | 跨窗口符号对齐 + 初始符号由中位信道确定 |
| 复 SVD 实现复杂度 | ✅ 清晰 | numpy.svd 原生支持复数 |
| 标准化策略影响结果 | ⚠️ 需实验 | 三种策略均实现，实验后选择最优 |
| 与现有 pipeline 的集成 | ✅ 清晰 | 复用 `run_multichannel_segment_filtering` 的输出 |
| 排行榜单位错误（未 ×100） | ✅ 已修复 | 与 `_overall_rel_error` 对齐，热力图同步 ×100 |

## 8. 验证结果（cs_102621，2026-06）

### 8.1 评估口径

与 Plan 2 完全一致：

1. 四变量 × 72 信道带通滤波（phase 先 unwrap）
2. 20 s 窗 / 1 s 步滑窗
3. 每窗估计 BPM，段内相对误差 `|est−GT|/GT` 取均值
4. 对 breath 段再取平均，**单位为 %**（`bpm_rel_err` 存比例，展示时 ×100）

脚本：`notebooks/scripts/chFusion_pca_svd.py`  
输出：`outputs/figures/pca_svd_102621_*.png`，`outputs/reports/chfusion_pca_svd_102621.npy`

### 8.2 单场景排行榜（7 个 breath 段）

| 排名 | 方法 | mean err% | 类别 |
|------|------|-----------|------|
| 1 | Modal η-weight | **4.60** | Plan2 模态 |
| 2 | Modal equal | 4.64 | Plan2 模态 |
| 3 | Modal top2 equal | 4.69 | Plan2 模态 |
| 6 | Uniform Total amplitude | 5.91 | Plan2 基线 |
| 8 | q_energy_peak (remote) | 6.61 | chFusion 基线 |
| 9 | **PCA Total Amp** | **6.62** | PCA/SVD |
| 10 | SVD Total Amp | 6.62 | PCA/SVD |
| 11 | PCA Stacked | 6.75 | PCA/SVD |
| 17 | PCA Remote Amp | 7.17 | PCA/SVD |
| 26 | SVD Complex Remote | 48.02 | PCA/SVD |
| 27 | SVD Complex Total | 52.30 | PCA/SVD |
| 28 | SVD Complex Local | 52.72 | PCA/SVD |

**要点：**

- 修复单位 bug 前，上述误差会显示为真实值的 **1/100**（例如 7.17% 误显示为 0.07%）。
- 实矩阵 **PCA ≡ SVD**（数值一致，符合理论）。
- PC1 方差占比约 **0.32–0.72**，未达文档预期的 0.5+，但提取仍可用。
- **SVD Complex（总幅值 + 总相位）严重失效**（mean 52%），段 1a/1b 约 108%——疑为 `|u₁|` 取幅值引入倍频；已保留该方案并追加 remote/local 幅值 + 总相位对照实验（见 §8.4）。
- **当前单场景最优仍为 Plan2 Modal 融合**，PCA Total Amp 略优于 Uniform remote，未超过 Modal。

### 8.3 脚本改动摘要

| 改动 | 说明 |
|------|------|
| 复用 `_seg_bpm_stats` / `_overall_rel_error` | 与 chfusion、Plan2 同口径 |
| 接入 `run_plan2_validation` | 统一排行榜含 13 种 Plan2 方法 |
| 修复 `mean_rel_err_pct` | 段级比例 ×100 再展示 |
| 段元数据 | `bpm_gt` / `segment_type` 从滤波 metadata 读取 |

### 8.4 复 SVD 幅值来源对照（待跨场景汇总）

除保留 **总幅值 + 总相位** 外，脚本增加：

| 方法 | 复矩阵构造 |
|------|------------|
| SVD Complex Total | `amplitudes · e^(j·phases)` |
| SVD Complex Remote | `remote_amplitudes · e^(j·phases)` |
| SVD Complex Local | `local_amplitudes · e^(j·phases)` |

> 文档 §2.3 曾标注 remote/local + 总相位「物理参考系不一致」；此处作为 **对照实验** 检验是否比总幅值方案更稳。

**102621 单场景复 SVD 对照：**

| 方法 | mean err% | 相对 Total |
|------|-----------|------------|
| SVD Complex Remote | 48.02 | 略优（仍不可用） |
| SVD Complex Total | 52.30 | 基线 |
| SVD Complex Local | 52.72 | 略差 |

Remote 幅值 + 总相位在 102621 上略好于 Total，但 **PC1 方差占比更高 ≠ BPM 更准**（三种复 SVD 均 ~50%+）。倍频问题与幅值来源关系不大，更可能来自 `|u₁|` 取模。

### 8.5 跨场景汇总（三场景 η 选路）

| 方法 | 091339 | 095806 | 102621 | 跨域 mean | ±std |
|------|--------|--------|--------|-----------|------|
| **Modal top2 equal** | 13.04 | 10.61 | **4.69** | **9.45** | 4.29 |
| **Modal η-weight** | 13.25 | 10.50 | **4.60** | **9.45** | 4.42 |
| Single Remote | 10.91 | 12.16 | 8.29 | 10.45 | **1.97** |
| Uniform Remote | 17.09 | 9.15 | 6.82 | 11.02 | 5.39 |
| PCA Total Amp | 25.97 | 6.78 | 6.62 | 13.12 | 11.13 |
| SVD Complex Remote | 47.53 | 73.69 | 48.02 | 56.42 | 14.97 |
| SVD Complex Total | 49.94 | 73.05 | 52.30 | 58.43 | 12.72 |
| SVD Complex Local | 50.49 | 71.78 | 52.72 | 58.33 | 11.70 |

图：`outputs/figures/pca_svd_cross_domain_aggregate_bars.png`  
报告：`outputs/reports/chfusion_pca_svd_cross_domain.npy`

**跨场景结论：**

1. **综合最优仍为 Plan2 Modal**（top2 equal / η-weight 跨域 mean **9.45%**），与 Plan2 跨域验证结论一致。
2. **PCA Total Amp** 在 102621/095806 尚可（~6–7%），但 **091339 上 25.97%** 拉垮跨域均值（13.12%），稳定性不如 Modal。
3. **三种复 SVD 均跨场景失效**（mean 56–58%）；Remote 略优于 Total/Local，不足以实用。
4. Single Remote 跨域 mean 10.45%、**std 最小（1.97%）**——方差小但均值略逊于 Modal。

### 8.6 PCA v2：高通 + 信道 η 加权 + PCA 模态融合（2026-06）

**设计原则：** 非必要不用带通；统一用 ``highpass_filtered`` 构造 PCA 矩阵；呼吸频带仅在 FFT 估 BPM / 算 η 时使用。

| 层级 | 选项 |
|------|------|
| 信道维（PCA 内） | ``uniform``（z-score）/ ``energy_ratio``（列 √η 加权） |
| 模态维（谱融合） | ``equal`` / ``energy_ratio``（变量 mean η 加权） |
| 复数 PCA | ``amp·e^(jφ)`` → Hermitian 协方差 PC1 → **Re(PC1)**（非 \|PC1\|） |

**cs_102621 单场景 Top（节选）：**

| 方法 | mean err% |
|------|-----------|
| **PCA-Cmplx Total ch-η** | **3.81** |
| Modal η-weight | 4.60 |
| PCA-Modal3 η/ch-η | 5.72 |
| PCA-HP Remote ch-η | 7.06 |

**三场景跨域（核心方法）：**

| 方法 | 091339 | 095806 | 102621 | mean |
|------|--------|--------|--------|------|
| Modal top2 equal | 13.04 | 10.61 | 4.69 | **9.45** |
| Modal η-weight | 13.25 | 10.50 | 4.60 | **9.45** |
| PCA-Modal3 η/ch-η | 19.54 | 7.51 | 5.72 | 10.92 |
| PCA-Cmplx Total ch-η | 28.43 | 11.73 | 3.81 | 14.66 |

**结论：**

- **PCA + 模态谱融合**（``PCA-Modal3 η/ch-η``）明显优于单变量带通 PCA（102621 5.72% vs 6.62%），说明「PCA 作提取、Plan2 作融合」方向正确。
- **复 PCA（Re(PC1) + 高通 + ch-η）** 在 102621 单场景最优（3.81%），但 **091339 上 28.43%**，跨域不稳定；优于旧复 SVD（\|u₁\| 倍频）但仍不足以替代 Modal。
- **幅值+相位两模态 PCA**（remote + phase）略逊于三模态 PCA-Modal3。
- **跨场景部署默认仍为 Modal**；PCA 系列可作为单场景调参/对照，需更多场景验证稳定性。

### 8.8 双幅值整合 + top2 模态（2026-06）

**已实现（代码）：** 方案 2/3/4；`ModalWeightMode` 扩展 **`top2_equal`**（`PCA-Modal3 top2/ch-η`、`PCA-Cmplx-Modal rem+loc top2`）；§9 脚本对 **cs_091339** 输出 η-blend / Dual-Amp 窗级倍频诊断。

**三场景跨域（2026-06 §8 重跑）：**

| 方法 | 091339 | 095806 | 102621 | mean |
|------|--------|--------|--------|------|
| **Modal top2 / η-weight** | 13.04–13.25 | 10.50–10.61 | 4.60–4.69 | **9.45** |
| PCA-Modal3 η/ch-η | 19.54 | 7.51 | 5.72 | 10.92 |
| **PCA-Modal3 top16/ch-η** | 19.10 | 8.84 | 4.61 | **10.85** |
| PCA-Modal3 top2/ch-η | 18.97 | 8.12 | 6.31 | 11.14 |
| PCA-Cmplx-Modal rem+loc η | 21.65 | 9.44 | 4.75 | **11.95** |
| PCA-Cmplx-Modal rem+loc top2 | 22.59 | 9.45 | 4.79 | 12.27 |
| PCA-Cmplx η-blend ch-η | 27.96 | 9.91 | 4.71 | 14.20 |
| PCA-Cmplx Total ch-η | 28.43 | 11.73 | 3.81 | 14.66 |
| PCA-Cmplx Total top8/ch-η | 28.44 | 10.22 | 3.35 | 14.00 |
| PCA-HP Remote top8/ch-η | 17.54 | 9.88 | 7.66 | 11.69 |
| PCA-HP Remote ch-η (72ch) | 16.79 | 7.64 | 7.06 | 10.50 |

**结论：** top2 模态对 **PCA 系列未带来超越 Plan2 Modal 的收益**（PCA-Modal top2 mean 11.14% > Modal 9.45%）；Top-K 信道在 Remote 单变量上 **top8 差于 72 道**（11.69% vs 10.50%），在 Modal3 上 **top16 略优于全 72 道**（10.85% vs 10.92%）但仍不及 Modal。

**091339 失败诊断（§9–§10）：** η-blend / Dual-Amp 在差段窗级 **double/half 谐波占比高**；§10 已输出最差段 PC1 呼吸带谱 vs GT 对照图 `pca_svd_091339_worst_seg_pc1_spectrum.png`。

---

## 9. 方法流程对照表（详细）

本节列出 `chFusion_pca_svd.py` 排行榜中**各类方法**从原始帧到 BPM 的完整差异。  
符号：η = 呼吸带能量 / 全频段能量（0.1–0.35 Hz / 0.05–0.8 Hz）；滑窗统一 **20 s 窗、1 s 步**。

### 9.0 公共前置（所有方法共享）

| 步骤 | 内容 |
|------|------|
| 数据源 | BLE CS 72 tone，`sampleData/CS_frames_*.jsonl` |
| 分段 | `config/scenarios/*.json`：7 breath + 2 apnea，每段有 `bpm_gt` |
| 单信道滤波链 | **median → highpass (0.05 Hz) → bandpass (0.1–0.35 Hz)**；`phases` 先 unwrap 再滤波 |
| 存储键 | 每信道每变量存 `original` / `median_filtered` / `highpass_filtered` / `bandpass_filtered` |
| 评估 | 窗级 BPM 相对误差 → 段内均值 → 各 breath 段再平均（%） |

**关键分歧点**（后文每方法会标明）：

1. **用哪级滤波信号**：`bandpass_filtered`（v1 PCA/SVD、Plan2）还是 `highpass_filtered`（v2 PCA）
2. **多信道怎么用**：选 1 道 / 等权谱融合 / q 加权 / **PCA 提 PC1**
3. **信道内加权**：z-score 等权（uniform）还是 **√η 列加权**（energy_ratio）
4. **多变量怎么用**：单变量 / 模态谱融合 / 堆叠矩阵
5. **BPM 怎么取**：波形 FFT 峰频 vs **归一化谱融合后峰频**

---

### 9.1 Plan 2 基线族（`run_plan2_validation`）

#### A. Single / Uniform（每变量 4 种）

| 项目 | Single X | Uniform X |
|------|----------|-----------|
| 变量 | `amplitudes` / `remote_amplitudes` / `local_amplitudes` / `phases` | 同左 |
| 滤波用于特征 | **带通** `bandpass_filtered` 做 FFT 谱；η 在 **高通** `highpass_filtered` 上算 | 同左 |
| 多信道 | **每窗选 η 最大 1 道**（`energy_ratio` 选路） | **72 道带通谱** |
| 信道融合 | 无（单道） | **等权平均** 归一化谱 |
| BPM | 单道带通 FFT 峰频，或融合谱 argmax × 60 | 同左 |

#### B. Modal 融合（5 种，Plan2 核心）

| 项目 | 说明 |
|------|------|
| 参与模态 | **phase + remote_amp + local_amp**（不含 total amp） |
| 滤波 | 每模态用 **best 单信道** 的 **带通** 波形做 FFT 谱 |
| 多信道（模态内） | 每变量 **独立** 选 η 最大信道（与 Single 相同选路） |
| 模态融合策略 | 见下表 |

| 方法名 | 模态权重 |
|--------|----------|
| Modal equal | 1/3 等权 |
| Modal η-weight | 各模态 best 信道的 η 归一化加权 |
| Modal 0.5/0.25/0.25 | 固定 phase 0.5，remote/local 各 0.25 |
| Modal top2 equal | 每窗按 η 排序取 **前 2 变量**，等权 0.5 |
| Modal top2 ρ-weight | top2 按谱峰 ρ 加权 |

BPM：加权融合归一化谱 → 呼吸带 parabolic 峰频 × 60。

---

### 9.2 chFusion 精简基线（脚本 §2，仅 remote）

| 方法 | 变量 | 滤波 | 多信道 | BPM |
|------|------|------|--------|-----|
| Single (remote amp) | `remote_amplitudes` | 带通 | η 最大 1 道 | 波形 FFT 峰频 |
| Uniform (remote amp) | 同左 | 带通 | 72 道谱等权融 | 融合谱峰频 |
| q_energy_peak (remote) | 同左 | 带通 | 72 道 **q_energy_peak** 加权谱 | 融合谱峰频 |

---

### 9.3 PCA/SVD v1（带通，§3b `PCA_SVD_EXPERIMENTS`）

**共同流程：**

```
带通 M×N 矩阵 → 列 z-score → (可选) PCA/SVD → PC1/u₁ 波形
→ 符号对齐 → 波形 Hanning FFT → 呼吸带峰频 → BPM
```

| 方法组 | 变量 / 矩阵 | 分解 | 信道内加权 | 备注 |
|--------|-------------|------|------------|------|
| PCA/SVD Remote/Local/Total Amp | 单变量 72 列 | PCA 或 SVD（实，**数学等价**） | z-score 等权 | 输入 `bandpass_filtered` |
| PCA/SVD Phase | `phases` 72 列 | 同左 | z-score 等权 | 同左 |
| SVD Complex ×3 | `amp·e^(jφ)` 72 列复矩阵 | 复 SVD，波形 = **\|u₁\|** | 列中心化，无 z-score | **已证实倍频失效，勿部署** |
| PCA Stacked | remote+local+total **216 列** 实矩阵 | PCA | z-score 等权 | 单窗内跨变量堆叠 |

**与 Plan2 差异：** 用**全部信道**线性组合，不做 per-channel η 筛选；BPM 用**波形 FFT** 而非谱融合。

---

### 9.4 PCA v2（高通，§3c）

**设计原则：** 矩阵构造用 `highpass_filtered`；呼吸带 0.1–0.35 Hz 仅用于 η 与 BPM 谱峰搜索。

#### 9.4.1 单变量 PCA-HP（6 种）

| 方法名 | 变量 | 信道内加权 | 流程 |
|--------|------|------------|------|
| PCA-HP Remote/Phase/Total **ch-uniform** | 各 1 变量 × 72 列 | z-score 等权 | 高通矩阵 → PCA → 波形 FFT BPM |
| PCA-HP Remote/Phase/Total **ch-η** | 同左 | 先 z-score，再列 **√η** 缩放后 PCA | η 在同窗高通切片上 per-channel 计算 |

#### 9.4.2 PCA 模态融合（4 种，`run_pca_modal_fusion`）

**模态内（替代 Plan2 的「选 best 信道」）：**

```
每变量: 高通 72 列 → (uniform 或 ch-η) PCA → PC1 波形 → 符号对齐
      → Hanning FFT → 呼吸带归一化谱 P̄_var(f)
```

| 方法名 | 参与模态 | 信道加权 | 模态融合 |
|--------|----------|----------|----------|
| PCA-Modal3 eq/ch-uni | phase + remote + local | uniform | **等权 1/3** |
| PCA-Modal3 η/ch-η | 同左 | **ch-η** | 各模态 **mean(信道 η)** 加权 |
| PCA-Modal amp+pha eq | **remote + phase**（2 模态） | uniform | 等权 1/2 |
| PCA-Modal amp+pha η | 同左 | ch-η | mean η 加权 |
| **PCA-Modal3 top2/ch-η** | phase + remote + local | ch-η | 每窗按 mean η **取 top2 模态等权**（对齐 Plan2 top2） |
| **PCA-Modal amp+pha top2** | remote + phase | ch-η | top2 equal（两模态时等同全参与） |

BPM：模态谱加权求和 → 呼吸带 argmax（parabolic）× 60。  
**与 Plan2 Modal 的唯一结构差异：** 模态内是 **PCA(72 道)** 而非 **Single best(1 道)**。

#### 9.4.4 双幅值整合复 PCA（方案 2/3/4，不 oracle 选 remote/local）

| 方法名 | 方案 | 矩阵构造 | 信道加权 | 模态/输出 |
|--------|------|----------|----------|-----------|
| PCA-Cmplx Dual-Amp | **2** | 每 tone：`A_rem·e^jφ` 与 `A_loc·e^jφ` **并列** → 144 列 | uniform / ch-η（按列对应幅值 η） | 单矩阵复 PCA → 谱峰 BPM |
| PCA-Cmplx η-blend | **3** | 每 tone：`Ã=(η_r A_r+η_l A_l)/(η_r+η_l)`，再 `Ã·e^jφ` → 72 列 | uniform / ch-η（混合后列 √(η_r+η_l)/2） | 单矩阵复 PCA |
| PCA-Cmplx-Modal rem+loc | **4** | remote、local **各** 72 列 `A·e^jφ` → **两次**独立复 PCA | uniform / ch-η | **模态** equal / η / **top2 equal** 谱融合 |

**102621 单场景（节选）：**

| 方法 | mean err% |
|------|-----------|
| PCA-Cmplx Total ch-η | **3.81** |
| Modal η-weight | 4.60 |
| **PCA-Cmplx η-blend ch-η** | **4.71** |
| **PCA-Cmplx-Modal rem+loc η** | **4.75** |
| PCA-Cmplx Dual-Amp ch-η | 4.80 |

**三场景跨域：**

| 方法 | mean |
|------|------|
| Modal η-weight | **9.45%** |
| **PCA-Cmplx-Modal rem+loc η** | **11.95%** |
| PCA-Cmplx η-blend ch-η | 14.20% |
| PCA-Cmplx Dual-Amp ch-η | 14.68% |

η-blend / 双复堆叠在 **102621 接近 Modal**，但 **091339 仍 22–29%**；**方案4 模态融合**跨域最优（11.95%），是不 oracle 选端时的当前最佳整合路径。

**停测说明（2026-06）：**

- **PCA-Cmplx Remote·e^jφ** 已移出默认实验表（物理不一致 + 跨域无优势）。
- **144 列 Dual-Amp** 保留脚本内对照，**不作为部署候选**；跨域 mean ~14.7%，091339 诊断见 §8.8。

#### 9.4.3 复数 PCA（2 种，`run_pca_complex_fusion`）

| 方法名 | 复矩阵列 | 信道加权 | 波形 | BPM |
|--------|----------|----------|------|-----|
| PCA-Cmplx Total **ch-uni** | `amplitudes·e^(jφ)` | uniform | **Re(PC1)**，非 \|PC1\| | 谱融合峰频 |
| PCA-Cmplx Total **ch-η** | 同左 | ch-η | Re(PC1) | 同左 |

流程：每窗 72 列复矩阵 → 列中心化 → (可选 √η) → **Hermitian 协方差** 第一特征向量 → 时间序列取实部 → 符号对齐 → 归一化谱 → BPM。

**与 SVD Complex 差异：** 分解用 PCA/Hermitian；输出 **Re(PC1)** 而非 **\|u₁\|**，避免倍频。

---

### 9.5 一表总览（排行榜方法族）

| 族 | 代表方法 | 信号 | 信道策略 | 变量/模态 | BPM 路径 | 跨域 mean（三场景） |
|----|----------|------|----------|-----------|----------|---------------------|
| Plan2 Modal | η-weight / top2 | 带通 | 每模态 **1 best** | 3 模态谱融合 | 谱 argmax | **9.45%** |
| Plan2 Single | Remote amp | 带通 | 1 best | 单变量 | 波形/谱 | 10.45% |
| PCA-Modal v2 | Modal3 η/ch-η | **高通** | **PCA 72** + ch-η | 3 模态谱融合 | 谱 argmax | 10.92% |
| PCA-Cmplx v2 | Total ch-η | 高通 | 复 PCA 72 + ch-η | 幅相联合单矩阵 | 谱 argmax | 14.66%（不稳） |
| PCA v1 带通 | Total Amp | 带通 | PCA 72 等权 | 单变量 | 波形 FFT | 13.12% |
| SVD Complex | Total | 带通 | 复 SVD \|u₁\| | 幅相联合 | 波形 FFT | **~58%（废弃）** |
| 实 SVD ≡ PCA | Remote Amp | 带通 | 同 PCA | 单变量 | 波形 FFT | 与 PCA 相同 |

---

## 10. 测试取舍与下一步

### 10.1 建议 **不再投入** 的实验（已有充分负/冗余结论）

| 类别 | 原因 |
|------|------|
| **SVD Complex**（Total/Remote/Local，\|u₁\|） | 三场景 mean 56–58%，倍频；与复 PCA 相比无优势 |
| **实矩阵 SVD** 独立排行榜 | 与 PCA 数值完全一致，保留 PCA 即可 |
| **PCA v1 带通单变量** 全矩阵 | 被 PCA-HP + PCA-Modal 替代；带通未比高通+谱融合更好 |
| **PCA Stacked 216 列** | 未超过 PCA Total / PCA-Modal3，复杂度高收益低 |
| **SVD Complex Remote vs Local** 细调 | 差异 <5% err，均在失效区 |
| **PCA-HP Phase ch-η** 单变量深挖 | 102621 10.8%，远逊于 remote / modal 路线 |
| **PCA-Cmplx Remote·e^jφ** | 已移出默认 suite；local+总相位物理不一致 |
| **144 列 Dual-Amp 部署路线** | 跨域 ~14.7%，091339 倍频/半频窗占比高；仅作对照 |

### 10.2 **已执行**（2026-06 本轮）

| 项 | 状态 |
|----|------|
| 方案 2/3/4 + top2 模态 | ✅ §8 三场景重跑完成（见 §8.8 表） |
| **Top-K 信道 PCA**（K=8/16） | ✅ `select_top_k_channels` + 5 组实验；Modal3 top16 mean **10.85%** |
| **091339 倍频 + 谱图诊断** | ✅ `chFusion_pca_svd_p1_diag.py` → harmonic_diag.npy + worst_seg 谱图 |
| 跨场景快捷重跑 | ✅ `chFusion_pca_svd_cross_domain.py` |

### 10.3 建议 **重点继续** 的实验

| 优先级 | 方向 | 具体内容 |
|--------|------|----------|
| **P1** | **Top-K 细调** | Modal3 试 K=4/12/24；复 PCA Total top16；看能否稳定 <10.5% |
| **P1** | **共识门控** | PCA-Modal 窗级与 Plan2 Modal 谱峰一致性门控 |
| **P2** | **更多场景** | 人体/非金属板验证 Modal vs PCA-Modal3 top16 |
| **停测** | top2 模态 PCA 部署 | PCA-Modal/Cmplx-Modal top2 均未优于 Plan2 Modal（§8.8） |
| **P2** | **Total ch-η 单场景** | 102621 3.35–3.81% 诱人，091339 28% 风险不变 |

### 10.4 部署参考（当前证据）

| 场景 | 推荐 |
|------|------|
| **跨场景生产默认** | Plan2 **Modal top2 equal** 或 **Modal η-weight**（跨域 9.45%） |
| **单场景调优上限** | 可试 **PCA-Cmplx Total ch-η**（102621 3.81%），需接受 091339 风险 |
| **研究对照基线** | Single Remote（std 最小 1.97%） |
| **明确避免** | SVD Complex \|u₁\|、带通单变量 PCA 作为最终方案 |

### 10.5 脚本与模块索引

| 层级 | 路径 | 职责 |
|------|------|------|
| **算法核心** | `src/ble_analysis/pca_svd.py` | PCA/SVD/复 PCA、Top-K、`diagnose_complex_integration_harmonics` |
| **流水线** | `src/ble_analysis/pca_svd_pipeline.py` | 实验表、单场景/跨场景 pipeline、排行榜、P1 诊断 |
| **Plan2** | `src/ble_analysis/chfusion.py` | Modal/Single/Uniform 基线 |
| **主 notebook** | `notebooks/scripts/chFusion_pca_svd.py` | 单场景图表 + 调用 pipeline |
| **跨场景 CLI** | `notebooks/scripts/chFusion_pca_svd_cross_domain.py` | 仅 §8 三场景重跑 |
| **诊断 CLI** | `notebooks/scripts/chFusion_pca_svd_p1_diag.py` | 091339 倍频 + 最差段谱图 |
| **报告** | `outputs/reports/chfusion_pca_svd_*.npy` | 单场景 / 跨域 / harmonic_diag |

---

## 11. 探索结论与保留问题（2026-06 收官）

### 11.1 已验证结论

| 主题 | 结论 |
|------|------|
| **跨场景部署** | Plan2 **Modal top2 / η-weight** 仍为最优（三域 mean **9.45%**） |
| **PCA 能否替代 Single-best** | **不能稳定替代**。091339 上 Single Remote **10.91%**，PCA-Modal3 η **19.54%**；瓶颈在**模态内提取**（72 道 PCA vs 1 道 max-η），非 top2 模态筛选 |
| **top2 对 PCA 模态** | 有小幅帮助（091339：top2 **18.97%** vs 全模态 η **19.54%**），但远逊于 Plan2 Modal top2（**13.04%**） |
| **Top-K 信道** | Modal3 **top16** 为 PCA 系列最优（跨域 **10.85%**）；Remote top8 **差于** 72 道（11.69% vs 10.50%） |
| **复 PCA 整合** | 不 oracle 选端时 **方案4 模态融合**最优（跨域 **11.95%**）；η-blend 单场景可达 4.71% 但 091339 不稳 |
| **半频/倍频** | **复 PCA 整合**（η-blend/Dual-Amp/Total·e^jφ）在 091339 段 2b 出现 **100% 半频**；Plan2 Modal **不经 PC1**，失效模式不同 |
| **明确废弃** | SVD Complex \|u₁\|、Remote·e^jφ、144 列 Dual-Amp 作部署路线 |

### 11.2 结构对照（Plan2 Modal vs PCA-Modal3）

```
Plan2 Modal：     每模态 = max-η 单信道 + 带通 → 谱 → 模态融合(η/top2) → BPM
PCA-Modal3：      每模态 = 72 道高通 PCA → PC1 谱 → 同一套模态融合 → BPM
```

相同：三模态、滑窗、谱融合权重。不同：滤波级、信道策略、top2 排序用 η 的定义（best 信道 η vs mean η）。

### 11.3 保留问题（待后续场景或算法迭代）

| ID | 问题 | 可能方向 |
|----|------|----------|
| **Q1** | 091339 上 PCA 模态内提取为何远差于 Single？差信道稀释 PC1，还是 phase/local 模态拖累？ | 每模态改为 **top1 信道** 与 PCA 对照；或 **PCA 前 top-K**（K=4/12）细调 |
| **Q2** | 复 PCA 半频能否用谐波惩罚或带通 PC1 抑制？ | 窗级谱峰二次检验；Re(PC1) 后再带通 |
| **Q3** | PCA-Modal 能否与 Plan2 **共识门控**（谱峰一致才融合）？ | 窗级 phase/remote/local 峰频差 > 阈值时退回 Single remote |
| **Q4** | 金属板三场景结论能否推广到人体/非金属？ | 新场景接入 `config/scenarios/` + `chFusion_pca_svd_cross_domain.py` |
| **Q5** | Total ch-η 单场景 3.35–3.81% 是否值得场景内调参？ | 仅当可接受 091339 类 **~28%** 尾部风险 |

### 11.4 推荐工作流（复现）

```bash
# 单场景完整 notebook（图表 + 排行榜）
python notebooks/scripts/chFusion_pca_svd.py

# 仅三场景跨域表（读/写 outputs/reports/）
python notebooks/scripts/chFusion_pca_svd_cross_domain.py

# 091339 倍频统计 + 最差段 PC1 谱图
python notebooks/scripts/chFusion_pca_svd_p1_diag.py
```

缓存失效条件：单场景 `.npy` 缺少 `REQUIRED_PCA_V2_CACHE_KEYS`（见 `pca_svd_pipeline.py`）。
