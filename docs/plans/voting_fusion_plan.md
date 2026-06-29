# Voting Fusion — 基于统计投票的多信道 BPM 融合验证计划

> **来源**：Deng et al., "A statistical sensing method by utilizing Wi-Fi CSI subcarriers", *J. Information and Intelligence*, 2024  
> **目标报告**：`docs/reports/voting_fusion_report.md`（模板：`docs/templates/algorithm_validation_report.md`）  
> **建议 plan 路径**：`docs/plans/voting_fusion_plan.md`  
> **日期**：2026-06-07  
> **验证状态**：已完成

---

## 1. 动机与背景

| 项目 | 说明 |
|------|------|
| 问题 | 当前 `Modal top2` / `chFusion` 的融合策略是**先选模态再谱融合**，本质上仍属于"在融合后的单一谱上找 BPM"。Deng et al. (2024) 提出另一种范式：**每个信道独立估计 BPM，然后统计投票**。这两种范式哪种更适合 BLE CS 数据，尚未验证 |
| 相关文档 | `docs/chFusion_pca_svd_plan.md`（当前最优：Modal top2/η-weight 跨域 mean **9.45%**）、`docs/CS呼吸算法验证整体进度.md` |
| 本 plan 定位 | **验证论文方法** — 将 Deng et al. 的 voting 框架适配到 BLE CS 多信道/多模态场景，与现有 Plan2 Modal 做系统对比 |

### 1.1 论文核心发现与本项目的关系

Deng et al. 的核心论证：

1. **传统加权求和的问题**：权重通常基于信号质量标量（如 CSI 幅值），但子载波之间的噪声（ICI）是**强相关的**。加权求和的有效性假设噪声独立，因此它不能有效抑制主要的 ICI 噪声。
2. **替代方案**：对每个 subcarrier **独立做检测/估计**，得到每个 subcarrier 的结果后，用**统计投票**融合。

在本项目 BLE CS 中：
- Wi-Fi subcarrier ↔ BLE tone（72 个，1 MHz 间隔，freq diversity 比 Wi-Fi 更大）
- 我们的 `Single` baseline 就是 per-tone 独立估计，但后续 `Modal top2` 是 per-modality 融合（不是 per-tone voting）
- **两个关键新问题**：(a) 多 tone 独立 BPM 估计后 voting vs 现有谱融合；(b) 投票机制可与现有 `η`/`ρ` 质量指标交叉

### 1.2 本项目已做了什么与此相关

- `Single`：每窗选 η 最大 tone → 单 tone BPM → **这正是"per-subcarrier 估计"的第一步**
- `Modal top2`：每模态选 η 最大 tone → 独立谱 → 模态融合 → BPM
- **缺失的步骤**：我们从未做过"72 tone 每 tone 独立做完整 BPM 估计 → 对 72 个 BPM 估计值做统计投票"

---

## 2. 物理与变量

### 2.1 可用观测量

| 变量 | 是否使用 | 理由 |
|------|----------|------|
| `remote_amplitudes` | ✅ | 当前项目综合最优的单变量；用作 per-tone voting 的主输入 |
| `local_amplitudes` | ✅（对照） | 用于验证 voting 是否对变量不敏感 |
| `amplitudes`（总幅值） | ❌（本 plan） | 避免变量数爆炸；如有余力可追加 |
| `phases`（总相位） | ✅（对照） | 作为 per-tone voting 的相位输入对照 |

### 2.2 不使用的变量及原因

- 不用 `local/remote` **单端相位**（含 LO 漂移，物理上不可靠）
- 总幅值暂不引入，先聚焦 remote/local 幅值 + phase 三变量

### 2.3 符号约定

| 符号 | 含义 |
|------|------|
| η | 呼吸频段能量比（per-tone per-window） |
| ρ | 谱峰峰度（per-tone per-window） |
| BPM_i | 第 i 个 tone 的独立 BPM 估计 |
| M | 有效 tone 数（≤72） |
| τ | Voting threshold（如 0.3M，来自论文） |
| GT | Ground truth BPM |

---

## 3. 算法步骤

### 3.1 公共前置（与现有 Plan2 相同）

```
数据源：BLE CS 72 tone，sampleData/CS_frames_*.jsonl
分段：config/scenarios/*.json（7 breath + 2 apnea，每段有 bpm_gt）
单信道滤波链：median → highpass (0.05 Hz) → bandpass (0.1–0.35 Hz)
滑窗：20 s 窗长 / 1 s 步长
```

### 3.2 待测方法 T0：Per-Tone Voting BPM（纯投票）

**输入变量**：`remote_amplitudes`（72 tone 的 bandpass_filtered 波形）。

