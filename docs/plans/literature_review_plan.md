# 文献调研计划 — Wi-Fi/BLE CSI Subcarrier 呼吸感知方法

> **来源**：Deng et al., "A statistical sensing method by utilizing Wi-Fi CSI subcarriers: Empirical study and performance enhancement", *J. Information and Intelligence*, 2024  
> **调研目标**：梳理该论文引用的关键参考文献中与本项目（BLE CS chFusion/PCA-SVD/Modal 融合）直接相关的方法，为后续算法迭代提供文献支撑  
> **日期**：2026-06-07  
> **执行人**：用户（文献下载 + 阅读 + 笔记）  
> **验证状态**：待执行

---

## 1. 调研动机

Deng et al. (2024) 提出了 "per-subcarrier 独立处理 → 统计投票融合" 的 CSI 感知框架，在呼吸检测和 BPM 估计上均优于传统的"先加权求和再处理"方法。该论文引用了 18 篇参考文献，其中若干篇与我们的 BLE CS chFusion 管线高度相关：

- **TR-BREATH [7]** 的 TRRS + eigendecomposition 与我们的 PCA/SVD 模态提取直接对标
- **Xie et al. [11]** 的 CSI ratio + PCA 与我们的 PCA 管线可直接对比
- **Wi-Breath [6]** 的 SVM 选信道提供了有监督筛选的替代思路
- **Wang et al. [10]** 的 bimodal CSI 处理了体动场景
- **Zeng et al. [15]** 的 CSI ratio 是整个领域的基础技术

本次调研的目的是：**精读这 5 篇关键文献，理清各方法的技术细节，并明确其与 BLE CS chFusion 管线的异同。**

---

## 2. 调研范围与优先级

### 2.1 第一优先级：必读（5 篇）

| # | 论文 | 发表 | 与我们的关联 | 核心待回答问题 |
|---|------|------|-------------|---------------|
| **P1** | [15] Zeng et al., "Boosting WiFi sensing performance via CSI ratio", *IEEE Pervasive Computing*, 2021 | 20(1):62–70 | CSI ratio 是 Wi-Fi 呼吸感知的**基础性技术**。如果我们的 BLE 数据是多天线采集的，这篇是必读 | ① CSI ratio 如何消除 CFO/SFO？② 我们的 BLE CS 已通过向量乘法抵消 CFO → 与 CSI ratio 是否等效？③ 是否适用于单天线 BLE 场景？ |
| **P2** | [7] Chen et al., "TR-BREATH: Time-reversal breathing rate estimation and detection", *IEEE Trans. Biomedical Engineering*, 2018 | 65(3):489–501 | 与我们的 **PCA/SVD** 模态提取直接对标：TRRS + eigendecomposition 选呼吸相关分量 | ① TRRS 如何定义与计算？② eigendecomposition 作用在什么矩阵上？③ TRRS 能否替代 η/ρ 作为信道/模态筛选指标？ |
| **P3** | [11] Xie et al., "A real-time respiration monitoring system using WiFi sensing based on the concentric circle model", *IEEE Trans. Biomedical Circuits and Systems*, 2023 | 17(2):157–168 | 直接在 **CSI ratio 上做 PCA** 提取呼吸主成分 | ① PCA 作用在什么维度（时间 × 子载波 vs 子载波 × 子载波）？② 与我们的 `PCA-Modal3` 有何结构异同？③ "concentric circle model" 是什么？ |
| **P4** | [6] Bao et al., "Wi-Breath: A WiFi-based contactless and real-time respiration monitoring scheme for remote healthcare", *IEEE J. Biomedical and Health Informatics*, 2023 | 27(5):2276–2285 | 使用 **SVM 从 CSI 幅度和相位差分中筛选**最优信号 | ① SVM 的输入特征是什么？② 训练数据如何标注？③ 有监督筛选是否本质上优于我们当前的 η/ρ 无监督筛选？ |
| **P5** | [10] Wang et al., "Resilient respiration rate monitoring with realtime bimodal CSI data", *IEEE Sensors Journal*, 2020 | 20(17):10187–10198 | 体动场景 + **中位数融合**，恰好是我们当前的薄弱环节 | ① "bimodal CSI" 指什么（两个频段？两设备？）② 如何在体动下选择对呼吸敏感的信号簇？③ 中位数融合与我们 top2 modal 有何可比性？ |

### 2.2 第二优先级：选读（2 篇）

| # | 论文 | 说明 |
|---|------|------|
| **S1** | [8] Liu et al., "Contactless respiration monitoring via off-the-shelf WiFi devices", *IEEE Trans. Mobile Computing*, 2016 | 被 Deng et al. 重点批评的"per-subcarrier 正弦拟合 + 加权合成"代表。读它的目的是**理解被淘汰的方法错在哪里** |
| **S2** | [16] Ma et al., "WiFi sensing with channel state information: A survey", *ACM Computing Surveys*, 2019 | 领域综述，帮助定位我们的方法在整个文献谱系中的位置 |

### 2.3 暂不下载

- [1] ITU-R Report — 频谱监管，无关
- [2] Tan et al. 综述 — 可后续
- [3]/[9] Zhang et al. BreathTrack — 偏传统
- [4] Ahmed et al. — 手势识别，领域不同
- [12] Zhuo et al. — 与 [8] 类似
- [13]/[14] Zhang/Gu et al. — 方差最大子载波选择，可用作 baseline 但非核心
- [17] Kuang et al. — 纯 OFDM 物理层，太底层
- [18] Deng et al. — 作者之前的 PLL 工作，仅是他们估计器的工程细节

