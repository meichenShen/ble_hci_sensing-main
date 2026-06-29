# Consensus Gating — 窗级共识门控融合计划

> **来源**：
> - Voting Fusion Review（Deng et al. voting 验证结论：T0-V3 跨域 9.20% 略优但 091339 退化）
> - PCA plan Q3（PCA-Modal 与 Plan2 谱峰一致性门控）
> - [待文献调研后补充] TR-BREATH [7] / Wi-Breath [6] / Bimodal CSI [10]
>
> **目标报告**：`docs/reports/voting_gating_report.md`  
> **日期**：2026-06-07（初稿，文献调研完成后补充 §1.4 / §3.4 / §4.3）  
> **验证状态**：已完成（G1–G6）

---

## 1. 动机与背景

### 1.1 问题

两个独立的实验线程揭露了同一个模式：

| 线程 | 最优方法 | 跨域 mean | 091339 | 095806 | 102621 |
|------|----------|-----------|--------|--------|--------|
| Plan2 Modal | Modal top2 equal | **9.45%** | 13.04% | 10.61% | **4.69%** |
| Voting Fusion | T0-V3 η·ρ per-tone voting | **9.20%** | 13.77% | **6.84%** | 6.99% |
| PCA-Modal | PCA-Modal3 η/ch-η | 10.92% | 19.54% | 7.51% | 5.72% |

**关键观察**：没有单一方法在所有场景中都是最优的。

- Modal top2 在 091339 和 102621 上最强，但在 095806 上被 T0-V3 大幅超越（10.61% vs 6.84%）
- T0-V3 在 095806 上极强，但在 091339 上比 Modal 差
- PCA-Modal3 在 095806 上优于 Modal（7.51% vs 10.61%），在 091339 上严重退化（19.54%）

这说明不同方法的优劣是**窗级条件性**的——某些窗适合 voting（per-tone 多数派明确），某些窗适合谱融合（per-tone 分散但谱峰收敛）。

**2026-06-07 更新：频率选择性衰落的直接证据。** Voting 增强诊断（commit `7330738`）揭示了一个关键的物理机制：

- **Tone 内时序高度稳定**：同一 tone 在相邻窗之间的 BPM 变化仅 ~0.40 BPM（72 tone × 39 窗的均值）。每个 tone 的 BPM 估计在时间上是自洽的——它持续跟踪该频点上多径信道赋予的主导周期成分。
- **Tone 间系统性分化**：不同 tone 形成多个不相干的 BPM 簇（如 8–10、14、18–20 BPM），这不是随机噪声，而是**频率选择性衰落**的直接表现——某些频点的呼吸路径增益高（BPM ≈ GT），某些频点的呼吸路径被多径抵消（BPM ≈ 半频），某些频点被其他周期信号主导。

这从根本上改变了门控的设计思路：不能只依赖 voting 内部置信度（τ），因为"稳定的错误簇"也可以达到高 τ。需要度量 **tone 之间的一致性结构**——如果大多数 tone 的 BPM 时间序列聚类在单个值附近，voting 可靠；如果形成多个大小相当的簇，应退回谱融合。

### 1.2 核心假设

> **H1**：在 095806 上 T0-V3 优于 Modal top2 的那些窗口，与 Modal top2 在 091339 上优于 T0-V3 的那些窗口，存在**可检测的信号特征差异**（如 voting confidence、谱峰一致性、η 分布偏度）。如果能检测这些特征，就可以在窗口级别动态选择方法。

> **H2**：窗级门控（gating）可以通过跨方法共识实现——当两个结构不同的方法（如 voting 和谱融合）给出相近 BPM 时，结果可信；当结果分歧时，选择历史可靠性更高的方法作为 fallback。

### 1.3 与现有工作的关系

- **PCA plan Q3** 提出了完全一致的思路：*"窗级 phase/remote/local 峰频差 > 阈值时退回 Single remote"*。本 plan 将这一概念从 PCA/Modal 之间的门控，扩展到 **Voting / Modal / PCA-Modal 三者之间的通用门控框架**。
- **Deng et al. 论文** 的 voting threshold τ 本质上是一种"单方法内部门控"——当票数不足时标记 low-conf。本 plan 将其扩展为**跨方法门控**——不仅看 voting 内部置信度，还看 voting 与 Modal 的外部一致性。
- **Voting 增强诊断（2026-06-07）** 发现了频率选择性衰落的直接证据：tone 内 BPM 时序高度稳定（|ΔBPM| ≈ 0.40），tone 间系统性分化。这意味着门控信号应包含 **tone 间一致性结构**（双峰性检测、聚类 coherence），而非仅看投票票数。由此衍生出 G5（双峰性门控）和 G6（persistence-filtered voting）。
- **[待文献调研后补充]** TR-BREATH [7] / Wi-Breath [6] / Bimodal CSI [10]

