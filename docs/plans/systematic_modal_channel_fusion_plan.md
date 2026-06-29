# 模态×信道 系统性融合验证计划

> **来源**：
> - [CS呼吸算法验证整体进度](../CS呼吸算法验证整体进度.md) — 开篇定义"模态融合+信道融合"双维框架
> - Voting fusion 报告（T0-V3 9.20% vs Modal top2 9.45%）
> - Voting gating 报告（G4 8.65% 跨域最优，无全局最优策略）
> - PCA/SVD plan（PCA-Modal3 10.92%，未超越 Modal）
> - 既有实验的结构性盲区分析（见 §1.2）
>
> **目标报告**：`docs/reports/systematic_modal_channel_fusion_report.md`  
> **日期**：2026-06-08（初稿）

---

## 1. 动机与背景

### 1.1 核心问题：方法对比混淆了两个独立维度

[CS呼吸算法验证整体进度](../CS呼吸算法验证整体进度.md) 开篇即定义了本项目的二维框架：

> **模态融合**：幅值和相位用谁，或者直接融合使用；  
> **信道融合**：多个信道融合成一个。

然而，回顾所有既有实验，每种"方法"实际上是在两个维度上各自取了一个点，导致方法之间的对比**同时改变了信道策略和模态策略**，无法归因：

```
Single Remote   = 信道策略: Single best (max-η)    × 模态策略: 只用 remote
T0-V3           = 信道策略: 72-tone η·ρ voting    × 模态策略: 只用 remote
Modal top2      = 信道策略: Single best per modal  × 模态策略: Top2 谱融合
PCA-Modal3      = 信道策略: PCA 72-tone per modal  × 模态策略: η-weight 谱融合
T3 hybrid       = 信道策略: 72-tone voting         × 模态策略: 跨模态 voting
G4              = 窗级门控(T0-V3, Modal top2)      × (元方法，非独立策略)
```

**当我们在 leaderboard 上比较这些方法时，无法区分**：T0-V3（9.20%）低于 Modal top2（9.45%），是因为 voting（信道策略）不如 single-best？还是因为"只用 remote"（模态策略）不如"三模态 top2 融合"？

**这不仅是归因问题，更阻碍了方法改进**——最优策略可能在未探索的单元格中。

### 1.2 结构性盲区：未探索的组合

记信道策略集合 **C** = {Single, Uniform, Voting-ηρ, Persistence-Voting, PCA, Top-K}，模态策略集合 **M** = {Single-Remote, Single-Phase, Single-Local, Equal-3, η-weight-3, Top2-Equal, Top2-ρ, Cross-Modal-Voting}。

下图标记了已验证(✅)和未探索(❌)的组合：

| 信道策略 ╲ 模态策略 | Single-Remote | Equal-3 | η-weight-3 | Top2-Equal | Cross-Modal-Voting |
|---------------------|:---:|:---:|:---:|:---:|:---:|
| **Single best (per modal)** | ✅ 10.45% | ✅ | ✅ | ✅ **9.45%** | ✅ T2 10.54% |
| **Uniform (per modal)** | ✅ 11.02% | ❌ | ❌ | ❌ | ❌ |
| **Voting η·ρ (per modal)** | ✅ **9.20%** | ❌ | ❌ | ❌ | ✅ T3 9.70% |
| **Persistence-Voting (per modal)** | ✅ G6 | ❌ | ❌ | ❌ | ❌ |
| **PCA (per modal)** | ✅ 10.50% | ❌ | ✅ 10.92% | ✅ 11.14% | ❌ |

**关键盲区（优先级排序）**：

