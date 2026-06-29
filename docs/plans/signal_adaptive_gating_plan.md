# 信号级自适应门控与退化根因追查 — 实现计划（修订版）

> **来源**：
> - [B1 gating & diagnosis plan](../plans/b1_gating_and_diagnosis_plan.md) — B1（逐模态 Voting→等权谱融合）跨域 8.45%，但门控中加入 B1 作为第三候选在部分窗上是负贡献
> - [B1 gating & diagnosis report](../reports/b1_gating_and_diagnosis_report.md) — H2（模态频谱相似度）已验证、H3（双峰性根因）未证实
> - [Method evolution progress report](../achievements/method_evolution_progress_report.md) — §10.2 标注 G4 系列 fallback→Remote 缺乏理论依据
> - **修订动机**：G4 系列门控的「分歧→回退 Single Remote」预设 Remote 为全局最稳定变量，但 remote/local 质量是场景依赖的。本 plan 去除此假设，将门控 fallback 改为 per-window 质量驱动。
>
> **目标报告**：`docs/reports/signal_adaptive_gating_report.md`  
> **日期**：2026-06-08（初稿）→ 2026-06-08（修订）

---

## 1. 动机与背景

### 1.1 核心问题：门控需要 fallback，但不能预设 fallback 目标

B1 gating 实验（Phase 4）发现了两个事实：

1. **B1（逐模态 Voting → 三模态等权谱融合）跨域 8.45%，是当前最优的无门控方法**。
2. **将 B1 加入门控框架作为第三候选，某些窗上是负贡献**：三候选最近对共识门控（G4-B1-v2）跨域 8.05%，但 102621 上（5.50%）差于 G4（4.51%）。

**但 G4 的「分歧→回退 Single Remote」策略存在一个未经审视的前提**：它假设 Remote 幅值是全局最可信的单变量 fallback 目标。**这在物理上不成立**——BLE CS 的一次测量由两次独立互相测量组成：local 是本设备测对方，remote 是对方测本设备。两者只是同一 CS 交换的两个方向，**物理上完全对等**，不存在固定的质量差异（见 [[ble-cs-physical-background]]）。哪个更优完全取决于具体多径环境和设备位置。G4 在三个金属板场景下恰好有效，可能是因为这些场景下 Remote 恰好较优，而非策略本身可泛化。

**本 plan 的核心目标**：设计一种门控策略，其 fallback 目标由**每窗信号质量**动态决定，而非硬编码为某个特定模态或信道。

### 1.2 附加问题

- **B1 作为门控第三候选的失效条件**：在哪些窗上 B1 的 BPM 偏离 Voting 和 Modal Top2 的共识，成为「搅局者」？
- **091339 退化根因**：H3（双峰性）已在 D2 诊断中被推翻，需要另寻解释。

### 1.3 本 plan 定位

本 plan 聚焦三个目标：

1. **P1**：分析 B1 作为门控第三候选在 102621 上的窗级失效模式——不预设 G4 是正确的，仅研究 B1 的偏离条件。
2. **P2**：设计两种不硬编码 fallback 模态的信号级自适应门控（SA-v1 / SA-v2）。
3. **P3**：追查 091339 退化根因（η 质量假说，与 P1/P2 独立）。

### 1.4 核心假设

> **H1（B1 偏离条件）**：B1 的 BPM 显著偏离 Voting 与 Modal Top2 二者均值的窗，特征是 per-modal Voting 阶段 remote/local/phase 三模态 BPM 估计分歧大（即 Voting 直方图在三个模态上指向不同 BPM）。这导致 B1 的 Equal 谱融合被模态间矛盾污染。

> **H2（信号级自适应门控）**：可以在窗级计算三候选 BPM 的一致性评分（`triplet_consensus_score`）。当三者高度一致时加权平均最优；当 B1 明显偏离另外两者时，忽略 B1、仅用另外两者的共识（或取 per-window 最高置信度候选）；当三者全分歧时，取 per-window 最高 η·ρ 候选直接输出。