### 1.4 文献调研衔接（预留）

> `[待文献调研后补充]`：
> - TR-BREATH [7] 的 TRRS 指标是否可作为门控特征？
> - Wi-Breath [6] 的 SVM 置信度是否优于 η/ρ threshold？
> - Bimodal CSI [10] 的体动检测器是否可作为"切换到 robust 方法"的门控信号？

---

## 2. 物理与变量

### 2.1 可用观测量

| 变量 | 是否使用 | 理由 |
|------|----------|------|
| `remote_amplitudes` | ✅ | T0-V3 的主输入；Modal top2 的参与模态之一 |
| `local_amplitudes` | ✅ | Modal top2 的参与模态 |
| `phases` | ✅ | Modal top2 的参与模态 |
| `amplitudes`（总幅值） | ❌ | 保持与现有 leaderboard 一致；门控概念验证阶段不引入新变量 |

### 2.2 门控信号来源

门控在**窗口级别**运行，每窗可用的信号包括：

| 信号 | 来源方法 | 含义 |
|------|----------|------|
| `BPM_vote` | T0-V3 | per-tone η·ρ 直方图投票结果 |
| `BPM_modal` | Modal top2 | top2 模态谱融合寻峰结果 |
| `BPM_single` | Single Remote | max-η tone 独立 BPM（robust fallback） |
| `conf_vote` | T0-V3 | voting 最高 bin 加权票数占比 |
| `win_mass_vote` | T0-V3 | 最高 bin 的绝对权重和 |
| `peak_dist` | 跨方法 | `|BPM_vote - BPM_modal|` |
| `η_vote_max` | T0-V3 | 参与 voting 的 tone 中最高 η |
| `ρ_vote_mean` | T0-v3 | 参与 voting 的 tone 的平均 ρ |
| `modal_eta_gap` | Modal top2 | top2 模态的 η 差距（top1 η − top2 η） |
| `bimodality_score` | T0-V3 | BPM 分布的双峰性：最高 bin 与第二高峰 bin 的票数比。低值 = 多簇竞争、voting 不可靠 |
| `tone_persistence` | per-tone 时序 | 每个 tone 的跨窗 BPM 平均 L1 步长（`mean_step_L1`）。高 persistence = tone 稳定跟踪某个周期成分；低 persistence = 噪声 tone，投票前剔除 |
| `n_coherent_tones` | T0-V3 | persistence ≤ 阈值且 BPM 在 ±2 BPM 内聚类的 tone 数量。少 = 可靠选民不足 |
| [待文献调研后补充] | TRRS | TR-BREATH 谐振强度指标 |

---

## 3. 算法步骤

### 3.1 公共前置

```
数据源：BLE CS 72 tone
分段：config/scenarios/cs_*.json
滤波：median → highpass → bandpass（与 Plan2 相同）
滑窗：20 s / 1 s 步
呼吸带：0.1–0.35 Hz
```

### 3.2 门控框架

```
对每窗:
  1. 并行计算三个方法的 BPM:
     BPM_vote  ← T0-V3(remote_amplitudes, 72 tone)   # η·ρ 加权直方图投票
     BPM_modal ← Modal top2(remote, local, phase)     # top2 模态谱融合
     BPM_single ← Single Remote(max-η tone)           # robust fallback

  2. 计算门控信号:
     peak_dist = |BPM_vote - BPM_modal|
     conf_vote = winning_bin_mass / total_weight      # 0~1
     consensus = (peak_dist ≤ δ)                       # δ = 门控容忍度, BPM

  3. 门控决策:
     if consensus and conf_vote ≥ τ_hi:
       BPM_final = weighted_average(BPM_vote, BPM_modal)  # 二者一致且高质量
     elif consensus and conf_vote < τ_hi:
       BPM_final = BPM_modal                              # 一致但 voting 低质量 → 信 Modal
     elif not consensus and conf_vote ≥ τ_hi:
       BPM_final = BPM_vote                               # voting 高置信但分歧 → 信 voting（095806 模式）
     else:
       BPM_final = BPM_single                             # 都不好 → fallback
```