| 优先级 | 盲区 | 为什么重要 |
|--------|------|-----------|
| **P0** | Voting on **phases** (72 tone) | phases 也是 72 tone，物理上不同于 remote 幅值。voting 在 phases 上是否更好？ |
| **P0** | Voting per modal + **模态谱融合**（Equal/η-weight/Top2） | 这是 T0-V3 的模态维度自然扩展——类似 Modal top2 但用 voting 替代 single-best |
| **P1** | Uniform per modal + 模态谱融合 | Uniform 在 095806 phase 上极强（6.75%），模态融合后可能更优 |
| **P1** | Persistence-Voting per modal + 模态谱融合 | G6 在 095806 上最优（6.55%），模态融合后能否跨场景稳定？ |
| **P2** | Top-K 信道 × 不同模态策略 | Top-K 在 voting 中无效（K4/8/16 均差于全量），但在 PCA 中 top16 最优（10.85%）。K 在不同信道策略下效果不同 |

### 1.3 核心假设

> **H1（信道独立性）**：voting 作为一种信道融合策略，在不同模态（remote/phases/local）上的相对效果不同——phase voting 可能优于 remote voting，因为 phase 的 tone 间噪声结构可能更独立。

> **H2（模态×信道交互）**：最优的模态策略取决于所采用的信道策略，反之亦然。不存在"无条件最优"的信道或模态策略。

> **H3（Voting + 模态谱融合）**：将 T0-V3 的 per-tone voting 应用到每个模态（而非仅 remote），然后对三个模态的归一化谱做 Modal top2 谱融合，跨域 mean 将优于纯 T0-V3（9.20%）和纯 Modal top2（9.45%）。

> **H4（Phase voting 的特殊性）**：phases 的 72 个 tone 的 BPM 估计质量分布与 remote_amplitudes 显著不同——phase 在 095806 场景下可能比 remote 更适合 voting。

> **H5（双峰性/持久性 across modalities）**：G5 的双峰性门控和 G6 的 persistence 筛选在 phases 和 local 的 voting 上同样有效，可作为跨模态通用的信道质量控制手段。

---

## 2. 物理与变量

### 2.1 三种模态的 72 信道结构

每个 BLE CS 帧为 72 个 tone，**每种模态下都有 72 个独立信道**：

| 模态 | 每 tone 含义 | 72 信道间的差异来源 |
|------|-------------|-------------------|
| `remote_amplitudes` | 远端设备测得的 PCT 幅值 | 多径频率选择性衰落（每个 tone 不同频点） |
| `local_amplitudes` | 本地设备测得的 PCT 幅值 | 同上（方向相反，多径环境对称但不相同） |
| `phases` | 两端 PCT 向量乘法后的总相位（LO 已抵消） | 多径引入的频率选择性相位旋转 |

**关键物理事实**：三种模态的 72 信道数据都来自同一组 BLE tone，但各自反映不同的物理量。频率选择性衰落对三者均有影响，但影响的模式不同——幅值衰减和相位旋转在多径下的行为是互补的。

### 2.2 已使用和未使用的模态组合

| 组合 | 是否已验证 | 代表方法 |
|------|:---:|------|
| remote only | ✅ | Single Remote, T0-V3, Uniform Remote |
| phases only | ✅（仅 Single/Uniform/PCA） | Single Phase, Uniform Phase |
| local only | ✅（仅 Single/Uniform/PCA） | Single Local, Uniform Local |
| remote + phases + local（谱融合） | ✅ | Modal top2/equal/η-weight |
| remote + phases + local（BPM 投票） | ✅ | T2 Cross-Modal median, T3 hybrid |
| **remote + phases + local（per-modal voting → 谱融合）** | ❌ | **本 plan 核心新增** |

---

## 3. 算法设计：二维策略网格

### 3.1 信道策略（C 维度）

每模态独立执行。输入 = 单模态 72 信道 bandpass_filtered 波形，输出 = 归一化呼吸频谱 + BPM 估计。