> **H3（091339 η 质量假说）**：091339 的退化与 per-tone η（呼吸频段能量比）系统性偏低相关。低 η 意味着 Voting 阶段 tone 级 BPM 估计噪声大，进而污染逐模态 Voting→谱的质量。如果成立，η 分布可作为 091339 类场景的预警指标。

---

## 2. 物理与变量

### 2.1 沿用变量

| 变量 | 是否使用 | 理由 |
|------|----------|------|
| `remote_amplitudes` | ✅ | Voting 和 B1 的模态之一；BLE CS 双向测量的本地端幅值，物理上与 local 对等 |
| `local_amplitudes` | ✅ | B1 三模态等权融合的模态之一；BLE CS 双向测量的远端幅值，物理上与 remote 对等 |
| `phases` | ✅ | B1 三模态等权融合的模态之一；两端 PCT 向量相乘后已抵消 LO 漂移，物理上可用 |
| `amplitudes`（总幅值） | ❌ | remote × local 的乘积，引入双方噪声，**无独立物理意义** |
| `η` per tone | ✅ | 诊断：tone 级呼吸频段能量比分布 |
| `ρ` per tone | ✅ | 诊断：tone 级谱峰峰度 |

> **物理依据**：BLE CS 中，remote/local 是同一 CS 交换的两个方向，物理上对等。单端相位含 LO 漂移不可用，只有 `phases`（两端 PCT 向量相乘后）可用。总幅值 `amplitudes` = remote × local 是双方噪声乘积，无物理意义。因此算法变量空间限定为 **remote_amplitudes / local_amplitudes / phases** 三种，三种应**对称对待**。

### 2.2 新增诊断信号

| 诊断量 | 含义 | 用途 |
|--------|------|------|
| `triplet_consensus_score` | 三候选 BPM 两两差异中，最近对距离 / 最远对距离 | H2：检测 B1 是否偏离其他两者 |
| `b1_deviation` | `|BPM_b1 − (BPM_vote + BPM_modal)/2|` | H1：量化 B1 偏离幅度 |
| `modal_vote_divergence` | `|BPM_vote − BPM_modal|` | 判断双候选基线是否已一致 |
| `per_modal_bpm_spread` | remote/local/phase 三模态各自 Voting 产出的 BPM 的标准差 | H1：模态间 Voting 分歧 |
| `mean_per_tone_eta` | 72 tone η 的均值 | H3：Voting 输入信号质量 |
| `eta_cv_per_tone` | 72 tone η 变异系数（std/mean） | 判断 tone 间质量差异 |

### 2.3 关键设计约束

> ⚠️ **门控 fallback 目标不得硬编码为特定模态（Remote/Local/Phase）或特定单信道**。所有 fallback 必须基于该窗的实时信号质量（η / η·ρ / 频谱峰度）动态选择。
>
> **物理依据**：BLE CS 的 remote 和 local 是同一 CS 交换的两个方向，物理上完全对等（见 §2.1）。不存在「Remote 天生更稳定」的物理理由——哪一方更优取决于具体多径环境。任何硬编码 fallback 的「成功」都可能是对特定测试场景的过拟合。Phase 同理——phase 的物理机制（LO 漂移已抵消）与幅值不同，不能预设 phase 总是比幅值好或差。

---

## 3. 算法设计

### 3.1 P1：B1 作为第三候选的窗级失效条件分析

**研究问题**（重新定位）：在 102621 上，B1 的 BPM 何时偏离 Voting 与 Modal Top2 的共识？这些窗有什么可量化的信号特征？

> 注意：P1 不预设「G4 是正确的」——它只研究 B1 的失效模式。G4 的 fallback→Remote 在 102621 上恰好有效，但这不代表那个 fallback 是正确答案。P1 的目标是找到描述 B1 偏离条件的信号特征，供 P2 门控使用。

