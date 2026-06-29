# B1 联合门控与 Vote→Equal 机制诊断 — 实现计划

> **来源**：
> - [Systematic modal-channel fusion plan](../plans/systematic_modal_channel_fusion_plan.md) — B1 8.45% 跨域最优，但 B3 Vote→Top2 失败
> - [Systematic fusion report](../reports/systematic_modal_channel_fusion_report.md) — 开放问题 Q1–Q5
> - [Voting gating achievement report](../achievements/voting_gating_achievement_report.md) — G4 8.65%，发现无全局最优门控
> - [CS呼吸算法验证整体进度](../CS呼吸算法验证整体进度.md)
>
> **目标报告**：`docs/reports/b1_gating_and_diagnosis_report.md`  
> **日期**：2026-06-08（初稿）

---

## 1. 动机与背景

### 1.1 核心问题：B1 全局最优但仍有两个关键短板

Systematic fusion 实验确立了 **B1（Vote→Equal modal）= 8.45%** 为当前跨域最优，突破了理想标准 8.5%。但两个关键问题阻碍了 B1 成为可部署的默认 pipeline：

| # | 问题 | 证据 |
|---|------|------|
| **P1** | B1 在 102621 上输给 G4（5.63% vs 4.51%，差 1.12pp） | B1 不是所有场景最优 |
| **P2** | Vote→Equal（B1 8.45%）有效但 Vote→Top2（B3 9.92%）无效——机制不明 | 若无法解释，则 B1 的优越性可能是偶然的 |

此外，**091339 仍是系统性瓶颈**——所有方法的 mean err% > 12%，B1 = 13.22% 仅比 T0-V3 13.77% 微降 0.55pp。

### 1.2 本 plan 定位

本 plan 不探索新的信道或模态策略，而是聚焦三个目标：

1. **工程级改进**：将 B1 加入 G4 的门控框架，期望同时利用 B1（095806 优势）和 G4（102621 优势），推动跨域 mean 进一步降低。
2. **机制理解**：诊断 Vote→Equal vs Vote→Top2 的行为差异，确认 B1 的优越性是否源于可解释的物理机制，还是当前三场景的偶然过拟合。
3. **091339 攻坚**：分析 B1 在 091339 上的失效模式，尝试结合 G5 双峰性门控改善。

### 1.3 核心假设

> **H1（B1+G4 联合门控）**：在三候选（B1、T0-V3、Modal top2）门控框架中，G4-like 共识/fallback 策略可实现跨域 mean < 8.3%，且三场景均不差于各自单一最优方法。

> **H2（Equal vs Top2 的机制差异）**：B1（Equal）优于 B3（Top2）的原因是：Voting→谱在三种模态上产生的频谱形状相似度高于 Single-best→谱，导致 Top2 的模态选择性退化——被踢出的模态与被保留的模态在频谱上差异小，Top2 退化退化为约 2/3 的 Equal。即 **Voting 信道策略降低了模态间的差异性，使 Top2 选择失去意义**。

> **H3（091339 双峰性门控 + B1）**：091339 上 voting BPM 直方图的双峰性是 B1 在该场景退化的根因。当 per-modal voting 的 BPM 分布呈双峰时，conf 加权谱被两个峰同时污染。结合 G5 级双峰性检测（在窗级剔除双峰模态后再做 Equal 融合）可将 091339 mean err% 降至 12% 以下。

> **H4（谱构造方式的敏感度）**：B1 的有效性依赖当前 conf 加权全谱（方案 B）的构造方式。如果用 winning-bin 窄带谱（方案 A）或 top-K tone 平均谱（方案 C），B1 和 B3 的排名可能反转。

---

## 2. 物理与变量

### 2.1 沿用变量

与 systematic fusion plan 一致：

| 变量 | 是否使用 | 理由 |
|------|----------|------|
| `remote_amplitudes` | ✅ | Voting per modal 的三模态之一 |
| `local_amplitudes` | ✅ | 同上；Modal top2 中常被踢出，但 Equal 融合中权重均等 |
| `phases` | ✅ | 同上；095806 上 Phase voting 单模态即 5.81% |

### 2.2 新增诊断变量

| 诊断量 | 含义 | 用途 |
|--------|------|------|
| `bimodality_score(var)` | per-modal voting BPM 直方图的双峰性（Hartigan's dip test 或双峰比） | H3 诊断：识别 voting 不可靠窗 |
| `spectral_cosine(var_i, var_j)` | 两个模态归一化频谱的余弦相似度 | H2 诊断：量化 Voting→谱的模态间相似度 |
| `top2_excluded_var` | B3 在每窗踢出了哪个模态 | H2 诊断：被踢出模态在 Equal 中的贡献 |