### 3.3 门控策略变体

| 策略 | δ (BPM) | τ_hi | 说明 |
|------|---------|------|------|
| **G1 — 简单共识** | 3.0 | 0.30 | voting 和 modal 在 3 BPM 内一致 → 取平均 |
| **G2 — 置信度优先** | 2.0 | 0.35 | 更严格的门控；分歧时用 conf 更高的方法 |
| **G3 — 自适应** | 2.0 ~ 5.0 | η-dependent | δ 随 max(η_vote, η_modal) 缩放：η 高时容忍度小 |
| **G4 — Single fallback** | — | — | 只在 voting 与 modal 分歧时退回 Single；一致时取 voting+modal 平均 |

### 3.4 基于频率选择性衰落的新门控策略（G5–G6）

以下策略直接利用增强诊断揭示的"tone 内时序稳定 + tone 间分化"机制，**不需要文献调研即可实现**。

#### G5 — 双峰性门控（Bimodality Gating）

```
对每窗:
  1. 计算 72 tone 的 per-tone BPM 估计（与 T0-V3 相同）
  2. 在 [6, 30] BPM × 1 BPM bin 上做直方图 → 得到每个 bin 的 η·ρ 加权票数
  3. 找最高 bin (peak_1) 和第二高 bin (peak_2)，二者在 BPM 轴上相距 ≥ 2 bin
  4. bimodality_score = peak_2_mass / peak_1_mass    # 0~1，越高越双峰

  5. 门控决策:
     if bimodality_score < 0.5:                       # 单峰主导 → voting 可靠
       BPM_final = T0-V3 投票结果
     elif bimodality_score ≥ 0.5 and peak_1_mass / total > 0.25:
       # 明显双峰 → 检查 peak_1 是否接近 Modal top2 的结果
       if |bin_center(peak_1) - BPM_modal| ≤ 2:
         BPM_final = weighted_avg(peak_1, BPM_modal)  # 主峰与 modal 一致
       else:
         BPM_final = BPM_modal                         # 双峰竞争 → 不信 voting
     else:
       BPM_final = BPM_single                          # 高度分散 → fallback
```

**与 G1–G4 的关键区别**：G5 不依赖 τ（票数阈值），而是看"有没有第二股势力"——如果两个 BPM 簇大小相当，无论绝对票数多少，voting 都不可靠。

#### G6 — Persistence-Filtered Voting（稳定性筛选投票）

```
对每窗:
  1. 如果有前一窗的 per-tone persistence 数据:
     - 剔除 mean_step_L1 > 阈值（如 2.0 BPM）的 tone
     → 这些 tone 在窗间 BPM 跳变剧烈，是噪声选民
  2. 对剩余 "稳定 tone" 做 T0-V3 voting
  3. 如果稳定 tone 数 < 12（太少）:
     → 退回 BPM_modal

预计算 persistence:
  从 voting 结果中提取 bpm_per_tone_per_window 矩阵 (n_win × 72)
  对每个 tone: mean_step_L1 = mean(|BPM[t+1] - BPM[t]|) across all windows
```

**与 G1–G4 的关键区别**：G6 在 voting 之前做预处理，而不是在 voting 之后做门控。它利用时域稳定性作为一个新的 tone 质量维度，与 η（频域能量）、ρ（频域峰度）互补。

#### 待文献调研后追加

> `[待文献调研后补充]`：
>
> - **G7 — TRRS 门控**：用 TR-BREATH [7] 的 TRRS 替代/补充 conf_vote 作为门控信号
> - **G8 — SVM 窗级质量分类器**：用 Wi-Breath [6] 的 SVM 特征工程思路训练窗级 quality classifier
> - **G9 — Bimodal CSI 体动检测器**：借鉴 [10] 的 motion detection 作为 "切换到 robust fallback" 的触发器

### 3.5 共识门控 vs 无门控的预期差异