```
对 102621 每窗：
  1. 获取三候选 BPM：
     bpm_vote  = T0-V3（远程单模态 Per-Tone η·ρ 投票）
     bpm_modal = Modal top2（逐模态最优信道→Top2 等权谱融合）
     bpm_b1    = B1（逐模态 Voting→三模态等权谱融合）
     bpm_gt    = ground truth

  2. 计算窗级指标：
     a. b1_deviation = |bpm_b1 − (bpm_vote + bpm_modal)/2|
     b. modal_vote_divergence = |bpm_vote − bpm_modal|
     c. per_modal_bpm_spread = std([bpm_remote_vote, bpm_local_vote, bpm_phase_vote])
        （三模态各自 per-modal Voting 产出的 BPM）
     d. error_b1 = |bpm_b1 − bpm_gt|
     e. error_pair = |avg(bpm_vote, bpm_modal) − bpm_gt|  （双候选平均的 error）

  3. 定义窗类型：
     - "B1 搅局窗"：b1_deviation > 3 BPM 且 modal_vote_divergence ≤ 3 BPM
       （双候选已共识，但 B1 偏离）
     - "B1 改善窗"：error_b1 < error_pair - 0.5 BPM
       （B1 的加入改善了双候选平均）
     - "三者分散窗"：min pairwise diff > 3 BPM
       （三个候选全分歧）

  4. 汇总统计：
     - 各类型窗占比
     - "B1 搅局窗" 上的 per_modal_bpm_spread 分布 vs "B1 改善窗"
     - "三者分散窗" 上各候选的 η·ρ 置信度对比
```

**预期（如果 H1 成立）**：「B1 搅局窗」上 `per_modal_bpm_spread` 显著高于「B1 改善窗」——即 remote/local/phase 三模态 Voting 指向不同 BPM 时，B1 的 Equal 谱融合被矛盾信息污染，产出的 BPM 偏离 Voting/Modal 共识。

**输出**：`b1_deviation` 与 `per_modal_bpm_spread` 的散点图 + 窗类型分布饼图 + 特征汇总表。

### 3.2 P2：信号级自适应门控（去硬编码版）

#### 3.2.1 新增 baseline：per-window best-single-channel

在设计门控前，需要先建立一个**可泛化的 fallback 候选池**：

```
每窗计算以下单信道 BPM（使用 η·ρ 选道）：
  bpm_single_remote = Single-best channel（remote 幅值，max-η·ρ 选道）
  bpm_single_local  = Single-best channel（local 幅值，max-η·ρ 选道）
  bpm_single_phase  = Single-best channel（phase，max-η·ρ 选道）

per-window best-single BPM = 上述三者中 η·ρ 最高者对应的 BPM
简称 bpm_best_single
```

> 注意：`bpm_single_remote` 就是已有的 B0（Single Remote），但本 plan 不预设它是最优 fallback。哪个单信道最好由每窗 η·ρ 决定。

#### 3.2.2 SA-v1：三候选一致性门控 + per-window best-single fallback

```
候选池：
  bpm_vote       = T0-V3（远程单模态 Per-Tone η·ρ 投票）
  bpm_modal      = Modal top2（逐模态最优信道→Top2 等权谱融合）
  bpm_b1         = B1（逐模态 Voting→三模态等权谱融合）
  bpm_best_single = per-window 最高 η·ρ 单信道 BPM

每窗门控逻辑：
  pair_diffs = sort([|vote−modal|, |vote−b1|, |modal−b1|])
  consensus_score = pair_diffs[0] / (pair_diffs[2] + ε)  # ∈ [0,1]

  if consensus_score > 0.4（存在接近对，非全离散）:
      最近对 = argmin pair_diffs
      若最近对的两候选 BPM 差 ≤ 3 BPM：
         若 B1 在最近对中 → 三候选加权平均（1:1:1）
         若 B1 不在最近对中 → 仅最近对两候选平均，忽略 B1
      否则 → 取最近对中 η·ρ 更高者
  else（三者全分散——全分歧）:
      # 关键改动：不再硬编码 fallback 目标
      取候选池中 per-window η·ρ 置信度最高者直接输出
      （候选池含 bpm_vote / bpm_modal / bpm_b1 / bpm_best_single）
```