---

## 3. 算法设计

### 3.1 主实验：B1+G4 联合门控（G4-B1）

在现有 G4 框架中增加 B1 作为第三候选：

```
每窗并行计算：
  candidate_1 = T0-V3  (单模态 remote voting)
  candidate_2 = Modal top2  (Single-best per modal → Top2 谱融合)
  candidate_3 = B1  (Vote per modal → Equal 谱融合)

门控规则（G4 逻辑扩展）：
  if |c1 - c2| ≤ δ and |c1 - c3| ≤ δ and |c2 - c3| ≤ δ:
      bpm = weighted_average(c1, c2, c3)  # 三方法共识
  elif |c1 - c2| ≤ δ:
      bpm = mean(c1, c2)  # c1-c2 共识
  elif |c1 - c3| ≤ δ:
      bpm = mean(c1, c3)  # c1-c3 共识
  elif |c2 - c3| ≤ δ:
      bpm = mean(c2, c3)  # c2-c3 共识
  else:
      bpm = Single Remote  # 三方法全分歧 → fallback
```

δ = 3 BPM（与 G4 一致）。

**变体**：

| ID | 变体 | 说明 |
|----|------|------|
| G4-B1-v1 | 三候选 + G4 共识规则 | 主方案 |
| G4-B1-v2 | 三候选 + top2 共识（取三候选中最接近的两个） | 备选：避免 δ 硬阈值 |
| G4-B1-v3 | 三候选 + B1 优先（分歧时默认 B1） | 验证 B1 是否可直接作为 fallback target |
| G4-B1-v4 | 双候选 G4（B1 vs Modal top2，去掉 T0-V3） | 降复杂度：B1 已包含 voting 信息 |

### 3.2 诊断实验

#### 3.2.1 诊断 D1：Equal vs Top2 模态间频谱相似度（H2）

在每窗计算：

```
1. 对 B1（Equal）：记录三模态 Voting→谱 → 融合后 BPM
2. 对 B3（Top2）：记录三模态 Voting→谱 → 被踢出模态 → 融合后 BPM
3. 计算余弦相似度矩阵：
   sim_{ij} = cosine(spectrum_var_i, spectrum_var_j)
   对比 B1 窗和 B3 窗的 sim 分布差异
4. 分析 B3 踢出模态的频谱与被保留模态的差异
```

**预期（如果 H2 成立）**：B3 窗的 `mean(sim_{ij})` 应显著高于 Modal top2（Single-best→谱）窗的对应值——即 Voting 产生的三种模态频谱比 Single-best 产生的更相似，导致 Top2 选择退化为近似 Equal×2/3。

#### 3.2.2 诊断 D2：091339 双峰性诊断（H3）

在 091339 每窗计算：

```
1. 对每个模态的 72-tone voting BPM 直方图做 bimodality 检测
2. 如果任一模态 bimodality_score > 0.5：
   a. 记录该窗为 "bimodal window"
   b. 对比 B1 vs B3 vs Single Remote 在该窗的 BPM 误差
3. 汇总：双峰窗 vs 单峰窗的 B1 error 分布
```

**预期（如果 H3 成立）**：B1 的误差主要集中在 bimodal windows 上；在这些窗上，B1 的 conf 加权谱被两个峰同时污染。

#### 3.2.3 诊断 D3：谱构造方式 ablation（H4）

对 B1 和 B3 分别测试三种谱构造方式：

| 方案 | 构造方式 | 实现 |
|------|----------|------|
| A (winning-bin) | 取 voting winning bin ±2 BPM 内的 tone 的平均谱 | 新实现 |
| B (conf-weighted) | 所有 tone 的归一化谱按 voting weight 加权平均 | 当前实现 |
| C (top-K) | 取 voting weight top-K（K=16, 24）的 tone 的等权平均谱 | 新实现 |

**预期（如果 H4 成立）**：方案 A 下 B3（Vote→Top2）可能优于方案 B 下的 B3——winning-bin 窄带谱增强了模态间差异，使 Top2 选择更有意义。

### 3.3 091339 专项：B1 + 双峰性门控（G5-B1）