| 代号 | 策略 | 说明 |
|------|------|------|
| **C-Single** | 选 max-η 单信道 | 与现有 Single 一致；η 在 highpass 上计算 |
| **C-Uniform** | 72 信道谱等权平均 | 与现有 Uniform 一致 |
| **C-Vote** | 72 信道 η·ρ 加权 BPM 直方图投票 | 即 T0-V3 的 per-tone voting |
| **C-VoteP** | Persistence-filtered voting | 即 G6：剔除 mean_step_L1 > 2.0 的 tone 后 voting |
| **C-PCA** | 72 信道高通 PCA → PC1 波形 → 谱 | 即 PCA-HP ch-η 或 ch-uniform |
| **C-TopK** | Top-K（η 排序）+ C-Vote | K ∈ {8, 16, 24, 36}；之前已验证 K=4/8/16 劣于全量但未系统扫 K |

### 3.2 模态策略（M 维度）

输入 = 每种模态各自产出的归一化频谱（来自信道策略），输出 = 融合后 BPM。

| 代号 | 策略 | 说明 |
|------|------|------|
| **M-Remote** | 只用 remote | 基线：不融合，等价于模态数=1 |
| **M-Phase** | 只用 phases | 基线：验证 phase voting 是否优于 remote voting |
| **M-Local** | 只用 local | 基线：验证 local 是否可通过 voting 改善（Single local 30%→?） |
| **M-Equal** | remote+phase+local 等权谱融合 | 与 Modal equal 一致 |
| **M-η** | 三模态按 mean η 加权谱融合 | 与 Modal η-weight 一致 |
| **M-Top2** | 每窗按 selector score 取 top2 模态，等权谱融合 | 与 Modal top2 equal 一致 |
| **M-Vote** | 三模态各自 BPM → 加权中位数 | 即 T3 的模态间 voting（非谱融合） |

### 3.3 门控策略（G 维度，元层次）

门控在窗口级别从多个（信道×模态）组合中选择。保留 G4（Single fallback）作为基准门控策略，并新增：

| 代号 | 策略 | 说明 |
|------|------|------|
| **G4** | T0-V3 vs Modal top2 → 共识取平均，分歧 fallback Single | 当前跨域最优 8.65% |
| **G4-Phase** | Phase-Voting vs Modal top2 → 共识取平均，分歧 fallback | 新增：phase voting 替代 remote voting |
| **G-Multi** | 在多个(C×M)组合中做窗级选择，选 conf 最高或 bimodality 最低的 | 新增：多候选门控 |

---

## 4. 实验矩阵

### 4.1 核心实验表（P0 优先级，必做）

共 **~15 个新方法**，加上既有 baseline，总计 ~25 方法。

#### Block A：信道策略在 phases 上的验证

验证 H1 和 H4——voting 是否在 phases 上也有效。

| ID | 信道策略 | 模态策略 | 新/旧 | 目的 |
|----|----------|----------|:---:|------|
| A1 | C-Vote | M-Phase | **新** | Phase voting: phases 72-tone η·ρ voting |
| A2 | C-VoteP | M-Phase | **新** | Persistence-filtered phase voting |
| A3 | C-Single | M-Phase | 旧 | Single Phase（已有 baseline） |
| A4 | C-Uniform | M-Phase | 旧 | Uniform Phase（已有 baseline） |

**关键问题**：Phase voting (A1) 的跨域 mean 是否优于 Remote voting (T0-V3 9.20%)？

#### Block B：Voting per modal + 模态谱融合

验证 H2 和 H3——这是最核心的新增实验。

| ID | 信道策略 | 模态策略 | 新/旧 | 目的 |
|----|----------|----------|:---:|------|
| B1 | C-Vote (per modal) | M-Equal | **新** | Voting→谱 → 三模态等权融合 |
| B2 | C-Vote (per modal) | M-η | **新** | Voting→谱 → η 加权融合 |
| B3 | C-Vote (per modal) | M-Top2 | **新** | Voting→谱 → top2 模态融合 |
| B4 | C-VoteP (per modal) | M-Top2 | **新** | Persistence-voting→谱 → top2 |