```
无门控 T0-V3:
  091339: 段 3 某个窗 → per-tone BPM 多峰 → voting 选 8 BPM (错) → 误差大
  095806: 某个窗 → per-tone BPM 集中在 GT 附近 → voting 选正确 → 误差小

有门控:
  091339: 同窗 → voting 选 8, modal 选 14 → peak_dist = 6 > δ → conf_vote 可能低
         → 门控退回 Single 或 Modal → 避免 8 BPM 错误
  095806: 同窗 → voting 选 14, modal 选 14 → consensus → 取平均 → 保持优势
```

### 3.6 BPM 加权平均策略

当 voting 和 modal 共识（peak_dist ≤ δ）时：

```
BPM_final = (w_vote * BPM_vote + w_modal * BPM_modal) / (w_vote + w_modal)

其中:
  w_vote = conf_vote · max(η_vote_max, 0.05)
  w_modal = 1.0  # modal 不产出 conf，暂固定
```

---

## 4. Baseline 对比

### 4.1 必跑方法

| ID | 说明 | 来源 |
|----|------|------|
| B0 | Single Remote | chfusion baseline |
| B1 | Uniform Remote | chfusion baseline |
| B2 | Modal top2 equal | 当前跨域最优 baseline |
| B3 | Modal η-weight | Plan2 baseline |
| T0-V3 | Per-Tone η·ρ voting | Voting plan 最优 |
| **G1** | 简单共识门控（δ=3, τ_hi=0.30） | 本 plan §3.3 |
| **G2** | 置信度优先门控（δ=2, τ_hi=0.35） | 本 plan §3.3 |
| **G3** | 自适应门控 | 本 plan §3.3 |
| **G4** | Simple consensus + Single fallback | 本 plan §3.3 |
| **G5** | 双峰性门控（bimodality gating） | 本 plan §3.4 — 基于频率选择性衰落诊断 |
| **G6** | Persistence-filtered voting | 本 plan §3.4 — tone 时序稳定性筛选 |

### 4.2 预期相对关系

| 对比 | 预期 | 理由 |
|------|------|------|
| G1 vs T0-V3 | 091339 改善、095806 略降 | 门控应阻止 091339 上的 voting 错误，但 095806 上可能因保守而损失一些窗 |
| G1 vs B2 (Modal) | 跨域优于或接近 Modal | 门控组合了两种方法的优势 |
| G4 vs G1 | 091339 更好、095806 略差 | Single fallback 在 voting-modal 分歧时更保守 |
| **G5 vs G1** | **091339 更好** | 双峰性检测直接识别"多簇竞争"场景（091339 特征），比 τ + peak_dist 更精确 |
| **G6 vs T0-V3** | **三个场景均改善** | 剔除噪声 tone 应提升 voting 输入质量，不依赖场景 |
| G1–G6 跨域 mean | 预期在 8.0–9.5% 区间 | G5/G6 理想情况下超越 G1–G4 |

### 4.3 文献调研后追加的 baseline

> `[待文献调研后补充]`：
>
> | G7 | TRRS 门控 | TR-BREATH [7] |
> | G8 | η/ρ/TRRS/persistence 联合特征 + threshold | — |
> | G9 | SVM 窗级 quality classifier | Wi-Breath [6] |
> | PCA 共识门控 | PCA-Modal3 + Plan2 Modal 共识（PCA plan Q3） | 与 G1 同框架、不同方法对 |

---

## 5. 评估设计

### 5.1 场景

| 场景 JSON | 用途 |
|-----------|------|
| `config/scenarios/cs_091339.json` | 主场景 — 验证门控能否阻止 voting 退化 |
| `config/scenarios/cs_095806.json` | 跨域 — 验证门控是否保留了 voting 的优势 |
| `config/scenarios/cs_102621.json` | 跨域 — 验证门控不引入新退化 |

### 5.2 指标

| 指标 | 说明 |
|------|------|
| 分段 BPM err% mean/std | 主指标 |
| 跨域 mean | 三场景平均 |
| 窗级门控动作分布 | `consensus & high-conf` / `consensus & low-conf` / `vote-high-conf` / `fallback` 四类占比 |
| 门控 vs 无门控窗级 BPM 偏差 | 分析门控改变了哪些窗的 BPM，方向是否正确 |
| 方法选择准确率 | 每窗比较门控选择的 BPM vs voting/modal/single 三者中最接近 GT 的 —— 门控是否选对了 |