**与旧 SA-v1 的关键区别**：
- 旧：「B1 是搅局者 → G4 模式 → 分歧回退 Single Remote」
- 新：「B1 偏离 + 另两者接近 → 信任另两者；全分歧 → per-window 最高置信度候选」

#### 3.2.3 SA-v2：η 质量感知门控

```
每窗：
  计算 per-tone η 统计量（在 remote 72 tone 上）：
    mean_eta = mean(72 tone η)
    eta_cv   = std(η) / mean_eta

  if mean_eta > τ_high 且 eta_cv < cv_thresh（信号质量好，tone 间一致）:
      信任 B1 直接输出  # Voting 输入质量好，三模态 Equal 融合应可靠

  elif mean_eta > τ_low（信号质量可接受）:
      使用 SA-v1 三候选一致性门控  # 包含 B1 但带 fallback 保护

  else（信号质量差——tone 级 Voting 噪声大）:
      # 关键改动：不默认回退到 Single Remote
      使用 bpm_best_single 直接输出
      （该窗上 η·ρ 最高的单信道，可能是 remote/local/phase 任一）
```

> ⚠️ **当前简化**：per-tone η 仅在 remote 上计算。由于 remote/local 物理对等（§2.1），一个更全面的方案应在 remote/local/phase 三者上分别计算 per-tone η，取最大值作为质量判断依据——因为 B1 使用三模态 Equal 融合，只要有一个模态信号质量好，B1 就可能仍然可靠。当前简化版本可能在 remote 差但 local/phase 好的窗上过度保守。此问题留待实验结果判断是否需要修正。

**阈值标定**（在 102621 上初步标定，标注 `[待优化]`）：
- τ_high = 102621 上 B1 error 最低的 1/3 窗的 mean_η 下四分位数
- τ_low = 102621 上 mean_η 中位数
- cv_thresh = 102621 上 eta_cv 中位数
- 标定方式：hold-one-scene-out（在 102621 标定，在 091339/095806 验证）

#### 3.2.4 消融变体

| 变体 | 说明 | 验证问题 |
|------|------|----------|
| **SA-v1** | 三候选一致性 + best-single fallback | 主方案 |
| **SA-v1-noB1** | 同 SA-v1 但候选池移除 B1（仅 vote + modal + best_single） | B1 的加入是否在  某些窗始终是负贡献？ |
| **SA-v2** | η 质量感知 + best-single fallback | 备选方案 |
| **SA-v1+SingleRemote** | SA-v1 但全分歧→Single Remote（**仅作消融对照**） |  量化「hardcoded fallback Remote」vs「best-single」的差异 |

> ⚠️ SA-v1+SingleRemote 对标旧 G4-B1-v2 的 fallback 逻辑，**仅作为消融证据**，不作为推荐方法。

### 3.3 P3：091339 η 质量诊断（与 P1/P2 独立）

```
对三场景每窗：
  1. 计算 per-tone η 统计量（mean, std, cv, p10, p50, p90）
     （分别在 remote 72 tone、local 72 tone、phase 72 tone 上计算，
       在窗首帧计算，不滑动。
       同时计算三变量 max-η = max(mean_η_remote, mean_η_local, mean_η_phase)）
  2. 三场景全局对比：
     箱线图：mean_η per scene / eta_cv per scene（三变量分开展示 + max-η）
  3. 091339 内部分析：
     将窗按 max-η 分为低/中/高三组（等频分箱）
     对比各组 B1 error mean/std
     将窗按 eta_cv 分为高变异/低变异两组
     对比各组 B1 error mean/std
  4. 交叉检查：
     - 091339 低 η 窗上 bpm_best_single 是否优于 B1？
     - 091339 低 η 窗的 per_modal_bpm_spread 是否更高？
```