**实现方式**：对每个模态（remote, local, phases），用 C-Vote 产出一个归一化频谱（对 voting 选出的 winning bin 中心 BPM 对应的频率构造窄带谱，或直接用 winning bin 附近 tones 的平均谱），然后用 Modal top2 相同的谱融合逻辑。

**关键问题**：B3（Voting→Top2）能否同时超越 T0-V3（9.20%，单模态 voting）和 Modal top2（9.45%，单信道 top2）？

#### Block C：Uniform per modal + 模态融合

验证 Uniform 在模态融合框架下是否能发挥 095806 phase Uniform（6.75%）的优势。

| ID | 信道策略 | 模态策略 | 新/旧 | 目的 |
|----|----------|----------|:---:|------|
| C1 | C-Uniform (per modal) | M-Top2 | **新** | Uniform 频谱 + top2 模态 |
| C2 | C-Uniform (per modal) | M-η | **新** | Uniform 频谱 + η 加权模态 |

### 4.2 扩展实验表（P1 优先级，有余力做）

| ID | 信道策略 | 模态策略 | 目的 |
|----|----------|----------|------|
| D1 | C-Vote | M-Local | Local voting: local 在 Modal top2 中常被踢出，独立 voting 是否能挽救？ |
| D2 | C-PCA (per modal) | M-Top2 | PCA→谱→top2（即 PCA-Modal3 top2，已有 11.14%，作为对照） |
| D3 | C-TopK (K=24) + C-Vote | M-Top2 | 中等 K 的 voting + modal fusion |

### 4.3 Baseline（复用既有结果）

| ID | 跨域 mean | 来源 |
|----|-----------|------|
| B0 Single Remote | 10.45% | chfusion baseline |
| B1 Uniform Remote | 11.02% | chfusion baseline |
| B2 Modal top2 equal | 9.45% | Plan2 当前最优 |
| B3 Modal η-weight | 9.45% | Plan2 |
| T0-V3 Per-Tone η·ρ voting | 9.20% | Voting plan |
| T3 Voting+Modal hybrid | 9.70% | Voting plan |
| G4 Single fallback | 8.65% | Gating plan 当前全局最优 |
| Single Phase | varies | Plan2 baseline |
| Uniform Phase | varies | Plan2 baseline |

### 4.4 场景

| 场景 | 用途 |
|------|------|
| `cs_091339` | voting 退化场景 — 验证 phase voting / modal fusion 能否改善 |
| `cs_095806` | voting 优势场景 — 验证模态融合是否保留 voting 优势 |
| `cs_102621` | 跨域对照 — 验证方法不引入新退化 |

---

## 5. 评估设计

### 5.1 主指标

- 分段 BPM err% mean / std
- 跨域 mean（三场景平均）
- **新增**：信道策略对比（固定模态策略，比较不同信道策略）
- **新增**：模态策略对比（固定信道策略，比较不同模态策略）

### 5.2 消融分析（Ablation）

这是本 plan 区别于以往的关键——**必须做消融**以分离信道策略和模态策略的贡献：

| 消融对比 | 固定 | 变化 | 回答的问题 |
|----------|------|------|-----------|
| A1 vs T0-V3 | 信道=C-Vote | 模态=Phase vs Remote | Phase voting 是否优于 Remote voting？ |
| B3 vs T0-V3 | 信道=C-Vote | 模态=Top2 vs Remote-only | 加模态融合对 voting 的增益？ |
| B3 vs Modal top2 | 模态=Top2 | 信道=Voting vs Single-best | Voting 替代 Single-best 做信道选择是否更好？ |
| B4 vs B3 | 模态=Top2 | 信道=VoteP vs Vote | Persistence 在模态融合下的增益？ |
| C1 vs Modal top2 | 模态=Top2 | 信道=Uniform vs Single-best | Uniform 做信道策略是否比 Single-best 更好？ |

### 5.3 成功标准