```
每窗：
1. 计算 per-modal voting BPM 直方图的 bimodality_score
2. 如果所有三个模态 bimodality_score < 0.5（单峰）：
     bpm = B1（Vote per modal → Equal 融合）
   elif 至少两个模态 bimodality_score < 0.5：
     bpm = 仅用单峰模态的 Equal 融合（踢出双峰模态）
   else（≥两个模态双峰）：
     bpm = Single Remote  # fallback
```

此策略仅在 091339 上单独测试，不期望在 095806/102621（本身 bimodality 低）上有改善。

---

## 4. Baseline 对比

### 4.1 必须复现的 baseline

| ID | 方法 | 跨域 mean | 来源 |
|----|------|-----------|------|
| B1 | Vote→Equal modal | 8.45% | systematic fusion |
| G4 | Single fallback | 8.65% | voting gating |
| G5 | Bimodality gating | 8.72% | voting gating |
| T0-V3 | Remote voting | 9.20% | voting fusion |
| Modal top2 | Single-best + Top2 | 9.45% | Plan2 |

### 4.2 待测方法

| ID | 方法 | 说明 |
|----|------|------|
| **G4-B1-v1** | 三候选 G4 门控 | 主方案 |
| **G4-B1-v2** | 三候选 top2 共识 | 备选 |
| **G4-B1-v3** | B1 优先 fallback | 备选 |
| **G4-B1-v4** | B1 vs Modal 双候选 | 降复杂度 |
| **D3-A-B1** | winning-bin 谱 + Equal | 谱构造 ablation |
| **D3-A-B3** | winning-bin 谱 + Top2 | 谱构造 ablation |
| **D3-C-B1** | top-K 谱 + Equal | 谱构造 ablation |
| **D3-C-B3** | top-K 谱 + Top2 | 谱构造 ablation |
| **G5-B1** | B1 + 双峰性门控（仅 091339） | 091339 专项 |

### 4.3 预期相对关系

| 对比 | 预期 | 理由 |
|------|------|------|
| G4-B1-v1 vs G4 | 更好 | B1 在三候选时提供额外的 voting→谱 选项 |
| G4-B1-v1 vs B1 | 更好（或相当） | 门控可在 B1 弱的窗退回 G4/T0-V3 |
| D3-A-B3 vs B3（方案B） | 更好 | winning-bin 谱增强模态间差异 |
| G5-B1 vs B1 (091339) | 更好 | 剔除双峰模态后 Equal 融合更稳定 |

---

## 5. 评估设计

### 5.1 场景

| 场景 | 用途 |
|------|------|
| `cs_091339` | 主诊断场景 + 091339 专项（G5-B1） |
| `cs_095806` | 验证门控不损失 B1 优势 |
| `cs_102621` | 验证门控改善 B1 vs G4 劣势 |

### 5.2 指标

| 指标 | 说明 |
|------|------|
| 分段 BPM err% mean / std | 主指标 |
| 跨域 mean | 三场景平均 |
| 各候选被选中占比（门控决策分布） | 新增：分析 B1/T0-V3/Modal/Single 各被选中的窗比例 |
| 模态间频谱余弦相似度分布 | 诊断指标（D1） |
| 双峰窗 B1 error vs 单峰窗 B1 error | 诊断指标（D2） |
| B3 被踢出模态的频谱相似度 vs 保留模态 | 诊断指标（D1） |

### 5.3 成功标准

| 级别 | 条件 |
|------|------|
| **理想** | G4-B1-v1 跨域 mean < **8.0%**，且三场景无不差于各自单一最优 |
| **良好** | G4-B1-v1 跨域 mean < **8.3%**，且 102621 上不差于 G4（4.51%） |
| **最低** | G4-B1-v1 跨域 mean < B1（8.45%）且诊断 D1/D2 产出明确机制解释 |
| **诊断成功** | D1 发现 Voting→谱的模态间相似度显著高于 Single-best→谱；D2 确认双峰窗是 091339 B1 误差主源 |
| **失败** | G4-B1-v1 跨域 ≥ 8.45%，说明 B1 与 G4 的门控组合无法超越单一最优 |

---

## 6. 实现要点

### 6.1 文件规划

| 类型 | 路径 | 说明 |
|------|------|------|
| 实验脚本 | `notebooks/scripts/chFusion_b1_gating_diagnosis.py` | 主脚本 |
| 可复用模块（扩展） | `src/ble_analysis/systematic_fusion.py` | 新增 `run_b1_gating_benchmark()` 和诊断函数 |
| 可复用模块（扩展） | `src/ble_analysis/consensus_gating.py` | 扩展 G4 门控为三候选 |

### 6.2 复用 API