```
对每窗:
  对每个有效 tone i (1..M):
    1. 取该 tone 的 remote_amplitudes bandpass_filtered 波形
    2. 计算该 tone 的 η_i（从 highpass_filtered 切片）
    3. 对波形做 FFT → 呼吸频带内找 argmax 峰频 → BPM_i
  得到 {BPM_1, BPM_2, ..., BPM_M}（M ≤ 72）

投票策略 V1 — 简单直方图投票：
  4. 在呼吸频带 [6, 30] BPM 范围内以 1 BPM 为 bin 做直方图
  5. 取最高票数的 BPM bin 中心值作为最终估计
  6. 如果最高票数 < τ·M（τ = 0.3，来自论文），标记为 "低置信度"

投票策略 V2 — η 加权投票：
  4. 同上直方图，但每 tone 的投票权重 = η_i
  5. 取加权最高票数的 BPM bin

投票策略 V3 — η 加权 + ρ 惩罚：
  4. 同上，权重 = η_i · ρ_i（ρ_i 为 tone i 的谱峰峰度）
  5. 低 ρ 的 tone（谱峰宽）自动降权
```

### 3.3 待测方法 T1：Per-Tone Voting + Top-K 筛选

**输入变量**：`remote_amplitudes`（与 T0 相同）。仅使用 **η 排序前 K 个 tone** 参与投票（K = 16, 8, 4）：

```
对每窗:
  1. 计算所有 72 tone 的 η_i
  2. 按 η 降序取前 K 个 tone
  3. 对 K 个 tone 独立估计 BPM
  4. 在 K 个 BPM 上执行 V1/V2/V3 投票
```

目的：测试剔除劣质 tone 是否能提升 voting 精度（论文隐含在"有效 subcarrier"概念中但未系统实验）。

### 3.4 待测方法 T2：Cross-Modal Voting（模态间投票）

将 voting 扩展为模态间投票。**输入变量**：每模态各自选 max-η 单 tone 的 bandpass_filtered 波形，变量分别为 `remote_amplitudes`、`local_amplitudes`、`phases`。

```
对每窗:
  对每模态 m ∈ {remote_amp, local_amp, phase}:
    1. 取该模态 η 最大的 tone 的 bandpass_filtered 波形
    2. FFT → 呼吸频带 argmax → BPM_m
  得到 3 个 BPM 估计值

投票: 
  直接取中位数 (median)，或 η_m 加权平均
```

这与 Plan2 `Modal top2` 的区别：
- `Modal top2`：选 top2 模态 → 谱融合 → 一个 BPM
- T2：每模态独立 BPM → 对 3 个 BPM 值做 consensus

### 3.5 待测方法 T3：Voting + Modal 混合（融合核心候选）

**输入变量**：`remote_amplitudes`、`local_amplitudes`、`phases`（三个变量各自独立做 per-tone voting，再模态间 consensus）。

```
对每窗:
  步骤 A（模态内 voting）:
    对 remote_amplitudes 的 72 tone 做 V2 voting → BPM_rem
    对 local_amplitudes 的 72 tone 做 V2 voting → BPM_loc
    对 phases 的 72 tone 做 V2 voting → BPM_pha

  步骤 B（模态间 voting）:
    对 {BPM_rem, BPM_loc, BPM_pha} 取 η 加权中位数作为最终 BPM
    其中加权 η 为各模态内最高 η tone 的 η 值
```

此方法的结构与论文最接近：per-subcarrier（per-tone）→ per-modality → final consensus。

### 3.6 BPM 估计细节

```
per-tone BPM 估计:
  输入: tone 波形 (M 帧)
  1. Hanning 窗
  2. FFT → 功率谱
  3. 呼吸频带 [0.1, 0.35] Hz 内 argmax
  4. parabolic 插值细调 → f_peak
  5. BPM = f_peak × 60

半频/倍频处理 [待确认]:
  - 暂不做谐波处理（先看 raw voting 效果）
  - 如果 voting 天然压制了倍频 outlier、median 稳健，那是优势
```

---

## 4. Baseline 对比

执行 Agent **必须**跑齐下表方法。