| 级别 | 条件 |
|------|------|
| **理想** | 任一新增方法跨域 mean < **8.5%**（突破 gating plan 理想标准），且三场景无灾难退化 |
| **良好** | 任一新增方法跨域 mean < **9.0%**（显著优于 Modal top2 9.45%） |
| **最低** | Voting per modal + Modal top2 跨域 mean < T0-V3（9.20%）且 < Modal top2（9.45%），证明模态和信道策略的**联合优化优于单独优化任一维度** |
| **失败** | 所有新增方法 > 9.45%，说明既有组合已达瓶颈 |

### 5.4 诊断产出

- **二维热力图**（信道策略 × 模态策略）：每个单元格 = 跨域 mean err%，最直观展示二维空间中的最优区域
- **消融瀑布图**：从 baseline 逐步叠加信道改进和模态改进，展示每步增益
- **窗级模态选择分布**（B3/M-Top2）：哪些窗选了哪两个模态，与 Modal top2 的模态选择对比

---

## 6. 实现要点

### 6.1 文件规划

| 类型 | 路径 | 说明 |
|------|------|------|
| 实验脚本 | `notebooks/scripts/chFusion_systematic_fusion.py` | 主脚本 |
| 可复用模块（扩展） | `src/ble_analysis/consensus_gating.py` | 新增 modal voting + spectral fusion 函数 |
| 可复用模块（新建） | `src/ble_analysis/systematic_fusion.py` | 二维策略网格的 pipeline 编排（可选，简单情况直接在脚本中实现） |

### 6.2 复用 API

```python
# 信道级
from ble_analysis.voting_fusion import (
    VotingConfig, _vote_one_window, vote_bpm_weighted_histogram,
    estimate_bpm_per_tone, _vote_weights,
)
from ble_analysis.chfusion import (
    ChFusionConfig, Plan2Config,
    run_multichannel_segment_filtering,
    estimate_segment_bpm_methods,        # Single/Uniform
    _find_best_channel, _energy_ratio, _peak_prominence,
    _channel_spectrum_and_q,             # 归一化谱计算
    _bpm_from_fused_spectrum,            # 融合谱 → BPM
)
from ble_analysis.consensus_gating import (
    compute_bimodality_score, compute_tone_persistence,
    _vote_filtered_tones,
)

# 模态级
# 复用 estimate_modal_best_channel_fusion 的谱融合逻辑
# 但把"选 best 信道"替换为"voting/uniform 产生的归一化谱"
```

### 6.3 关键新增函数签名

```python
def per_modal_voting_spectrum(
    ch_map: dict,
    ch_list: list,
    variable: str,          # "remote_amplitudes" | "local_amplitudes" | "phases"
    st: int, end: int, fs: float,
    cfg: ChFusionConfig,
    vcfg: VotingConfig,
) -> Tuple[np.ndarray, float, dict]:
    """对单个模态的 72 信道做 voting，返回归一化频谱 + winning BPM + 诊断信息.
    
    Returns:
        spectrum: 呼吸频带归一化功率谱 (len(band_freqs),)
        bpm: voting 选出的 BPM
        info: {conf, bimodality, winning_mass, n_effective_tones, ...}
    """
    ...

def modal_fusion_from_spectra(
    spectra: Dict[str, np.ndarray],   # {"remote": spec, "local": spec, "phase": spec}
    scores: Dict[str, float],         # per-modality quality scores (η or conf)
    weight_mode: str,                 # "equal" | "energy_ratio" | "top2_equal" | "top2_peak"
    band_freqs: np.ndarray,
    cfg: ChFusionConfig,
) -> float:
    """与现有 modal fusion 完全相同的谱融合逻辑，但输入谱来自任意信道策略（而非 single-best）."""
    ...
```

### 6.4 伪代码：主循环

