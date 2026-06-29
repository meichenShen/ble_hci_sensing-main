# WiFi MRC cs_091339 失效诊断与消融补齐 — 实现计划

> **来源**：
> - 上一轮报告：`docs/reports/wifi_mrc_baselines_report.md` — MRC-PCA-η-equal 跨域 10.78%，cs_091339 失效（17.63% vs B1 13.22%）
> - 上一轮 plan：`docs/plans/wifi_mrc_baselines_plan.md` §8.4 — Q2/Q3/Q4/Q5 未执行
> - Claude Review 判定：supported，4 项保留问题未关
>
> **目标报告**：`docs/reports/wifi_mrc_diagnosis_report.md`（模板：`docs/templates/algorithm_validation_report.md`）
> **日期**：2026-06-16
> **验证状态**：待实现

---

## 1. 动机与背景

### 1.1 问题

WiFi MRC baseline 实验确认：时域 MRC 可运行、PCA 符号校正有效（+3.9 pp），但最优 MRC（10.78%）仍差于 B1（8.45%）。且 **cs_091339 是 MRC 系统性失效的场景**：

| 方法 | cs_091339 | cs_095806 | cs_102621 | 跨域 mean |
|------|-----------|-----------|-----------|-----------|
| B1 Vote→Equal | 13.22 | 6.50 | 5.63 | 8.45 |
| MRC-PCA-η-equal | **17.63** | 7.29 | 7.41 | 10.78 |
| Fan-η-equal | **18.78** | 11.79 | 9.97 | 13.51 |

MRC 在 091339 上比 B1 差 4.41 pp，其他场景仅差 0.79–1.78 pp。若不理解失效机制，无法判断时域 MRC 在 BLE 上的真实边界。

上一轮 plan 的 4 项诊断问题（§8.4 Q2–Q5）未执行。其中 Q5（Fan η·ρ 消融）是回答「B1 vs Fan 的差距来自 Voting 还是 η·ρ」的关键实验。

### 1.2 本 plan 定位

本 plan 是 `wifi_mrc_baselines` 的**补充诊断与消融补齐**，不引入新算法。

| 项目 | 说明 |
|------|------|
| 问题 | cs_091339 MRC 为何失效？B1 vs Fan 差距归因？ |
| 相关文档 | `wifi_mrc.py`（复用并扩展）、上一轮 .npy 结果 |
| 本 plan 定位 | 诊断 + 消融补齐（Q2–Q5 同捆） |

---

## 2. 物理与变量

同 `wifi_mrc_baselines_plan.md` §2。本 plan 不改变观测量。

| 变量 | 是否使用 | 理由 |
|------|----------|------|
| `remote_amplitudes` | ✅ | 同上一轮 |
| `local_amplitudes` | ✅ | 同上一轮 |
| `phases`（总相位） | ✅ | 同上一轮 |
| `amplitudes`（总幅值） | ❌ | 无独立物理意义 |

---

## 3. 诊断与消融设计

共 5 项独立任务：D1–D3 为纯诊断（分析既有数据），A1–A2 为消融变体（需新增少量方法跑 BPM）。

### D1：per-window η 稳定性分析（Plan Q4）

**问题**：低采样率下 per-tone η 是否不稳定？cs_091339 的 η 是否比另两场景更噪声？

**方法**：

```
对每个场景 × 模态（remote_amp / local_amp / phases）：
    提取逐窗 72-tone η 向量
    计算：
        1. 相邻窗 η 的 tone 级 Pearson r（均值 ± std）
        2. η 窗口间变异系数 CV
        3. Top-10 η tone 相邻窗 Jaccard overlap
```

**输出**：
- 三场景 × 三模态 η 自相关曲线图
- 汇总表：`mean(r)`, `CV`, `top10_overlap`
- 判定：cs_091339 η 是否显著不如另两场景稳定

### D2：Best-modal 切换频率与分布（Plan Q3）

**问题**：Fan / MRC-PCA Best-modal 策略的窗间选择是否频繁跳变？cs_091339 是否更严重？

**方法**：

```
对 Fan-η-linear 和 MRC-PCA-η-sqrt：
    读取已有的 best_modal_per_window 字段
    统计：
        1. 模态选择直方图（remote vs local vs phase 占比）
        2. 相邻窗切换频率
        3. 按模态分组的 BPM 误差
```