### 5.3 成功标准

| 级别 | 条件 |
|------|------|
| **理想** | 跨域 mean < 8.5%，且 091339 ≤ Modal top2（13.04%）+ 095806 ≤ T0-V3（6.84%）+ 1.5% |
| **最低** | 跨域 mean < 9.45%（不差于 Modal top2），且 091339 无灾难性退化（≤ 18%） |
| **失败** | 门控跨域 mean > Modal top2 + 2%（> 11.45%），或门控在 091339 上比 T0-V3 还差 |
| **部分成功** | 门控在某个场景上显著优于两种无门控方法，但跨域均值未改善 |

### 5.4 诊断产出

关键诊断：**窗级方法选择准确率热力图**。对每窗，找出 voting / modal / single 三者中 BPM 最接近 GT 的那个（oracle），然后统计门控选对/选错的比例。宽表如下：

| 场景 | 段 | oracle = voting | oracle = modal | oracle = single | 门控选对率 |
|------|-----|-----------------|----------------|-----------------|------------|
| 091339 | 3 | 30% | 45% | 25% | ? |
| 095806 | 1a | 55% | 30% | 15% | ? |
| ... | ... | ... | ... | ... | ? |

---

## 6. 实现要点

### 6.1 建议文件

| 类型 | 路径 |
|------|------|
| 实验脚本 | `notebooks/scripts/chFusion_voting_gating.py` |
| 可复用模块 | `src/ble_analysis/consensus_gating.py`（新建，~200 行） |
| 场景配置 | 沿用现有 JSON |

### 6.2 复用 API

```python
from ble_analysis.chfusion import (
    ChFusionConfig, Plan2Config,
    run_multichannel_segment_filtering,
    run_modal_fusion_benchmark,
    estimate_segment_bpm_methods,        # Single/Uniform
    _energy_ratio, _peak_prominence,
    _find_best_channel, _weighted_median,
    _overall_rel_error, _seg_bpm_stats,
)
from ble_analysis.voting_fusion import (
    VotingConfig,
    estimate_bpm_per_tone,
    vote_bpm_weighted_histogram,
    vote_bpm_histogram,
    _vote_one_window,
    MODAL_VOTING_VARIABLES,
)
from ble_analysis.segments import (
    BreathMetricParams, FilterParams,
    _sliding_window_indices,
)
```

### 6.3 新增模块接口草案

`src/ble_analysis/consensus_gating.py`：

```python
__all__ = [
    "GatingConfig",
    "GatingStrategy",
    "GatingDecision",
    "compute_gating_signals",
    "compute_bimodality_score",
    "compute_tone_persistence",
    "apply_gating",
    "run_gating_benchmark",
]

@dataclass
class GatingConfig:
    """窗级共识门控配置"""
    delta_bpm: float = 3.0             # 共识容忍度 (BPM)
    tau_hi: float = 0.30               # voting 高置信度阈值
    fallback_method: str = "single"    # "single" | "modal"
    consensus_weighting: str = "conf"  # "equal" | "conf"
    min_eta_for_gating: float = 0.02   # η 过低时直接 fallback
    # G5 专属
    bimodality_threshold: float = 0.5  # peak_2/peak_1 超过此值视为双峰
    # G6 专属
    persistence_threshold: float = 2.0 # mean_step_L1 超过此值的 tone 被剔除
    min_stable_tones: int = 12         # 最少稳定 tone 数，不足则 fallback

class GatingDecision(Enum):
    CONSENSUS_HIGH = "consensus_high"      # 一致 + 高置信 → 平均
    CONSENSUS_LOW = "consensus_low"        # 一致 + 低置信 → 信 modal
    VOTE_HIGH_CONF = "vote_high_conf"      # 分歧 + vote 高置信 → 信 vote
    FALLBACK = "fallback"                  # 都不好 → fallback

def compute_gating_signals(
    bpm_vote: float, bpm_modal: float, bpm_single: float,
    conf_vote: float, conf_vote_mass: float,
    eta_vote_max: float, eta_modal_max: float,
    config: GatingConfig,
) -> Tuple[GatingDecision, float]:
    """返回 (决策类型, 最终 BPM)"""
    ...

def apply_gating(
    voting_results: dict,     # T0-V3 的完整结果
    modal_results: dict,      # Modal top2 的完整结果
    single_results: dict,     # Single Remote 的完整结果
    config: GatingConfig,
) -> dict:
    """完整门控 pipeline：逐窗计算信号 → 决策 → 汇总"""
    ...

def run_gating_benchmark(
    frames, segment_config, ...,
    gating_strategies: List[GatingConfig],
) -> dict:
    """跑所有门控策略 + 返回对比"""
    ...
```