```python
# Block B 核心：Voting per modal + Modal Top2 谱融合
for seg in breath_segments:
    for window in sliding_windows(seg):
        spectra = {}
        scores = {}
        for var in ["remote_amplitudes", "local_amplitudes", "phases"]:
            # 信道级：per-modal voting 产出归一化谱
            spec, bpm, info = per_modal_voting_spectrum(
                ch_maps[var], ch_lists[var], var, st, end, fs, cfg, vcfg
            )
            spectra[var] = spec
            scores[var] = info["conf"]  # 或 mean η

        # 模态级：top2 谱融合（逻辑与 Modal top2 完全一致）
        bpm_final = modal_fusion_from_spectra(
            spectra, scores, weight_mode="top2_equal",
            band_freqs=band_freqs, cfg=cfg
        )
```

### 6.5 不做的事

- 不修改现有 `voting_fusion.py` / `chfusion.py` 的核心逻辑
- 不新增场景 JSON
- 不在本 plan 做 τ/δ/K 的 exhaustive grid search（聚焦于二维策略网格的主效应）
- 不做 G7–G9（文献驱动的方法，待文献调研后单独 plan）

---

## 7. 预期产出

| 产出 | 路径 |
|------|------|
| 验证报告 | `docs/reports/systematic_modal_channel_fusion_report.md` |
| 数值结果 | `outputs/reports/systematic_fusion_results.npy` |
| 跨域汇总 | `outputs/reports/systematic_fusion_cross_domain.npy` |
| 二维热力图 | `outputs/figures/systematic_fusion_2d_heatmap.png` |
| 消融瀑布图 | `outputs/figures/systematic_fusion_ablation_waterfall.png` |
| 跨域排行榜 | `outputs/figures/systematic_fusion_leaderboard.png` |
| 模态选择对比 | `outputs/figures/systematic_fusion_modal_selection.png` |

---

## 8. 风险与保留问题

### 8.1 算法风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| Voting 产出的"归一化谱"如何定义？voting 本身不产谱 | 高 | 方案A：用 winning bin 附近 ±2 BPM 内的 tone 的平均谱；方案B：用所有 tone 的 spectrum 做 conf 加权平均（类似 soft voting） |
| Phase voting 的 η/ρ 定义与幅值不同 | 中 | phase 信号的高通滤波后 η 计算与幅值相同（`_energy_ratio`），ρ 也相同。语义差异但不影响计算 |
| 实验矩阵爆炸 | 中 | P0 核心矩阵只包含 C-Vote/C-VoteP/C-Uniform × M-Phase/M-Equal/M-η/M-Top2 ≈ 12 个新方法。加上 baseline < 25 个方法 |
| Local 模态可能拉垮任何包含它的融合 | 低 | Local 在多数场景下是最差模态；M-Top2 天然会踢出 local。如果 M-Equal/M-η 因 local 退化，这本身就是有价值的发现 |

### 8.2 保留问题

| ID | 问题 | 备注 |
|----|------|------|
| Q1 | "Voting→谱"的最佳构造方式是什么？ | `[待确认]` — 需要 ablation：winning bin 平均谱 vs conf 加权全谱 vs top-K tone 平均谱 |
| Q2 | Phase voting 的 η 和 ρ 是否应该使用与幅值相同的计算公式？ | `[待确认]` — 当前 phase η 定义与幅值一致（`_energy_ratio` on highpass），但 phase 没有 DC 分量，η 天然更高 |
| Q3 | 模态融合时 conf_vote（非 η）作为模态权重是否更优？ | `[待确认]` — voting 产出的 conf 是"票数集中度"，与 η（"信号能量集中度"）不同维度 |
| Q4 | C-Vote per modal 的计算量是否可接受？ | 三模态 × 72 tone voting / 窗 ≈ 3× 现有 T0-V3 的计算量。单场景 ~1–2 min，可接受 |

---

## 9. 验证状态

状态：**已完成**（P0 Block A/B/C）