| 方法 ID | 输入变量 | 说明 | 实现参考 |
|---------|----------|------|----------|
| **B0** | `remote_amplitudes`（max-η 单 tone） | Single Remote（max-η 单信道 BPM） | `chfusion.py` 现有 |
| **B1** | `remote_amplitudes`（72 tone 等权） | Uniform Remote（72 tone 等权谱融合 BPM） | `chfusion.py` 现有 |
| **B2** | `remote_amplitudes` + `local_amplitudes` + `phases`（各 max-η 单 tone） | Modal top2 equal（当前跨域最优） | `chFusion_plan2.py` 现有 |
| **B3** | 同上 | Modal η-weight | `chFusion_plan2.py` 现有 |
| **T0-V1** | `remote_amplitudes`（72 tone） | Per-Tone Voting — 简单直方图 | 本 plan §3.2 |
| **T0-V2** | `remote_amplitudes`（72 tone） | Per-Tone Voting — η 加权直方图 | 本 plan §3.2 |
| **T0-V3** | `remote_amplitudes`（72 tone） | Per-Tone Voting — η·ρ 联合加权 | 本 plan §3.2 |
| **T1-K4-V2** | `remote_amplitudes`（Top-4 tone by η） | Top-4 tone η voting | 本 plan §3.3 |
| **T1-K8-V2** | `remote_amplitudes`（Top-8 tone by η） | Top-8 tone η voting | 本 plan §3.3 |
| **T1-K16-V2** | `remote_amplitudes`（Top-16 tone by η） | Top-16 tone η voting | 本 plan §3.3 |
| **T2** | `remote_amplitudes` + `local_amplitudes` + `phases`（各 max-η 单 tone） | Cross-Modal Voting（3 模态 median） | 本 plan §3.4 |
| **T3** | `remote_amplitudes` + `local_amplitudes` + `phases`（各 72 tone） | Voting + Modal 混合 | 本 plan §3.5 |

### 预期相对关系（研究阶段假设，可被实验推翻）

| 对比 | 预期 | 理由 |
|------|------|------|
| T0-V2 vs B0 (Single) | 略优或相当 | voting 应比单 tone 更稳健（Deng 论文结论）；但 BLE tone 间噪声相关性可能弱于 Wi-Fi |
| T0-V2 vs B1 (Uniform) | 显著更优 | Uniform 是论文明确批评的方式（先加权平均再估计）；voting 保留了每个 tone 的完整信息 |
| T0-V3 vs T0-V2 | 略优 | ρ 惩罚应进一步降低宽峰 tone 的干扰 |
| T1-K16-V2 vs T0-V2 | 相当或略优 | 剔除 η 很低的 tone 可能减少噪声；但可能损失 diversity |
| T2 vs B2 (Modal top2) | 各有优势 | 结构不同：T2 是独立 BPM 再 consensus，B2 是先谱融合再 BPM |
| T3 vs B2 (Modal top2) | [待确认] — 不确定 | T3 是论文范式的最完整实现；是否超越 Modal top2 取决于 BLE tone 噪声结构 |

---

## 5. 评估设计

### 5.1 场景

| 场景 JSON | 用途 |
|-----------|------|
| `config/scenarios/cs_091339.json` | 主场景 |
| `config/scenarios/cs_095806.json` | 跨域重复性 |
| `config/scenarios/cs_102621.json` | 跨域重复性 |

### 5.2 指标

| 指标 | 说明 |
|------|------|
| 分段 BPM 相对误差 % | 主指标；报告 mean / std |
| 跨域 mean | 三场景平均 mean err% |
| 窗级低置信度占比 | voting 票数 < τ·M 的窗口比例（T0/T1/T3 专属） |
| η / ρ 分布 | 投票参与 tone 的质量分布 |
| 单 tone vs voting BPM 偏差 | 分析 voting 是否有效压低了 outlier BPM |

### 5.3 成功标准

| 级别 | 条件 |
|------|------|
| **理想** | 任一 voting 方法的跨域 mean < **9.45%**（超过当前 Modal top2），且 091339 无灾难性退化 |
| **最低** | T0-V2 跨域 mean ≤ B0 (Single Remote) 的跨域 mean，即 voting 不比单 tone 差 |
| **mixed** | 部分场景显著优于 baseline、部分场景显著差 → voting 为**场景条件有效** |
| **失败** | 所有 voting 方法跨域 mean > 15%，或 091339 mean > 25% |

---

## 6. 实现要点

### 6.1 建议文件

| 类型 | 路径 |
|------|------|
| 实验脚本 | `notebooks/scripts/chFusion_voting_fusion.py` |
| 可复用模块（新增） | `src/ble_analysis/voting_fusion.py` |
| 场景配置 | 沿用现有 JSON（不需新增） |

### 6.2 复用 API

```python
from ble_analysis.chfusion import (
    run_multichannel_segment_filtering,
    estimate_segment_bpm_methods,  # 复用 Single/Uniform baseline
    Plan2Config,                    # 复用 Modal top2 baseline
)
from ble_analysis.segments import _sliding_window_indices
from ble_analysis.metrics import _overall_rel_error, _seg_bpm_stats
```