**输出**：
- 三场景 × 两方法模态分布柱状图
- 切换频率表
- 按模态分组的 BPM 误差对比

### D3：PCA loading 一致性分析（扩展 Plan Q1）

**问题**：PCA 符号校正有效（Q1 已确认），但 cs_091339 上 PCA loading 是否窗口间不一致？

**方法**：

```
对 MRC-PCA-η-sqrt 每窗：
    提取 PCA loading v₁
    计算：
        1. 相邻窗 v₁ 余弦相似度
        2. sign(v₁) 稳定性（相邻窗符号一致的 tone 占比）
        3. explained_variance_ratio_
```

**输出**：
- 三场景 PCA loading 余弦相似度曲线
- v₁ 解释方差比分布
- 判定：cs_091339 PCA 是否本身不稳定

### A1：Fan η·ρ MRC 消融（Plan Q5）⭐ 关键

**问题**：B1（η·ρ Voting + Equal）vs Fan-η-equal（η MRC + Equal）的 5.06 pp 差距中，多少来自 Voting vs MRC，多少来自 η·ρ vs η？

**方法**：新增两个 η·ρ 权重变体：

| 变体 | MRC 权重 | 模态融合 | 目的 |
|------|----------|----------|------|
| **Fan-ηρ-linear** | w_i = η_i·ρ_i | Best modal | 对比 Fan-η-linear：纯权重差异 |
| **Fan-ηρ-equal** | w_i = η_i·ρ_i | Equal | 对比 B1：纯 Voting vs MRC |

`compute_mrc_weights(mode="eta_rho")` 已支持，只需在 `_fan_window_bpms` 中传入 rho。ρ 复用既有 per-tone 谱峰度计算。

**预期消融分解**：

```
B1 (8.45%)  ─┬─ Voting + η·ρ  ─── 参考
              │
Fan-ηρ-equal ─┬─ MRC + η·ρ      ─── 若接近 B1 → Voting 非关键
              │                     若仍差 B1 → Voting 独立优势
              │
Fan-η-equal  ─┬─ MRC + η         ─── η·ρ vs η 贡献 = Fan-ηρ-equal vs Fan-η-equal
(13.51%)
```

**输出**：
- Fan-ηρ-linear / Fan-ηρ-equal 的 3 场景 BPM err%
- 消融分解表：Voting vs MRC 贡献、η·ρ vs η 贡献

### A2：MRC-PCA-η-linear 变体

**问题**：MRC-PCA 框架下 η（线性）vs √η 权重孰优？

**方法**：新增 `MRC-PCA-η-linear`（`weight_mode="linear"` + PCA sign + Equal），已在 `mrc_pca_fusion` 中支持。

**输出**：MRC-PCA-η-linear 3 场景 BPM err%，对比 MRC-PCA-η-sqrt。

---

## 4. Baseline 对比

本 plan 不重跑既有 baseline。D1–D3 使用已有 .npy 结果。仅 A1–A2 需跑 **3 个新变体**：

| 方法 ID | 说明 | 实现 |
|---------|------|------|
| **Fan-ηρ-linear** | η·ρ-MRC → Best modal | 扩展 `_fan_window_bpms` 支持 rho |
| **Fan-ηρ-equal** | η·ρ-MRC + Equal | 同上 |
| **MRC-PCA-η-linear** | η-MRC + PCA sign → Equal | 暴露 `_mrc_pca_window_bpms` 的 weight_mode |

**引用已有结果**（不重跑）：B1 (8.45%), Fan-η-equal (13.51%), Fan-η-linear (15.21%), MRC-PCA-η-equal (10.78%), MRC-PCA-η-sqrt (11.95%)

**预期相对关系**（可被推翻）：

| 对比 | 预期 | 理由 |
|------|------|------|
| Fan-ηρ-equal vs Fan-η-equal | η·ρ 更优 | 引入峰度抑制假峰 tone |
| Fan-ηρ-equal vs B1 | 仍差于 B1 | MRC 时域合并丢失 per-tone 谱结构，Voting 谱域保留了 tone 间差异信息 |
| cs_091339 η 稳定性 | 差于另两场景 | 复杂多径 → η 对噪声更敏感 |

