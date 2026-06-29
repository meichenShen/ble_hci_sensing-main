# SA 门控退化根因诊断 — 实现计划

> **来源**：
> - [Signal adaptive gating report](../reports/signal_adaptive_gating_report.md) — 无 SA 变体跨域优于 B1（8.45%）；SA-v1 = 11.42%（+2.97pp）
> - [Signal adaptive gating plan](../plans/signal_adaptive_gating_plan.md) — H1/H3 未证实，SA-v2 最优 10.66%
> - [B1 gating & diagnosis report](../reports/b1_gating_and_diagnosis_report.md) — G4-B1-v2 8.05%，102621 上 B1 加入门控反而退化
>
> **定位**：**纯诊断** — 不解锁新算法，仅后分析已有 SA benchmark 数据，回答一个核心问题：**SA-v1 的门控决策在哪些窗上、以何种方式破坏了无门控 B1 的正确估计？**
>
> **目标报告**：`docs/reports/sa_degradation_diagnosis_report.md`  
> **日期**：2026-06-08

---

## 1. 动机与背景

### 1.1 核心问题

SA 实验的核心负结果是：

```
B1（无门控）→ 8.45%
SA-v1（三候选一致性门控 + best-single fallback）→ 11.42%
差距：+2.97pp
```

这意味着 **SA-v1 的门控决策在净效应上是破坏性的**——它在某些窗上纠正了 B1 的错误，但在更多窗上引入了新的误差。我们需要知道：

1. **哪些窗上 SA-v1 ≠ B1？**（门控改变了最终 BPM 的窗占比）
2. **这些改变中，多少是正确的（SA-v1 比 B1 更接近 GT），多少是错误的？**
3. **错误集中在哪个决策路径？**（三重共识？对共识？best-single fallback？）
4. **091339 上 SA-v1 退化尤其严重（18.66% vs B1 13.22%，+5.44pp），原因是什么？**

### 1.2 本 plan 不做什么

- 不设计新算法
- 不修改任何 gating 逻辑
- 不跑新 benchmark（复用已有 SA benchmark 输出）
- 不改变 threshold 或参数

---

## 2. 数据来源

**全部复用已有数据，不新增 benchmark 运行。**

| 数据 | 路径 | 内容 |
|------|------|------|
| SA 跨域结果 | `outputs/reports/signal_adaptive_gating_cross_domain.npy` | 各方法 per-scene mean error |
| SA per-scene 结果 | `outputs/reports/signal_adaptive_gating_{091339,095806,102621}_results.npy` | 包含窗级 BPM 序列 |
| SA benchmark 脚本 | `notebooks/scripts/chFusion_signal_adaptive_gating.py` | 参考门控逻辑实现 |
| SA 门控模块 | `src/ble_analysis/signal_adaptive_gating.py` | 参考决策路径标签 |

> ⚠️ 如果 per-scene .npy 文件不含 **窗级 BPM 序列**（只有 summary statistics），则需要重新运行 benchmark 脚本，但**仅保存更细粒度的中间输出**——不改变任何算法逻辑。

---

## 3. 诊断设计

### 3.1 D1：SA-v1 与 B1 逐窗误差对比（三场景）

```
对每场景每窗：
  error_b1   = |bpm_b1 − bpm_gt|       （转换为 BPM err% 或保持 BPM 差值）
  error_sa   = |bpm_sa-v1 − bpm_gt|
  delta_err  = error_sa − error_b1     （正 = SA-v1 更差）

  sa_decision = SA-v1 的决策标签（triple_consensus / pair_consensus / best_single_fallback / ...）
  b1_deviation = |bpm_b1 − bpm_vote| （B1 偏离 Voting 候选的幅度）
  consensus_score = triplet_consensus_score（来自 SA-v1 内部）

汇总：
  1. SA-v1 ≠ B1 的窗占比（bpm 差 > 0.1 BPM）
  2. 在这些窗中：SA-v1 正确（|error_sa| < |error_b1|） vs SA-v1 错误（翻转） vs 两者同向
  3. delta_err 的分布（正 = SA-v1 更差）
```

**产出图表**：

| 图 ID | 内容 | 说明 |
|--------|------|------|
| D1-a | 三场景 SA-v1 error vs B1 error 散点图 | 每点一个窗，按 sa_decision 着色；对角线 = 两者相等；点在对角线上方 = SA-v1 更差 |
| D1-b | delta_err 分布（三场景分面直方图） | 正偏 = SA-v1 系统性地更差 |
| D1-c | 汇总表：SA-v1 改善 / 恶化 / 不变的窗数及占比 | 按场景 + 按决策路径分组 |

### 3.2 D2：按决策路径分解误差（三场景）