**预期（如果 H3 成立）**：091339 上 low max-η 窗占比 > 095806/102621，且 B1 error 集中在 low max-η 窗。使用 max-η（而非仅 remote η）是因为 B1 使用三模态 Equal 融合——只要有一个模态信号质量好，B1 就可能可靠；反之，三者都差才是真正的退化条件。

---

## 4. Baseline 对比

### 4.1 必须复现/引用的 baseline

| 方法 | 描述性名称 | 跨域 mean | 来源 |
|------|-----------|-----------|------|
| B1 | 逐模态 Voting → 三模态等权谱融合 | 8.45% | systematic_fusion |
| T0-V3 | 远程单模态 Per-Tone η·ρ 投票 | 9.20% | voting_fusion |
| Modal top2 | 逐模态最优信道（max-η 选道）→ Top2 等权谱融合 | 9.45% | Plan2 |
| **Single Remote** | 单信道 Remote 幅值（max-η 选道） | 10.45% | P0 baseline |
| **Single Local** | 单信道 Local 幅值（max-η 选道） | `[待测]` | **新增 baseline** |
| **Single Phase** | 单信道 Phase（max-η 选道） | `[待测]` | **新增 baseline** |
| **Best Single** | per-window 最高 η·ρ 单信道（remote/local/phase 动态选择） | `[待测]` | **新增 baseline** |

> 旧 plan 中将 G4（8.65%）和 G4-B1-v2（8.05%）列为 baseline。本 plan **不再将其作为对标目标**，原因见 §2.3。G4 系列的结果将在 §5 的消融分析中引用作为参考值，但不作为成功标准。

### 4.2 待测方法

| ID | 方法 | 说明 |
|----|------|------|
| **SA-v1** | 三候选一致性门控 + per-window best-single fallback | 主方案 |
| **SA-v1-noB1** | 同 SA-v1 但候选池无 B1 | 消融：B1 是否始终负贡献？ |
| **SA-v2** | η 质量感知门控（三级 fallback→best-single） | 备选方案 |
| **SA-v1+SingleRemote** | SA-v1 但全分歧→Single Remote | 消融对照：量化硬编码 Remote 的偏差 |

### 4.3 预期相对关系

| 对比 | 预期 | 理由 |
|------|------|------|
| SA-v1 vs B1（全局） | 略优 | 在 B1 偏离窗上有 fallback 保护 |
| SA-v1 vs B1（102621） | 接近 | B1 在 102621 某些窗失效，SA-v1 应绕过 |
| SA-v1 vs Best Single | 优于 | 共识窗上多候选平均优于单候选 |
| SA-v2 vs SA-v1（091339） | 不确定 | 取决于 η 质量在 091339 上是否确实是退化主因 |
| Single Remote vs Single Local（三场景） | 场景依赖 | remote/local 质量谁更优取决于场景——**预期跨场景不一致** |

---

## 5. 评估设计

### 5.1 场景

| 场景 | 用途 |
|------|------|
| `cs_091339` | P3 诊断主场景 + SA 验证（B1 退化场景） |
| `cs_095806` | SA 验证（B1 优势场景保持） |
| `cs_102621` | P1 追查 + SA 验证（B1 偏离模式检测） |

### 5.2 指标

| 指标 | 说明 |
|------|------|
| 分段 BPM err% mean / std | 主指标 |
| 跨域 mean | 三场景平均 |
| **B1 搅局窗占比**（102621） | P1：`b1_deviation > 3` 且 `modal_vote_divergence ≤ 3` 的窗比例 |
| **per_modal_bpm_spread** | P1/H1：三模态 Voting BPM 的标准差 |
| **triplet_consensus_score** 分布 | P2：三候选两两差异的模式 |
| **SA-v1 门控决策分布** | 各路径被选中的窗比例（最近对平均 / 最高置信度单候选 / …） |
| **per-tone η 分布（mean/std/CV）** | P3：三场景对比 |
| **Single Remote/Local/Phase 三场景各自 mean** | 验证 remote 并非全局最稳定的单变量 |