---

## 5. 评估设计

### 5.1 场景

三场景全部，权重相等：`cs_091339` / `cs_095806` / `cs_102621`

### 5.2 指标

**诊断（D1–D3）**：η 相邻窗 Pearson r、η CV、Top-10 Jaccard、Best-modal 切换频率、PCA loading cosine similarity、explained variance ratio

**BPM（A1–A2）**：分段 BPM 相对误差 % mean/std，跨域 mean，within 1/2 BPM ratio

### 5.3 成功标准

| 级别 | 条件 |
|------|------|
| **最低** | D1–D3 全部产出图表与统计，每项有明确结论 |
| **合格** | A1 产出消融分解表，定量归因 Voting vs MRC 和 η·ρ vs η |
| **良好** | 确定 cs_091339 MRC 失效的 ≥1 个主因（η 不稳定 / 模态选择错误 / PCA 不一致） |
| **理想** | Fan-ηρ-equal 接近 B1（差距 < 2 pp）→ 说明 B1 优势主要来自 η·ρ，Voting 非不可替代；或反之确认 Voting 独立优势 |

---

## 6. 实现要点

### 6.1 建议文件

| 类型 | 路径 |
|------|------|
| 实验脚本 | `notebooks/scripts/chFusion_wifi_mrc_diagnosis.py`（新建） |
| 可复用模块 | `src/ble_analysis/wifi_mrc.py`（**扩展** per-window 诊断输出 + eta_rho 路径） |
| 场景配置 | 沿用 `config/scenarios/cs_*.json` |

### 6.2 复用 API

```python
from ble_analysis.wifi_mrc import (
    compute_mrc_weights,        # 已支持 mode="eta_rho"
    fan_mrc_fusion,
    mrc_pca_fusion,
    estimate_bpm_from_waveform,
    run_wifi_mrc_benchmark,     # 扩展以输出额外诊断数据
)
from ble_analysis.chfusion import ChFusionConfig, _energy_ratio
from ble_analysis.segments import FilterParams, BreathMetricParams
from ble_analysis.voting_fusion import MODAL_VOTING_VARIABLES
```

### 6.3 扩展 `wifi_mrc.py` 建议

新增三个诊断辅助函数：

```python
def compute_eta_stability_diagnostics(
    multichannel_by_var, scenario_id, *, config=None, metric_params=None,
) -> dict:
    """D1: 逐窗 η 自相关 / CV / Top-10 overlap"""
    ...

def compute_modal_switching_diagnostics(
    results, method_keys=["fan_eta_linear", "mrc_pca_eta_sqrt"],
) -> dict:
    """D2: 已有 best_modal_per_window → 分布 + 切换频率"""
    ...

def compute_pca_loading_diagnostics(
    multichannel_by_var, scenario_id, *, config=None, metric_params=None, pca_top_k=36,
) -> dict:
    """D3: PCA loading cosine similarity + 符号稳定性"""
    ...
```

A1/A2 变体通过在 `_fan_window_bpms` 和 `_mrc_pca_window_bpms` 中暴露 rho / weight_mode 参数实现，不重写核心逻辑。

### 6.4 实现注意事项

1. D1–D3 优先用既有 .npy 结果。若逐窗 η / PCA loading 未保存，仅重跑 cs_091339 的滤波链（不重跑全三场景）。
2. ρ 值从 per-tone PSD 计算：`ρ = kurtosis(PSD_breath_band)`，需在数据收集阶段计算。
3. `mrc_pca_fusion` 当前不返回 loading 向量——需在 info dict 中增加 `loadings` 字段。
4. 场景 JSON 不得修改。
5. 诊断数据与 BPM 结果分开保存。

### 6.5 不做的事

- 不修改 MRC/Fan 核心算法
- 不重跑已有 baseline
- 不引入 B2 波形融合
- 不评估波形质量

---

## 7. 预期产出

### 7.1 诊断图表（D1–D3）

| 产出 | 路径 |
|------|------|
| η 自相关曲线 | `outputs/figures/wifi_mrc_diagnosis_eta_stability.png` |
| Best-modal 切换分布 | `outputs/figures/wifi_mrc_diagnosis_modal_switching.png` |
| PCA loading 余弦相似度 | `outputs/figures/wifi_mrc_diagnosis_pca_loading.png` |
| 诊断汇总图（三指标合一） | `outputs/figures/wifi_mrc_diagnosis_summary.png` |