```python
# 信道/模态级
from ble_analysis.systematic_fusion import (
    per_modal_voting_spectrum,
    per_modal_uniform_spectrum,
    modal_fusion_from_spectra,
    run_systematic_fusion_benchmark,
)
from ble_analysis.consensus_gating import (
    compute_bimodality_score,
    _gate_one_window_g4,  # 需扩展为三候选版本
)
from ble_analysis.voting_fusion import (
    VotingConfig, _vote_one_window, vote_bpm_weighted_histogram,
)
from ble_analysis.chfusion import (
    ChFusionConfig, _bpm_from_fused_spectrum,
    _channel_spectrum_and_q, _energy_ratio,
    estimate_modal_best_channel_fusion,
)
```

### 6.3 关键新增函数签名

```python
def gate_three_candidates(
    bpm_b1: float, bpm_vote: float, bpm_modal: float,
    bpm_single: float,
    delta: float = 3.0,
    variant: str = "v1",  # "v1" | "v2" | "v3" | "v4"
) -> Tuple[float, str]:
    """三候选门控；返回 (bpm, decision_tag)."""
    ...

def compute_modal_spectral_similarity(
    spectra: Dict[str, np.ndarray],  # {var: spec} per-modal spectra
) -> float:
    """计算模态间频谱的平均余弦相似度."""
    ...

def compute_voting_bimodality_per_modal(
    bpm_per_tone_per_var: Dict[str, np.ndarray],
) -> Dict[str, float]:
    """对每个模态的 voting BPM 分布计算 bimodality score."""
    ...

def per_modal_voting_spectrum_variant(
    ch_list, ch_map, variable, st, end, fs, cfg, vcfg, ...,
    spectrum_mode: str = "conf_weighted",  # "conf_weighted" | "winning_bin" | "top_k"
    top_k: int = 16,
) -> Tuple[np.ndarray, float, dict]:
    """支持多种谱构造方式的 per-modal voting→谱."""
    ...
```

### 6.4 不做的事

- 不新增场景 JSON
- 不改变滑窗参数或滤波链
- 不探索新的信道策略或模态策略
- 不对 τ/δ/K 做 exhaustive grid search
- 不做 G7–G9（文献驱动方法）

---

## 7. 预期产出

| 产出 | 路径 |
|------|------|
| 验证报告 | `docs/reports/b1_gating_and_diagnosis_report.md` |
| 数值结果 | `outputs/reports/b1_gating_diagnosis_results.npy` |
| 跨域汇总 | `outputs/reports/b1_gating_diagnosis_cross_domain.npy` |
| 门控决策分布图 | `outputs/figures/b1_gating_decision_pie.png` |
| 排行榜图 | `outputs/figures/b1_gating_leaderboard.png` |
| 模态相似度对比图 | `outputs/figures/b1_diag_spectral_similarity.png` |
| 双峰窗 error 分布图 | `outputs/figures/b1_diag_bimodal_error.png` |
| 谱构造 ablation 对比图 | `outputs/figures/b1_diag_spectrum_mode.png` |

---

## 8. 风险与保留问题

### 8.1 算法风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| B1 与 G4 的门控组合不产生改善 | 高 | 设计 v1–v4 四种变体，覆盖不同门控哲学 |
| D3 谱构造 ablation 中方案 A 实现复杂 | 中 | winning bin 的定义需要明确 bin width（±2 BPM），可能需试验几个值 |
| 091339 双峰性不是 B1 退化的唯一原因 | 中 | D2 也分析单峰窗的误差，不完依赖 H3 |
| 诊断显著增加了每窗计算量 | 低 | D1/D2 仅在 P0 诊断阶段计算，G4-B1 主实验不增加额外计算 |

### 8.2 保留问题

| ID | 问题 | 备注 |
|----|------|------|
| Q1 | G4-B1 组合是否应该包含 G5 双峰性门控作为第四候选？ | `[待确认]` — 可在本 plan P1 阶段追加 |
| Q2 | 如果 D1 确认模态间相似度高，是否应该改用 ρ 而非 η 作为 modal selector？ | `[待确认]` — ρ 可能对不同模态的频谱形状差异更敏感 |
| Q3 | D3 中 top-K 的 K 值如何选？ | 当前建议 K=16, 24，与之前 voting plan 中的 K 试验一致 |
| Q4 | B1 的 conf 加权谱是否过度信任 high-conf 窗？ | conf 分布需要在诊断中分析 |

---

## 9. 验证状态

状态：**已完成**