---

## 3. 每篇论文的阅读指南

### 3.1 统一阅读框架

对每篇 P1–P5 论文，按以下 checklist 记录：

```
□ 论文标题、作者、发表信息
□ 一句话核心贡献
□ 信号模型（输入是什么变量？几通道？如何预处理？）
□ 核心算法步骤（用伪代码或流程图概括）
□ 与我们 chFusion/PCA-SVD/Modal 管线的结构对照
□ 可直接借鉴的技术点（具体到函数/参数层面）
□ 不适用于 BLE CS 的地方（并标注原因）
□ 实验设置（场景数、人数、体动有无、ground truth 来源）
□ 与我们方法的关键数字对比（如有可比结果）
```

### 3.2 对照矩阵（读后填写）

| 论文方法 | 对应我们的方法 | 结构相同点 | 结构不同点 | 可移植性 |
|----------|---------------|-----------|-----------|---------|
| [7] TR-BREATH | PCA/SVD Modal | | | |
| [11] PCA on CSI ratio | PCA-Modal3 | | | |
| [6] Wi-Breath SVM | η/ρ 选信道 | | | |
| [10] Bimodal CSI | Modal top2 | | | |
| [15] CSI ratio | BLE CS 向量乘法 | | | |

---

## 4. 预期产出

| 产出 | 路径 | 说明 |
|------|------|------|
| 文献阅读笔记 | `docs/papers/reading_notes/` | 每篇 P1–P5 一个 .md 文件，按 §3.1 checklist 填写 |
| 对照矩阵 | `docs/papers/reading_notes/method_comparison_matrix.md` | §3.2 的汇总表 |
| 后续 plan 建议 | `docs/papers/reading_notes/next_steps.md` | 基于调研结果，建议哪些技术点值得做实验验证 |

---

## 5. 执行步骤

1. **下载** P1–P5 五篇论文 PDF，放入 `docs/papers/`
2. **按顺序精读**：P1 (CSI ratio) → P2 (TR-BREATH) → P3 (PCA on CSI ratio) → P4 (Wi-Breath) → P5 (Bimodal CSI)
3. **每读完一篇**：写 `docs/papers/reading_notes/{paper_short_name}.md`
4. **全部读完后**：填写对照矩阵 + 写下一步建议
5. **将产出交回**给 Claude/DeepSeek Review，Review 后可生成下一轮实验 plan

---

## 6. 风险与注意事项

| 风险 | 说明 |
|------|------|
| 论文无法下载 | 部分 IEEE 论文需要机构订阅；可尝试 arXiv 预印本或 ResearchGate |
| 方法与 BLE CS 不完全对应 | Wi-Fi CSI 有 30–52 子载波（312.5 kHz 间隔），BLE CS 只有 3 广播信道（2.4 GHz 频段）和 72 tone（1 MHz 间隔）。物理层差异可能导致方法不可直接移植 |
| 数学符号体系不同 | 需在笔记中统一翻译成项目的 `η/ρ/BPM/Modal` 符号体系 |
| 阅读时间预估 | P1–P5 五篇论文，每篇预计 1–2 小时精读 + 0.5 小时笔记 = 总计约 10–15 小时 |

---

## 7. 附加：Deng et al. 方法概要

（供文献调研时对照参考）

| 维度 | Deng et al. (2024) |
|------|-------------------|
| 核心思想 | Per-subcarrier 独立检测/估计 → 统计投票融合 |
| 理论贡献 | 证明传统"加权求和"不能有效抑制 ICI 噪声（因为 ICI 跨子载波强相关） |
| 检测 | 时频分析检测器 + voting threshold = 0.3M |
| 估计 | 每 subcarrier 独立 PLL 测频 + 呼吸带峰值搜索 → 统计融合 |
| 数据集 | 30 组数据，单人静止，802.11n 30 subcarrier |
| Baseline | 等权求和、最大绝对值子载波、PCA 选子载波 |
| 局限 | Voting threshold 无理论最优、无多场景/体动验证、未与 learning-based 方法对比 |

与本项目的对应关系：
- Wi-Fi subcarrier → BLE tone（72 个，更密集）
- Per-subcarrier detection → `Single`（单信道估计）
- Weighted sum → `Uniform`（等权融合）
- PCA-based selection → `PCA/SVD` 模态选择
- Voting fusion → `Modal top2` / `chFusion`（我们的融合策略已接近此方向）

---

## 8. 验证状态

| 字段 | 内容 |
|------|------|
| **验证状态** | 待执行（由用户下载论文并阅读） |
| **实际产出** | — |

---

## 给执行人的首条指令

本 plan 由用户（而非 Cursor Composer）执行。请按 §5 步骤：

1. 先尝试从 IEEE Xplore / arXiv / ResearchGate 下载 P1–P5 五篇论文
2. 按 P1 → P5 顺序阅读
3. 每篇写阅读笔记到 `docs/papers/reading_notes/`（目录需新建）
4. 读完后填写对照矩阵
5. 将结果交回给 Claude/DeepSeek Review