### 7.2 消融结果（A1–A2）

| 产出 | 路径 |
|------|------|
| 消融 BPM 数值 | `outputs/reports/wifi_mrc_diagnosis_ablation.npy` |
| 消融分解表图 | `outputs/figures/wifi_mrc_diagnosis_ablation_decomposition.png` |
| 消融跨域排行榜 | `outputs/figures/wifi_mrc_diagnosis_ablation_leaderboard.png` |

### 7.3 报告

`docs/reports/wifi_mrc_diagnosis_report.md`

### 7.4 建议运行命令

```bash
python notebooks/scripts/chFusion_wifi_mrc_diagnosis.py --all
```

---

## 8. 风险

| 风险 | 概率 | 缓解 |
|------|------|------|
| 既有 .npy 不含逐窗 η/PCA loading | 中 | 仅重跑 cs_091339 滤波链提取所需量 |
| ρ 未按 tone 单独存储 | 高 | 从 per-tone PSD kurtosis 计算 |
| PCA loading 数据量大 | 低 | 仅存 top-36 loading |

---

## 9. 验证状态

| 字段 | 内容 |
|------|------|
| **验证状态** | 已完成 |
| **实际脚本** | `notebooks/scripts/chFusion_wifi_mrc_diagnosis.py` |
| **核心模块** | `src/ble_analysis/wifi_mrc.py`（扩展诊断 + A1/A2） |
| **报告链接** | `docs/reports/wifi_mrc_diagnosis_report.md` |
| **数值结果** | `outputs/reports/wifi_mrc_diagnosis_diagnostics.npy`、`wifi_mrc_diagnosis_ablation.npy` |
| **图表** | `outputs/figures/wifi_mrc_diagnosis_*.png` |
| **一句话结论** | η·ρ MRC 缩小 Fan 与 B1 差距至 2.33 pp，确认 Voting 独立优势；091339 失效不由 η/模态切换/PCA 不稳定解释。 |

### 保留问题

| ID | 问题 | 备注 |
|----|------|------|
| Q091 | cs_091339 MRC 失效主因 | D1–D3 均未支持原假设；η CV 偏高待深入 |
| Q-Vote | Voting 优势机制 | 谱域保留 per-tone 结构 vs 时域加权合并 |
| Q-B2 | 波形方向是否仍有价值 | BPM 超越 B1 预期有限 |

---

## 10. 给执行 Agent 的首条指令

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并严格执行：

`docs/plans/wifi_mrc_diagnosis_plan.md`

执行要点：

1. **D1–D3 优先**：先用既有 .npy 做诊断。若缺失数据，仅重跑 cs_091339。
2. **A1/A2 轻量扩展**：在 `_fan_window_bpms` 增加 eta_rho 路径，`_mrc_pca_window_bpms` 暴露 weight_mode，不重构模块。
3. 使用 `docs/templates/algorithm_validation_report.md` 撰写报告。
4. 回填本 plan §9。

执行完成后，请返回：

- `docs/reports/wifi_mrc_diagnosis_report.md`
- `outputs/reports/wifi_mrc_diagnosis_*.npy`
- `outputs/figures/wifi_mrc_diagnosis_*.png`
- `src/ble_analysis/wifi_mrc.py` diff
- `notebooks/scripts/chFusion_wifi_mrc_diagnosis.py`
- git commit 摘要

---

## 附录：与上一轮待办对应

| 上一轮待办 | 本 plan | 类型 |
|-----------|---------|------|
| Q1: tone 间反相 | 已确认 ✅ | 已关 |
| Q2: η vs η·ρ Spearman | 合并入 A1（若 η·ρ vs η 差异大，自然说明不一致） | 🔀 |
| Q3: Best-modal 切换 | D2 | 诊断 |
| Q4: η 窗口间自相关 | D1 | 诊断 |
| Q5: Fan η·ρ 消融 | A1 ⭐ | 消融 |
| cs_091339 MRC 失效 | D1 + D2 + D3 | 诊断 |
| MRC-PCA-η-linear | A2 | 消融 |