### 5.3 成功标准

| 级别 | 条件 |
|------|------|
| **理想** | SA-v1 跨域 mean < **7.8%**，且 091339 < 12%、102621 < 5.5% |
| **良好** | SA-v1 跨域 mean < **8.0%**，且三场景均不差于 B1 + 0.5pp，且 102621 不差于 Best Single |
| **最低** | 至少一个 SA 变体跨域 mean < B1（8.45%），且 P1 产出 B1 偏离条件的明确信号特征 |
| **P3 诊断成功** | 091339 退化与 η 质量相关的统计证据（low-η 窗 B1 error > high-η 窗 B1 error） |
| **失败** | 无 SA 变体跨域 < 8.45%，且 P1 无法找到可迁移信号特征 |

### 5.4 注意

- 旧 plan 的成功标准包含「102621 ≤ G4 + 0.3pp」。本 plan **移除此条**——不应以硬编码 fallback 的策略作为标尺。
- 新增对标：「SA-v1 vs Best Single」——验证门控的共识窗收益是否足以覆盖全分歧窗的 fallback 成本。

---

## 6. 实现要点

### 6.1 文件规划

| 类型 | 路径 | 说明 |
|------|------|------|
| 实验脚本 | `notebooks/scripts/chFusion_signal_adaptive_gating.py` | 主脚本 |
| 可复用模块（新增） | `src/ble_analysis/signal_adaptive_gating.py` | P2 门控逻辑 |
| 可复用模块（扩展） | `src/ble_analysis/consensus_gating.py` | 新增 `compute_triplet_consensus()`、`compute_per_tone_eta_stats()` |

### 6.2 复用 API

```python
from ble_analysis.systematic_fusion import (
    per_modal_voting_spectrum,
    modal_fusion_from_spectra,
    run_systematic_fusion_benchmark,
)
from ble_analysis.consensus_gating import (
    _gate_one_window_g4,
    gate_three_candidates,
)
from ble_analysis.chfusion import (
    _energy_ratio,  # per-tone η
    ChFusionConfig,
)
```

### 6.3 关键新增函数签名

```python
def compute_per_window_best_single(
    ch_list: List, ch_map: Dict,
    st: int, end: int, fs: float, cfg: ChFusionConfig,
) -> Tuple[float, str]:
    """返回 (bpm, modality_label)，在 remote/local/phase 中选 η·ρ 最高的单信道 BPM."""
    ...

def compute_per_modal_voting_bpms(
    ch_list: List, ch_map: Dict,
    st: int, end: int, fs: float, cfg: ChFusionConfig,
) -> Dict[str, float]:
    """返回 {"remote": bpm_r, "local": bpm_l, "phase": bpm_p}，三模态各自 per-modal Voting BPM."""
    ...

def compute_triplet_consensus_score(
    bpm_vote: float, bpm_modal: float, bpm_b1: float,
) -> float:
    """返回三候选一致性评分 ∈ [0,1]；接近 1 = 三者一致，接近 0 = 一对接近但第三偏离."""
    diffs = sorted([
        abs(bpm_vote - bpm_modal),
        abs(bpm_vote - bpm_b1),
        abs(bpm_modal - bpm_b1),
    ])
    return diffs[0] / (diffs[2] + 1e-6)

def compute_per_tone_eta_stats(
    ch_list: List, ch_map: Dict, variable: str,
    st: int, end: int, fs: float, cfg: ChFusionConfig,
) -> Dict[str, float]:
    """返回该窗该变量 72 tone η 的 {mean, std, cv, p10, p50, p90}."""
    ...

def gate_signal_adaptive(
    bpm_vote: float, bpm_modal: float, bpm_b1: float,
    bpm_best_single: float,
    best_single_label: str,  # "remote" | "local" | "phase"
    eta_stats: Dict[str, float],
    delta: float = 3.0,
    variant: str = "v1",  # "v1" | "v1-noB1" | "v2"
) -> Tuple[float, str, str]:
    """信号级自适应门控。
    返回 (bpm, decision_tag, fallback_modality).
    decision_tag ∈ {"triple_consensus", "pair_consensus", "best_single_fallback", "b1_direct", ...}
    """
    ...

def run_p1_b1_deviation_analysis(
    results_b1: Dict,
    results_vote: Dict,
    results_modal: Dict,
    scenario: str,
) -> Dict:
    """P1：分析 B1 偏离 Voting/Modal 共识的窗级特征."""
    ...
```