```
SA-v1 的决策路径（从 gate_signal_adaptive 的 decision_tag 获取）：
  A. triple_consensus    — 三候选 delta ≤ 3 BPM，三者平均（含 B1）
  B. pair_consensus      — 仅两个候选 delta ≤ 3 BPM，两者平均
     B1. B1 在共识对中 → 平均含 B1
     B2. B1 不在共识对中 → 平均不含 B1（B1 被忽略）
  C. best_single_fallback — 三者全分散 → 选 η·ρ 最高单信道

每路径汇总：
  窗数、占比
  该路径上 SA-v1 error mean/std
  该路径上 B1 error mean/std（对比：SA-v1 是在改善还是破坏）
  该路径上 GT 的分布（是否存在呼吸段/ apnea 的影响）
```

**产出图表**：

| 图 ID | 内容 |
|--------|------|
| D2-a | 分组柱状图：各决策路径的 mean error（SA-v1 vs B1 vs GT baseline），三场景各一组 |
| D2-b | 决策路径分布饼图（三场景对比，与已有 `sa_decision_distribution.png` 互补——这次叠加 error 着色） |

### 3.3 D3：Best-single fallback 失效机制分析

```
当 SA-v1 进入 best_single_fallback（路径 C）时：
  1. 选中的是哪个模态？（remote / local / phase）— 分布
  2. 该 fallback 的 BPM error vs B1 error vs GT
  3. 该窗的 triplet_consensus_score 分布（确认确实是"全分歧"）
  4. 该窗上 B1 的 error 是多少？（如果 B1 本身在这些窗上很好，说明 fallback 是倒退）

对比：
  - 路径 C 窗上：B1 如果被直接使用（不做 fallback），error 是多少？
  - 路径 C 窗上：如果 fallback → hardcoded Remote（SA-v1+SingleRemote 的行为），error 是多少？
```

**产出图表**：

| 图 ID | 内容 |
|--------|------|
| D3-a | 路径 C 窗上 SA-v1 vs B1 vs SA-v1+SingleRemote 三者 error 对比（箱线图） |
| D3-b | 路径 C 窗上被选中的 fallback 模态分布（柱状图），按场景分面 |

### 3.4 D4：091339 专项退化分析

```
仅 091339 场景：
  D4.1：SA-v1 各决策路径的窗数占比 vs 095806/102621
        → 是否 091339 上全分歧（路径 C）占比显著更高？
  D4.2：路径 C 窗上 fallback 选中了哪个模态？
        → 091339 上 best_single 是否大量误选（选了 local 或 phase 而实际 remote 更好）？
  D4.3：091339 上 triplet_consensus_score 的分布 vs 其他两场景
        → 是否 091339 上三候选系统性更不一致（consensus_score 整体偏低）？
  D4.4：091339 上 B1 正确但 SA-v1 改错的窗，集中于哪个决策路径？
```

**产出图表**：

| 图 ID | 内容 |
|--------|------|
| D4-a | 三场景决策路径占比对比（堆叠柱状图），091339 高亮 |
| D4-b | 091339 上 consensus_score 直方图 vs 095806/102621 叠加 |
| D4-c | 091339 上 B1 error vs SA-v1 error 散点，标注误选 fallback 模态 |

### 3.5 D5：Consensus score 作为门控信号的质量评估

```
三场景汇总：
  1. triplet_consensus_score 与 B1 error 的 Spearman / Pearson 相关系数
     → 高 consensus 是否确实意味着 B1 更准确？
  2. triplet_consensus_score 与 SA-v1 error 的相关系数
     → 门控本身是否在利用这个信号？
  3. 将 consensus_score 按 [0-0.2, 0.2-0.4, 0.4-0.6, 0.6-0.8, 0.8-1.0] 分箱
     每箱内 B1 error mean, SA-v1 error mean
     → 是否存在一个 consensus_score 区间，SA-v1 明确优于 B1？
```

**产出图表**：

| 图 ID | 内容 |
|--------|------|
| D5-a | Consensus score vs B1 error 散点 + 分箱均值折线（三场景分面） |
| D5-b | 分箱柱状图：各 consensus_score 段的 SA-v1 vs B1 mean error |

---

## 4. 实现要点

### 4.1 不新增 benchmark

本 plan 的核心假设是：SA benchmark 脚本 (`chFusion_signal_adaptive_gating.py`) 在运行时已经保存了每窗的 BPM 值。诊断代码只读取这些已有 .npy 文件做后分析。

**如果 per-scene .npy 不含窗级 BPM 序列**（仅 summary），需修改 benchmark 脚本的**保存部分**（不涉及算法逻辑），将每窗 BPM 追加写入。

### 4.2 建议文件

| 类型 | 路径 |
|------|------|
| 诊断脚本 | `notebooks/scripts/chFusion_sa_degradation_diagnosis.py` |
| 可复用诊断函数 | `src/ble_analysis/sa_diagnostics.py`（新增） |

### 4.3 关键函数签名