| 字段 | 内容 |
|------|------|
| **验证状态** | 已完成（P0：G4-B1 v1–v4、D1–D3、G5-B1） |
| **脚本** | `notebooks/scripts/chFusion_b1_gating_diagnosis.py` |
| **模块** | `src/ble_analysis/b1_gating_diagnosis.py`, `src/ble_analysis/consensus_gating.py` |
| **数值结果** | `outputs/reports/b1_gating_diagnosis_*.npy` |
| **图表** | `outputs/figures/b1_gating_*.png`, `outputs/figures/b1_diag_*.png` |
| **报告** | `docs/reports/b1_gating_and_diagnosis_report.md` |
| **成果汇报** | `docs/achievements/b1_gating_and_diagnosis_achievement_report.md` |

**结论摘要**：G4-B1-v2 跨域 8.05% 为当前最优，优于 B1/G4；H2（Voting 谱更相似）已验证；H3/G5-B1 未证实；102621 仍适合 G4。

**遗留问题**：102621 上 v2 弱于 G4；091339 退化根因待查；场景自适应门控需新 plan。

---

## 10. 附录：方法代号与信道/模态融合对照

完整对照表见验证报告 [**附录 A**](../reports/b1_gating_and_diagnosis_report.md#附录-a方法代号与信道模态融合对照) 与成果汇报 [`docs/achievements/b1_gating_and_diagnosis_achievement_report.md`](../achievements/b1_gating_and_diagnosis_achievement_report.md#附录-方法代号与信道模态融合对照)。

**速查**（信道 → 模态 → 可选门控）：

| 代号 | 信道融合 | 模态融合 | 门控 |
|------|----------|----------|------|
| B1 Vote→Equal | 每模态 Vote | 三模态 Equal | — |
| B3 Vote→Top2 | 每模态 Vote | 三模态 Top2 | — |
| T0-V3 | Vote（仅 remote） | 无 | — |
| Modal top2 | Single-best per modal | Top2 | — |
| G4 | （候选内见上） | （候选内见上） | T0-V3 vs Modal → 分歧 Single |
| G4-B1-v2 | 同上 + B1 候选 | 同上 | 三候选中最近一对共识 |

> Systematic **B1**（`b1_vote_modal_equal`）≠ Baseline **B1 Uniform Remote**（`b1_uniform_remote`）。

---

## 给执行 Agent 的首条指令

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并严格执行：

`docs/plans/b1_gating_and_diagnosis_plan.md`

### 执行范围

**P0 必做**：

1. **G4-B1 联合门控（v1–v4）**：扩展 `consensus_gating.py` 的 G4 门控为三候选。实现 `gate_three_candidates()`。四种变体均在三场景上运行。
2. **诊断 D1（模态间频谱相似度）**：在 B1（Equal）和 B3（Top2）的每窗计算三模态频谱余弦相似度。对比 B1 窗、B3 窗和 Modal top2 窗的相似度分布。生成对比直方图。
3. **诊断 D2（091339 双峰性）**：在 091339 每窗计算 per-modal voting BPM 直方图的 bimodality score。将窗按双峰/单峰分组，对比 B1 error 分布。生成双峰窗 vs 单峰窗 error boxplot。
4. **诊断 D3（谱构造 ablation）**：实现 winning-bin 窄带谱（方案 A）和 top-K 平均谱（方案 C）。用三种方案分别运行 B1（Equal）和 B3（Top2），对比跨域 mean。
5. **G5-B1（091339 专项）**：实现 B1 + 双峰性门控，仅在 091339 上测试。

### 关键实现注意

- 门控 δ 沿用 G4 的 3 BPM。
- bimodality_score 可直接复用 `consensus_gating.compute_bimodality_score()`，输入改为 per-modal voting BPM 分布。
- 谱构造方案 A 的 winning bin = voting 直方图最高票 bin 的中心 BPM，窄带宽度 = ±2 BPM（含约 4 BPM 范围，在呼吸频带 6–21 BPM 中足够窄）。
- D1 的频谱余弦相似度使用 `np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))`，只计算呼吸频带内的频谱。
- D3 仅需在三场景的跨域 mean 上比较，不需要完整的窗级诊断。

执行完成后，请返回以下材料给 Claude/DeepSeek Review：

- `docs/reports/b1_gating_and_diagnosis_report.md`
- `outputs/reports/b1_gating_diagnosis_*.npy`
- `outputs/figures/b1_gating_*.png`、`outputs/figures/b1_diag_*.png`
- 关键脚本路径
- git diff 摘要