### 6.4 不做的事

- 不新增场景 JSON
- 不改变滑窗参数或滤波链
- 不探索新信道/模态融合策略
- 不对 τ_high/τ_low/cv_thresh 做 exhaustive grid search（仅手动标定）
- **不**使用场景标签做任何 if-else 分支
- **不**在 fallback 中硬编码任何特定模态（remote/local/phase）
- **不**以 G4 或 G4-B1-v2 作为 success criteria 的标尺

### 6.5 P1 追查的实现注意

P1 的核心输入是三个候选方法在 102621 上的**窗级 BPM 序列**（与 GT 对齐）。需要：
- 运行 B1 在 102621 上，保存窗级 BPM 和 per-modal Voting BPM
- 运行 T0-V3 在 102621 上，保存窗级 BPM
- 运行 Modal top2 在 102621 上，保存窗级 BPM
- 加载已有 GT（ground truth segments）

这些运行在 P2/P3 的 benchmark 中自然覆盖，P1 是纯后分析，不需要额外 benchmark。

---

## 7. 预期产出

| 产出 | 路径 |
|------|------|
| 验证报告 | `docs/reports/signal_adaptive_gating_report.md` |
| 数值结果 | `outputs/reports/signal_adaptive_gating_*.npy` |
| 跨域汇总 | `outputs/reports/signal_adaptive_gating_cross_domain.npy` |
| P1 B1 偏离 vs per_modal_spread 散点图 | `outputs/figures/sa_p1_b1_deviation_scatter.png` |
| P1 窗类型分布饼图 | `outputs/figures/sa_p1_window_type_pie.png` |
| SA 跨域排行榜 | `outputs/figures/sa_leaderboard.png` |
| SA 门控决策 Sankey/饼图 | `outputs/figures/sa_decision_distribution.png` |
| SA-v1+SingleRemote 消融对比 | `outputs/figures/sa_ablation_fallback_modality.png` |
| P3 三场景 per-tone η 分布对比 | `outputs/figures/sa_p3_eta_distribution.png` |
| P3 091339 η 分组 B1 error 对比 | `outputs/figures/sa_p3_eta_vs_error.png` |
| Single Remote/Local/Phase 三场景柱状图 | `outputs/figures/sa_single_modality_comparison.png` |

---

## 8. 风险与保留问题

### 8.1 算法风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| SA-v1 移除硬编码 Remote fallback 后跨域劣于旧 G4-B1-v2（8.05%） | 中 | 劣于硬编码 fallback ≠ 方法更差；SA-v1+SingleRemote 消融可量化差异。若 SA-v1 劣于 B1（8.45%），说明三候选门控本身有问题 |
| per-window best-single 中 remote 仍然被选中最频繁 | 低 | 这本身是信息——说明这三个场景下 remote 确实最稳定，但不改变 fallback 应动态选择的原则 |
| P1 找不到 B1 偏离的可迁移信号特征 | 高 | 如果 per_modal_bpm_spread 无法区分 B1 搅局窗和改善窗，SA-v1 的三候选一致性评分可能无效——此时 SA-v1-noB1 作为备选 |
| τ 阈值跨场景泛化 | 中 | SA-v1 无阈值（仅 δ=3 BPM consensus threshold）；SA-v2 阈值在 hold-one-scene-out 下标定 |
| Single Local / Single Phase 在某些场景下极差（> 30%） | 低 | per-window η·ρ 选道会自然避开——这正是动态选择的优势 |

### 8.2 保留问题