### 6.3 新增模块接口草案

`src/ble_analysis/voting_fusion.py`（~150 行）：

```python
__all__ = [
    "VotingConfig",
    "VotingStrategy",
    "estimate_bpm_per_tone",
    "vote_bpm_histogram",
    "vote_bpm_weighted_histogram",
    "run_voting_fusion",
]

@dataclass
class VotingConfig:
    """Voting fusion 配置"""
    variable: str = "remote_amplitudes"  # 或 "local_amplitudes", "phases"
    voting_strategy: str = "eta_weighted"  # "simple" | "eta_weighted" | "eta_rho_weighted"
    top_k: int | None = None  # None = 全部 72 tone, 或 4/8/16
    vote_threshold: float = 0.3  # τ，论文默认 0.3
    bin_resolution_bpm: float = 1.0  # 直方图 bin 宽
    breath_freq_low: float = 0.1
    breath_freq_high: float = 0.35

def estimate_bpm_per_tone(
    window_data: np.ndarray,       # (M_frames, N_tones) bandpass_filtered
    eta_per_tone: np.ndarray,      # (N_tones,) per-tone η
    rho_per_tone: np.ndarray | None,  # (N_tones,) per-tone ρ, optional
    config: VotingConfig,
    fs: float,
) -> tuple[np.ndarray, np.ndarray]:
    """对每个 tone 独立估计 BPM.
    
    Returns:
        bpm_per_tone: (N_tones,) 或 (K,)
        quality_per_tone: (N_tones,) η 或 η·ρ
    """
    ...

def vote_bpm_weighted_histogram(
    bpm_per_tone: np.ndarray,
    weights: np.ndarray,
    config: VotingConfig,
) -> tuple[float, bool]:
    """对 per-tone BPM 做加权直方图投票.
    
    Returns:
        final_bpm: 投票 BPM
        confident: 最高票数是否 >= τ·M
    """
    ...

def run_voting_fusion(
    frames: ..., scenario: ..., config: VotingConfig,
) -> dict:
    """完整 voting fusion pipeline: 滤波 → 滑窗 → per-tone BPM → 投票.
    
    Returns:
        {
            "bpm_per_window": List[float],
            "confident_per_window": List[bool],
            "bpm_per_tone_per_window": List[np.ndarray],
        }
    """
    ...
```

### 6.4 伪代码：主循环

```python
# 对每段 breath 数据
for seg in breath_segments:
    all_bpm = []
    all_confident = []
    for window in sliding_windows(seg):
        # 1. 取出 M×N 带通矩阵
        data_matrix = window.get_bandpass_data(config.variable)  # (M, N)

        # 2. 计算 per-tone η, ρ（从高通数据）
        eta = compute_eta_per_tone(window.get_highpass_data(config.variable))
        rho = compute_rho_per_tone(data_matrix)

        # 3. 可选 Top-K 筛选
        if config.top_k:
            top_idx = np.argsort(eta)[-config.top_k:]
            data_matrix = data_matrix[:, top_idx]
            eta = eta[top_idx]
            rho = rho[top_idx]

        # 4. Per-tone BPM 估计
        bpm_per_tone, quality = estimate_bpm_per_tone(data_matrix, eta, rho, config)

        # 5. Voting
        bpm, confident = vote_bpm_weighted_histogram(bpm_per_tone, quality, config)

        all_bpm.append(bpm)
        all_confident.append(confident)

    # 段内 BPM 相对误差
    seg_err = np.mean(np.abs(np.array(all_bpm) - gt) / gt) * 100
```

### 6.5 不做的事

- 不修改现有 `chfusion.py` / `pca_svd.py` / `segments.py`
- 不在本 plan 阶段引入 learning-based voting（如 SVM/MLP）
- 不新增场景 JSON
- 不对 apnea 段做 voting（与现有 pipeline 一致，仅 breath 段）

---

## 7. 预期产出

| 产出 | 路径 |
|------|------|
| 验证报告 | `docs/reports/voting_fusion_report.md` |
| 数值结果 | `outputs/reports/voting_fusion_results.npy` |
| 跨域汇总 | `outputs/reports/voting_fusion_cross_domain.npy` |
| 排行榜柱状图 | `outputs/figures/voting_fusion_leaderboard.png` |
| 跨域汇总图 | `outputs/figures/voting_fusion_cross_domain_aggregate_bars.png` |
| Voting 诊断图 | `outputs/figures/voting_fusion_diagnostics.png`（per-tone BPM 散点 vs GT、置信度分布、bin 直方图示例） |

### 7.1 建议运行命令