### 6.4 伪代码：窗级门控循环

```python
# 对每段 breath 数据
for seg in breath_segments:
    gated_bpms = []
    decisions = []
    for w_idx, window in enumerate(sliding_windows(seg)):
        # 1. 获取三个方法在该窗的 BPM
        bpm_vote   = voting_results[seg][window].bpm       # T0-V3
        bpm_modal  = modal_results[seg][window].bpm        # Modal top2
        bpm_single = single_results[seg][window].bpm       # Single Remote

        # 2. 计算门控信号
        peak_dist   = abs(bpm_vote - bpm_modal)
        conf_vote   = voting_results[seg][window].confidence
        eta_vote    = voting_results[seg][window].max_eta
        eta_modal   = modal_results[seg][window].top2_eta_mean

        # 3. 门控决策
        decision, bpm_final = compute_gating_signals(
            bpm_vote, bpm_modal, bpm_single,
            conf_vote, peak_dist, eta_vote,
            config
        )

        gated_bpms.append(bpm_final)
        decisions.append(decision)

    # 段级统计
    seg_err = np.mean(np.abs(np.array(gated_bpms) - gt) / gt) * 100
```

### 6.5 不做的事

- 不引入新变量（总幅值等）
- 不在本 plan 阶段做 τ/δ 的 exhaustive grid search（留待实验脚本内快速扫描）
- 不修改 `voting_fusion.py` 或 `chfusion.py`
- 不新增场景 JSON

---

## 7. 预期产出

| 产出 | 路径 |
|------|------|
| 验证报告 | `docs/reports/voting_gating_report.md` |
| 数值结果 | `outputs/reports/voting_gating_results.npy` |
| 跨域汇总 | `outputs/reports/voting_gating_cross_domain.npy` |
| 门控决策分布图 | `outputs/figures/voting_gating_decision_pie.png`（四类决策占比） |
| 对比柱状图 | `outputs/figures/voting_gating_comparison_bars.png`（G1–G4 vs T0-V3 vs Modal） |
| 方法选择准确率热力图 | `outputs/figures/voting_gating_oracle_heatmap.png` |

---

## 8. 风险与保留问题

### 8.1 算法风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 门控本身引入新错误——在 consensus 时取平均可能拉偏正确结果 | 中 | 诊断 oracle 选对率；如果平均比二选一更差，改用 "选更可信的" 而非平均 |
| δ = 2–3 BPM 是否合理？呼吸 BPM 变化缓慢（窗间差通常 < 2 BPM），但 GT 分辨率有限 | 低 | δ 在 1–5 BPM 范围内扫描 |
| Fallback 到 Single 在 091339 上本身就是 10.91%（比 Modal 13.04% 更好）——门控可能只是在学"多用 Single" | 中 | 报告门控决策分布；如果 >70% 窗 fallback 到 Single，说明门控没有真正融合两种方法 |
| 门控策略可能过拟合三场景的特定窗 | 高 | 明确标注"仅金属板三场景"；如需推广需要更多场景验证 |

### 8.2 保留问题

| ID | 问题 | 备注 |
|----|------|------|
| Q1 | 门控最优 δ/τ_hi 是否跨场景一致？ | `[待确认]` — 需三场景分别扫描 |
| Q2 | η 是否足够作为"窗级可靠性"的代理？tone_persistence 和 bimodality_score 是否更优？ | `[待确认]` — G5/G6 将直接回答此问题 |
| Q3 | Fallback 用 Single Remote 还是 Modal top2？091339 上 Single 更优（10.91% vs 13.04%），095806 上 Modal 更优（10.61% vs 12.16%） | `[待确认]` — 可能也需要场景自适应 |
| Q4 | persistence_threshold = 2.0 BPM 是否合理？剔除后稳定 tone 数通常剩多少？ | G6 执行后分析 tone 剔除分布 |
| Q5 | [待文献调研后补充] TRRS / SVM 特征是否能提供比 persistence/bimodality 更好的门控信号？ | |
| Q6 | [待文献调研后补充] 门控能否扩展到 PCA-Modal3 + Modal top2 的方法对？ | |