| ID | 问题 | 备注 |
|----|------|------|
| Q1 | per_modal_bpm_spread 的物理含义是什么——它反映多径差异还是 tone 级噪声？ | `[待确认]` — 可能需要在受控仿真中验证 |
| Q2 | 如果 P3 确认 η 是 091339 退化根因，是否需要回到信道选择层改进（而非仅门控层）？ | `[待确认]` — 可能是下一轮 plan 的内容 |
| Q3 | per-window best-single 的 remote/local/phase 选择比例在不同场景间是否有显著差异？ | 若能显示 remote 选中率 < 80%，则直接证明硬编码 Remote fallback 确实有问题 |
| Q4 | SA-v1 的 consensus_score 阈值（0.4）和 pair distance 阈值（3 BPM）是否需要跨场景自适应？ | `[待确认]` — 先固定，观察跨场景分布 |
| Q5 | SA-v2 仅用 remote per-tone η 是否过于保守？是否应改用三变量 max-η（见 §3.2.3 简化标注）？ | `[待确认]` — 先跑 remote-only 版，若 SA-v2 劣于 SA-v1 且 fallback 比例过高，下一轮改用 max-η |

---

## 9. 验证状态

状态：**已完成**

| 项目 | 实际产出 |
|------|----------|
| **验证状态** | 已完成（P1/P2/P3 全部执行；无 SA 变体跨域 < B1） |
| 报告 | `docs/reports/signal_adaptive_gating_report.md` |
| 脚本 | `notebooks/scripts/chFusion_signal_adaptive_gating.py` |
| 模块 | `src/ble_analysis/signal_adaptive_gating.py` |
| 跨域结果 | SA-v2 10.66% > B1 8.45%；SA-v1 11.42% |
| 图表 | `outputs/figures/sa_*.png` |

**结论摘要**：去除硬编码 Remote fallback 的 SA 门控未能超越 B1；P1 在 102621 上 b1_disruptor=0%（H1 未证实）；P3 η 分组 error 非单调（H3 部分/未证实）；best-single 选道跨场景显著不同（验证 remote 非全局最优）。

---

## 给执行 Agent 的首条指令

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并严格执行：

`docs/plans/signal_adaptive_gating_plan.md`

### 执行范围

**新增 baseline（必做）**：Single Remote / Single Local / Single Phase / Best Single（per-window 动态选道），三场景运行。这是验证「remote 不是全局最稳定变量」的经验证据。

**P1 必做（轻量）**：在 P2 的 benchmark 运行中自然产出 B1、T0-V3、Modal top2 在 102621 上的窗级 BPM 序列。后分析 B1 偏离条件。

**P2 必做**：实现 SA-v1 / SA-v1-noB1 / SA-v2 / SA-v1+SingleRemote（消融），三场景运行。

**P3 必做**：三场景 per-tone η 分布对比（remote/local/phase 三者分别 + max-η）+ 091339 η 分组 B1 error 分析。

### 关键实现注意

- **严禁**：任何基于场景标签的 if-else 分支。门控仅能使用窗级信号特征
- **严禁**：在 fallback 中硬编码 `variable == "remote_amplitudes"` 或 `modality == "remote"`
- `bpm_best_single` 的计算：对 remote/local/phase 各做 Single-best（max-η·ρ 选道），取 η·ρ 最高者
- `triplet_consensus_score` = 最近对距离 / 最远对距离；阈值暂设 0.4
- SA-v2 的 τ_high/τ_low/cv_thresh 在 102621 上标定（详见 §3.2.3）
- P3 的 per-tone η 统计需在 remote/local/phase 三变量上分别计算，并额外计算 max-η（三变量取最大），仅需在每窗首帧计算一次（不滑动）

### 提交给 Claude/DeepSeek Review 的材料

- `docs/reports/signal_adaptive_gating_report.md`
- `outputs/reports/signal_adaptive_gating_*.npy`
- `outputs/figures/sa_*.png`
- 关键脚本路径
- git diff 摘要