```bash
# 单场景完整实验
python notebooks/scripts/chFusion_voting_fusion.py

# 跨域汇总（可选）
python notebooks/scripts/chFusion_voting_fusion_cross_domain.py
```

---

## 8. 风险与保留问题

### 8.1 算法风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| BLE tone 间噪声相关性弱于 Wi-Fi subcarrier → voting 优势不明显 | 预期验证论文结论，但可能推翻 | 通过 T0 vs B0/B1 直接测量 voting gain |
| Voting 在 72 tone 上 bin 分辨率足够、但倍频 tone 可能占多数 → voting 选错 | 高 | 对比 V3（含 ρ 惩罚）和 V2 |
| Voting threshold τ = 0.3 直接取自论文、未经 BLE 调优 | 中 | 报告低置信度窗占比，必要时扫描 τ ∈ [0.2, 0.5] |
| Top-K 太小可能丢失 diversity、K 太大可能引入噪声 | 中 | 同时测 K=4/8/16/72（全量） |

### 8.2 数据风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 当前仅金属板三场景 → 结论可能是域特定的 | 高 | 明确标注"仅金属板场景"；P2 建议新场景 |
| Apnea 段不评估（与现有 baseline 一致） | 低 | 不适用 voting 方法（无呼吸信号时 voting 无意义） |

### 8.3 评估风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| BPM 离散化 bin width = 1 BPM → 精度受限于 bin 分辨率 | 中 | 记录 bin 分辨率；可用 parabolic 插值在投票前细化 per-tone BPM |
| 论文使用的 detector 与我们的 BPM 估计不同 | 低 | 我们仅对比"估计"部分（不做检测），与现有 leaderboard 对齐 |

### 8.4 保留问题

| ID | 问题 | 备注 |
|----|------|------|
| Q1 | Voting threshold τ 取 0.3 是否对 BLE 最优？ | `[待确认]` — 需要实验后扫描 |
| Q2 | BLE 72 tone 的 η 分布是否足够 diverse 使 voting 有效？ | `[待确认]` |
| Q3 | Voting 是否能天然压制倍频/半频 outlier（median/voting robust）？ | `[待确认]` — 关键假设 |
| Q4 | Voting 是否适用于 apnea 检测？ | 暂不在本 plan 范围 |

---

## 9. 验证状态

| 字段 | 内容 |
|------|------|
| **验证状态** | 已完成 |
| **实际脚本** | `notebooks/scripts/chFusion_voting_fusion.py`、`src/ble_analysis/voting_fusion.py` |
| **报告链接** | `docs/reports/voting_fusion_report.md` |
| **数值结果** | `outputs/reports/voting_fusion_results.npy`、`voting_fusion_cross_domain.npy` |
| **图表** | `outputs/figures/voting_fusion_leaderboard.png`、`voting_fusion_cross_domain_aggregate_bars.png`、`voting_fusion_diagnostics.png` |
| **一句话结论** | T0-V3（η·ρ per-tone voting）跨域 mean **9.20%** 略优于 Modal top2 **9.45%**，但 091339 主场景未改善（13.77% vs 13.04%）；T0-V2 未达最低成功标准；不建议替换 Modal top2 为默认策略 |

结论摘要：

- 跨域最优 voting：T0-V3 η·ρ-weight **9.20%**
- Plan 最低标准（T0-V2 ≤ Single Remote）：**未达成**（10.96% > 10.45%）
- Plan 理想标准（跨域 < 9.45% 且 091339 无退化）：**部分达成**（跨域达标，091339 未改善）

遗留问题：

- Q1–Q4 见 `docs/reports/voting_fusion_report.md` §6
- 091339 per-tone outlier / 倍频机制待诊断
- Top-K 筛选无效，已废弃为部署路线

---

## 给执行 Agent 的首条指令

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并严格执行：

`docs/plans/voting_fusion_plan.md`

实现 §3 的 T0/T1/T2/T3 四种 voting 方法，跑齐 §4 的 14 个 baseline + test 方法 × 三场景，使用 `docs/templates/algorithm_validation_report.md` 撰写 `docs/reports/voting_fusion_report.md`，并回填本 plan §9。

关键点：
1. **新模块** `src/ble_analysis/voting_fusion.py`（~150 行），核心接口见 §6.3
2. **复用现有滤波管线**（`run_multichannel_segment_filtering`）和评估函数（`_overall_rel_error`）
3. **BPM 估计统一用 20 s 窗 / 1 s 步 / 呼吸带 0.1–0.35 Hz**，与 Plan2 一致
4. **排行榜需包含 Plan2 Modal top2/η-weight 作为基准**，以检验 voting 是否达到或超越当前最优