```python
def load_per_window_bpm(
    results_path: str,
) -> Dict[str, np.ndarray]:
    """从 SA benchmark .npy 加载各方法窗级 BPM 序列.
    返回 {"b1": bpm_array, "sa_v1": ..., "sa_v1_single_remote": ..., "gt": ...}
    """
    ...

def compare_window_errors(
    bpm_method: np.ndarray,
    bpm_baseline: np.ndarray,
    bpm_gt: np.ndarray,
) -> Dict:
    """逐窗比较两个方法的 error.
    返回改善/恶化/不变的窗 index 和 delta_err.
    """
    ...

def analyze_by_decision_path(
    bpm_sa: np.ndarray,
    bpm_b1: np.ndarray,
    bpm_gt: np.ndarray,
    decision_tags: List[str],
    fallback_modalities: List[str],
) -> pd.DataFrame:
    """按决策路径分组汇总 error.
    """
    ...

def analyze_consensus_score_quality(
    consensus_scores: np.ndarray,
    error_b1: np.ndarray,
    error_sa: np.ndarray,
    n_bins: int = 5,
) -> Dict:
    """Consensus score 与 error 的相关性分析.
    """
    ...
```

### 4.4 注意

- 所有分析是**纯后处理**，不重新跑 BPM 估计
- 决策标签（decision_tag）和共识分数（consensus_score）需要 SA-v1 benchmark 在运行时保存
- 如果当前 benchmark 脚本未保存这些中间量（仅保存了 final BPM），需要做一次**最小侵入的重新运行**：仅增加 intermediate outputs 的保存，不动算法

---

## 5. 预期产出

| 产出 | 路径 |
|------|------|
| 诊断报告 | `docs/reports/sa_degradation_diagnosis_report.md` |
| 诊断结果数据 | `outputs/reports/sa_degradation_diagnosis_results.npy` |
| D1-a 散点图 | `outputs/figures/sa_diag_d1_error_scatter.png` |
| D1-b 直方图 | `outputs/figures/sa_diag_d1_delta_error_hist.png` |
| D2-a 柱状图 | `outputs/figures/sa_diag_d2_path_error_bar.png` |
| D2-b 饼图 | `outputs/figures/sa_diag_d2_path_pie.png` |
| D3-a 箱线图 | `outputs/figures/sa_diag_d3_fallback_error_box.png` |
| D3-b 柱状图 | `outputs/figures/sa_diag_d3_fallback_modality_bar.png` |
| D4-a 堆叠柱状图 | `outputs/figures/sa_diag_d4_091339_path_compare.png` |
| D4-b 直方图 | `outputs/figures/sa_diag_d4_091339_consensus_hist.png` |
| D4-c 散点图 | `outputs/figures/sa_diag_d4_091339_error_scatter.png` |
| D5-a 散点+折线 | `outputs/figures/sa_diag_d5_consensus_vs_error.png` |

---

## 6. 风险与保留问题

| 风险 | 影响 | 缓解 |
|------|------|------|
| 当前 .npy 不含窗级 BPM 序列和决策标签 | 需重新运行 benchmark 保存中间量 | 最小侵入：仅修改保存逻辑，不动算法 |
| SA-v1 代码在 benchmark 运行后可能未保留 decision_tag | 无法按决策路径分组 | 可从 bpm_sa 和 bpm_b1/bpm_vote/bpm_modal 反推（delta = 3 BPM 规则可逆推） |
| 窗数较少（每场景 ~30-50 窗） | 分箱后每格样本量小 | 不做过度细分（D5 分 5 箱以内） |
| 诊断结果可能显示门控在**所有**路径都劣于无门控 | 这对下一步有明确指导意义：放弃窗级门控路线 | 仍是有价值的结论 |

---

## 7. 验证状态

状态：**待实现**

---

## 给执行 Agent 的首条指令

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并严格执行：

`docs/plans/sa_degradation_diagnosis_plan.md`

### 执行范围

**纯诊断，不新增 benchmark，不修改算法。**

1. **数据加载**：读取 `outputs/reports/signal_adaptive_gating_*.npy`，提取 B1 和 SA-v1（+ SA-v1+SingleRemote）的窗级 BPM 序列和 GT。
2. **D1**：逐窗 SA-v1 vs B1 error 对比（三场景）。
3. **D2**：按 SA-v1 决策路径分解误差。
4. **D3**：Best-single fallback 失效机制。
5. **D4**：091339 专项（路径分布 + consensus score + fallback 模态）。
6. **D5**：Consensus score 作为门控信号的质量评估。

### 关键注意

- 如果当前 .npy 不含窗级 BPM 和 decision_tag，需要以最小侵入方式重新运行 benchmark：
  - **只改保存逻辑**（增加 intermediate outputs 的 .npy 保存）
  - **不动 `gate_signal_adaptive()` 或任何信道/模态融合函数**
  - 修改前先备份原始 `chFusion_signal_adaptive_gating.py`
- 所有分析必须三场景分别呈现 + 跨域汇总
- 091339 分析需单独成章（§3.4）