---

## 9. 文献调研衔接清单

以下章节预留了文献调研后的补充空间：

| 章节 | 当前状态 | 待补充内容 |
|------|----------|-----------|
| §1.3 | 已写 PCA Q3、Deng τ、频率选择性衰落诊断 | 追加 TR-BREATH TRRS、Wi-Breath SVM、Bimodal CSI motion detection |
| §1.4 | 空 | 每个关键论文可借鉴的具体技术点 + 如何集成到门控框架 |
| §2.2 | 已写 13 个门控信号（含 bimodality_score / tone_persistence / n_coherent_tones） | 追加 TRRS、SVM confidence score |
| §3.4 | **G5/G6 已定义**（基于诊断发现，可立即实现） | G7/G8/G9（文献驱动的方法变体） |
| §4.3 | **G5/G6 已加入必跑表** | G7/G8/G9（文献驱动的 baseline） |
| §8.2 Q5/Q6 | 已写 persistence/bimodality 相关问题 | 待文献驱动的新问题 |

**可立即执行**：G1–G6 共 6 种门控策略 + 5 个 baseline + T0-V3 = **12 个方法**，无需等待文献调研。

---

## 10. 验证状态

| 字段 | 内容 |
|------|------|
| **验证状态** | 已完成（G1–G6；G7–G9 待文献调研） |
| **实际脚本** | `notebooks/scripts/chFusion_voting_gating.py`、`src/ble_analysis/consensus_gating.py` |
| **数值结果** | `outputs/reports/voting_gating_results.npy`、`voting_gating_cross_domain.npy`、`voting_gating_oracle_stats.npy` |
| **图表** | `outputs/figures/voting_gating_decision_pie.png`、`voting_gating_comparison_bars.png`、`voting_gating_oracle_heatmap.png` |
| **报告链接** | `docs/reports/voting_gating_report.md` |
| **一句话结论** | G4 跨域 mean 8.65% 优于 Modal（9.45%）和 T0-V3（9.20%），达最低成功标准；G5/G6 分别在 091339/095806 单场景显著改善，无全局最优门控。 |

**结论摘要：**

- 跨域最优：**G4 Single fallback** 8.65% > G5 8.72% > G1 8.95% > T0-V3 9.20% > Modal 9.45%
- 091339：G5 12.27% 最优（vs Modal 13.04%、T0-V3 13.77%）
- 095806：G6 6.55% 最优（vs T0-V3 6.84%、Modal 10.61%）
- 102621：G1/G4 4.51% 最优（vs Modal 4.69%）
- 理想标准（跨域 < 8.5%）未达成；最低标准达成

**遗留问题：**

- G7–G9 与 PCA 共识门控待文献调研后追加
- oracle 窗级选对率多数段 < 70%，门控信号仍需优化
- Fallback Single vs Modal 的场景自适应（Q3）未解决

---

## 给执行 Agent 的首条指令

> ⚠️ **本 plan 部分就绪**：G1–G6 可立即执行（无需文献调研）。G7–G9 和 PCA 共识门控等待文献调研后再追加。
>
> Cursor Composer 当前执行内容：
> 1. 实现 §3.2–3.4 的 G1–G6 六种门控策略
> 2. 新增 `src/ble_analysis/consensus_gating.py`（接口见 §6.3，含 `compute_bimodality_score`、`compute_tone_persistence`）
> 3. 复用 `voting_fusion.compute_channel_bpm_persistence`（已实现）作为 G6 的输入
> 4. 写 `notebooks/scripts/chFusion_voting_gating.py`
> 5. 跑 §4.1 的 12 个方法（4 baseline + T0-V3 + G1–G6）× 三场景
> 6. 输出 §7 的图表和报告
> 7. 生成 §5.4 的 oracle 方法选择准确率分析
>
> 执行完成后，请返回以下材料给 Claude/DeepSeek Review：
>
> - `docs/reports/voting_gating_report.md`
> - `outputs/reports/voting_gating_*.npy`
> - `outputs/figures/voting_gating_*.png`
> - `src/ble_analysis/consensus_gating.py`
> - git diff 摘要