| 字段 | 内容 |
|------|------|
| **验证状态** | 已完成（P0 Block A/B/C；P1 D1–D3 未做） |
| **实际脚本** | `notebooks/scripts/chFusion_systematic_fusion.py`、`src/ble_analysis/systematic_fusion.py` |
| **数值结果** | `outputs/reports/systematic_fusion_results.npy`、`systematic_fusion_cross_domain.npy` |
| **图表** | `outputs/figures/systematic_fusion_*.png`（4 张） |
| **报告链接** | `docs/reports/systematic_modal_channel_fusion_report.md` |
| **一句话结论** | B1 Vote→Equal modal 跨域 8.45% 为全局最优（优于 G4 8.65%），达理想标准；Vote→Top2（B3）和 Persistence 模态融合（A2/B4）未达预期。 |

**结论摘要：**

- 跨域最优：**B1 Vote→Equal** 8.45% > G4 8.65% > C2 9.15% > B2 9.16% > T0-V3 9.20% > Modal 9.45%
- 091339：B1 13.22%（与 T0-V3 13.77% 接近）；G5 12.27% 仍为单场景最优
- 095806：A1 Phase voting 5.81% 优于 T0-V3 6.84%；B3–B4 ~6.4% 接近 G6 6.55%
- 102621：B1 5.63% 最优；Modal top2 4.69% 仍单场景最优
- 理想标准（跨域 < 8.5%）**已达成**；最低标准（B3 < T0-V3 且 < Modal）**未达成**

**遗留问题：**

- Vote→Equal 有效但 Vote→Top2 无效的机制（Q1）
- Persistence 在模态融合框架下失效（A2/B4）
- P1 扩展实验（D1–D3）未执行
- B1 与 G4 门控组合待评估

---

## 给执行 Agent 的首条指令

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并严格执行：

`docs/plans/systematic_modal_channel_fusion_plan.md`

### 执行范围

**P0 必做（Block A + Block B + Block C）**：

1. **Block A（Phase voting）**：实现 A1（Phase η·ρ voting）、A2（Phase persistence voting）。复用 `_vote_one_window`，将 `variable` 参数从 `"remote_amplitudes"` 改为 `"phases"`。
2. **Block B（Voting per modal + 模态谱融合）**：这是核心新增。实现 `per_modal_voting_spectrum()` 和 `modal_fusion_from_spectra()`。对三模态各自做 C-Vote → 归一化谱 → Modal top2/Equal/η-weight 谱融合。B1/B2/B3/B4 四个方法。
3. **Block C（Uniform per modal + 模态融合）**：实现 C1/C2。复用现有 Uniform 谱计算，替换 single-best 为 uniform 谱，再做模态融合。
4. **Baseline 复现**：B0/B1/B2/B3/T0-V3/T3/G4 的结果加载既有 `.npy` 或重新计算。
5. **消融分析**：按 §5.2 的消融对比表生成表格和瀑布图。
6. **二维热力图**：信道策略（行）× 模态策略（列）× 跨域 mean（颜色）。

### 关键实现注意

- `per_modal_voting_spectrum()` 的谱构造：建议用 **conf 加权的所有 tone 频谱平均**作为初始方案（方案 B），因为实现简单且保留了完整的频谱形状信息。
- 模态融合逻辑直接复用 `estimate_modal_best_channel_fusion()` 中的谱加权和 `_bpm_from_fused_spectrum()`。
- 滑窗参数和滤波链保持与 Plan2 一致（20 s / 1 s 步 / 0.1–0.35 Hz）。
- Phase 变量做 voting 前已经是 unwrapped（由 `run_multichannel_segment_filtering` 自动处理）。

执行完成后，请返回以下材料给 Claude/DeepSeek Review：

- `docs/reports/systematic_modal_channel_fusion_report.md`
- `outputs/reports/systematic_fusion_*.npy`
- `outputs/figures/systematic_fusion_*.png`
- 关键脚本路径
- git diff 摘要
