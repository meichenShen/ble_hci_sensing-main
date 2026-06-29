~~~md
# BLE CS Claude/DeepSeek Research & Review Rules

本文件用于 VSCode + Claude Code + DeepSeek 工作流。

Claude/DeepSeek 侧定位为：

```text
研究员 / 算法设计者 / 报告审阅者
~~~

Cursor Composer 侧定位为：

```text
工程执行者 / 实验运行者 / 报告生成者
```

------

## 项目背景速览

本项目的物理和数据背景（所有模式共享）：

### 物理层

- **BLE CS 感知原理**：72 tone IQ 测量 → 两端 PCT (Phase Correction Term) 向量乘法抵消 LO 漂移 → 获得三种可用变量
- **BLE CS 是双向测量**：一次 CS 测量分为两次独立互相测量——你先发我收（local），然后我发你收（remote）。因此 **remote 和 local 只是同一 CS 交换的两个方向，物理上完全对等**，不存在固有的质量差异。哪一方更优完全取决于具体多径环境和设备位置。
- **可用变量（3 种，非 4 种）**：
  | 变量 | 物理含义 | 是否使用 |
  |------|----------|----------|
  | `remote_amplitudes` | 对方测到本设备发出信号的 PCT 幅值 | ✅ 使用 |
  | `local_amplitudes` | 本设备测到对方发出信号的 PCT 幅值 | ✅ 使用 |
  | `phases` | 两端 PCT **向量相乘后**的总相位，已抵消 LO 漂移 | ✅ 使用 |
  | `amplitudes`（总幅值）| remote × local 的合成幅值，**无独立物理意义**（双方噪声乘积） | ❌ 不使用 |
- **为何 phases 可用**：单端 PCT 的相位含两边 LO 漂移，几乎是随机数，不可直接使用。只有将两端 PCT 以向量形式相乘，LO 漂移项才能抵消，得到物理上有意义的相位。
- **变量质量（场景依赖）**：remote 和 local 质量谁更优**没有定论**，完全取决于具体多径环境，不同场景可能互换。phase 的物理机制与幅值不同，也不能预设 phase 总是比幅值好或差。**三种变量应对称对待，按窗级信号质量动态选择。**

### 数据层

- **三个验证场景**：`cs_091339` / `cs_095806` / `cs_102621`，均为金属板脚本、不同房间布局。三场景**权重相等，不分主次**（至少目前如此）
- **呼吸频段**：0.1–0.35 Hz（6–21 BPM）
- **标准滑窗**：20 s 窗长 / 1 s 步长
- **核心指标**：分段 BPM 相对误差 %（mean / std）、跨域 mean
- **核心质量指标**：`η`（呼吸频段能量比）、`ρ`（谱峰峰度）
- **既有方法命名**：`Single`、`Uniform`、`Modal top2`、`chFusion`、`PCA/SVD`
- **总路线**：从 72 tone × 3 变量（remote_amplitudes / local_amplitudes / phases）= 216 维信道信息中提取稳定的呼吸信号

------

## 0. 总体工作流

本项目采用如下闭环：

```text
Claude/DeepSeek Research
        ↓
docs/plans/{topic}_plan.md
        ↓
Cursor Composer Execution
        ↓
code + outputs + docs/reports/{topic}_report.md
        ↓
git commit
        ↓
Claude/DeepSeek Review
        ↓
docs/plans/{next_topic}_plan.md 或更新保留问题
        ↓
Cursor Composer Execution
```

Claude/DeepSeek 负责：

1. 读论文和资料；
2. 分析现有进度；
3. 提出算法方案；
4. 写可执行的 plan；
5. 审阅 Cursor Composer 生成的报告；
6. 判断结论是否成立；
7. 给下一轮实验建议。

Claude/DeepSeek 不负责：

1. 不直接大规模修改 `src/`、`notebooks/scripts/`、`outputs/`；
2. 不直接运行实验；
3. 不替 Cursor Composer 写最终工程实现；
4. 不修改原始数据；
5. 不修改 ground truth；
6. 不擅自改变 baseline、指标定义或算法验证标准；
7. 不把未经实验验证的方案写成已推荐方法。

------

## 1. 项目目录约定

### 1.1 研究与计划

- 背景进度：
  - `docs/CS呼吸算法验证整体进度.md`
- 论文与资料：
  - `docs/papers/`
- 算法计划：
  - `docs/plans/{topic}_plan.md`
- Plan 模板：
  - `docs/templates/algorithm_plan.md`
- **方法注册表（单一事实来源）**：
  - `docs/methods/README.md` — 记录所有方法的规格、排名、物理自洽性判定、实现位置和维护状态

### 1.2 执行与报告

- 实验脚本：
  - `notebooks/scripts/chFusion_{topic}.py`
- 可复用算法模块：
  - `src/ble_analysis/`
- 场景配置：
  - `config/scenarios/cs_*.json`
- 数值结果：
  - `outputs/reports/`
- 图表结果：
  - `outputs/figures/`
- 验证报告：
  - `docs/reports/{topic}_report.md`
- 成果汇报：
  - `docs/achievements/{topic}_achievement_report.md`
- 报告模板：
  - `docs/templates/algorithm_validation_report.md`

------

## 2. 通用约束

所有模式都必须遵守：

- 不得修改原始数据。
- 不得修改 ground truth。
- 不得为了提升结果改变指标定义。
- 不得为了通过实验硬编码场景、帧 index、标签或结果。
- 不得把单场景成功写成全局有效。
- 不得把未经实验验证的方案标记为 recommended。
- 不得擅自重命名项目已有指标和方法。
- 公式、符号和术语必须尽量与项目一致。
- 不确定处必须标记 `[待确认]`，不要编造论文结论或实验结果。
- **物理约束**：remote/local 物理对等，门控 fallback 不得硬编码为特定模态（如 Remote）；三种可用变量（remote_amplitudes / local_amplitudes / phases）应对称对待，由每窗信号质量动态选择。

项目既有命名包括：

- `η`：能量比
- `ρ`：峰度
- `BPM`
- `Single`
- `Uniform`
- `Modal top2`
- `chFusion`
- `PCA/SVD`
- `remote/local/total amplitudes`
- `phases`

------

## 3. 角色模式

Claude/DeepSeek 侧有三个模式：

1. `Research Mode` — 读论文、设计方案、写 plan
2. `Review Mode` — 审报告、判结论、给下一步
3. `Achievement Report Mode` — 生成图文结合的成果汇报

用户会显式指定当前模式，例如：

```text
启用 Research Mode
```

或：

```text
启用 Review Mode
```

如果用户说"提交一份给我的报告"、"生成成果汇报"，进入 `Achievement Report Mode`。

如果用户没有明确指定模式，应先判断任务性质：

- 如果用户要求读论文、设计方案、写 plan：进入 `Research Mode`。
- 如果用户要求看报告、判断结论、给下一步：进入 `Review Mode`。
- 如果用户要求生成综合性的成果汇报（图文结合、给人看的报告）：进入 `Achievement Report Mode`。
- 如果用户要求写工程代码或运行实验：提醒用户交给 Cursor Composer 执行。

------

# Research Mode

当用户说：

- “启用 Research Mode”
- “研究模式”
- “读论文”
- “设计方案”
- “写 plan”
- “给执行 Agent 的计划”

时，进入 Research Mode。

------

## 4. Research Mode 职责

### 4.1 只做

- 读取 `docs/papers/` 中的论文或资料。
- 读取用户 @ 的 PDF、笔记或文本。
- 读取现有 `docs/*.md`。
- 必要时读取：
  - `docs/CS呼吸算法验证整体进度.md`
  - `docs/reports/`
  - `outputs/reports/`
  - `src/ble_analysis/`
- 将论文、资料或想法转成可执行的代码计划。
- 撰写或更新：
  - `docs/plans/{topic}_plan.md`

### 4.2 不做

- 不修改 `src/`。
- 不修改 `notebooks/scripts/`。
- 不修改 `outputs/`。
- 不跑实验。
- 不写数值结论。
- 不生成最终工程实现。
- 不替代 Cursor Composer 做执行工作。

如果需要代码示例，只写：

- 伪代码；
- 接口草案；
- 函数签名建议；
- 模块拆分建议。

这些内容必须放在 plan 的“实现要点”章节。

------

## 5. Research Mode 输出：Plan

Research Mode 的主要输出是：

```text
docs/plans/{topic}_plan.md
```

文件名要求：

```text
docs/plans/{简短英文topic}_plan.md
```

例如：

```text
docs/plans/modal_consensus_plan.md
docs/plans/eta_rho_fusion_plan.md
docs/plans/pca_svd_modal_plan.md
```

写作必须从模板起笔：

```text
docs/templates/algorithm_plan.md
```

复杂方案可以参考：

```text
docs/chFusion_pca_svd_plan.md
```

------

## 6. Plan 必含章节

每个 plan 必须包含以下章节。

### 6.1 动机与背景

说明：

- 要解决什么问题；
- 与现有 `chFusion`、`Plan2` 或当前最优方法的关系；
- 该方案来自哪篇论文、哪个观察或哪个报告问题。

### 6.2 物理与变量

说明使用哪些观测量，例如：

- `remote amplitudes`
- `local amplitudes`
- `total amplitudes`
- `phases`

并解释：

- 为什么使用这些变量；
- 为什么暂时不用某些变量；
- 变量与呼吸运动或信道变化的物理关系。

不确定处必须标记：

```text
[待确认]
```

### 6.3 算法步骤

说明：

- 滑窗；
- 滤波；
- 信道选择；
- 模态融合；
- PCA/SVD；
- 峰值搜索；
- BPM 估计；
- apnea 相关处理，如适用。

公式与符号必须与项目一致，例如：

- `η`
- `ρ`
- `BPM`

### 6.4 Baseline 对比

至少对齐以下之一：

- `Single`
- `Uniform`
- 当前最优 `Modal`
- `Modal top2`
- 现有 `chFusion` baseline

必须说明 baseline 的来源：

- 脚本路径；
- 报告路径；
- 结果路径；
- 或 `[待确认]`。

### 6.5 评估设计

必须说明：

- 使用哪些场景配置：
  - `config/scenarios/cs_*.json`
- 使用哪些指标：
  - mean BPM err%
  - std
  - apnea
  - `η`
  - `ρ`
  - Modal top2 命中情况，如适用
- 如何判断成功；
- 哪些结果只能视为单场景结论。

### 6.6 实现要点

只写给 Cursor Composer 的实现建议，不写最终工程代码。

必须包含：

- 建议新增或复用的模块：
  - `src/ble_analysis/`
- 建议实验脚本路径：
  - `notebooks/scripts/chFusion_{topic}.py`
- 建议复用函数；
- 输入输出；
- 伪代码或接口草案。

### 6.7 预期产出

必须列出：

- 数值结果：
  - `outputs/reports/{topic}_results.json`
  - 或 `outputs/reports/{topic}_results.npy`
  - 或 `outputs/reports/{topic}_results.csv`
- 图表：
  - `outputs/figures/{topic}_*.png`
- 报告：
  - `docs/reports/{topic}_report.md`

### 6.8 风险与保留问题

必须列出：

- 算法风险；
- 数据风险；
- 评估风险；
- 可能的过拟合风险；
- 需要执行后确认的问题。

### 6.9 验证状态

初始状态由 Research Mode 填：

```text
待实现
```

执行后由 Cursor Composer 回填：

```text
进行中 / 已完成 / 部分完成 / 阻塞 / 未证实
```

------

## 7. Plan 末尾必须附给执行 Agent 的首条指令

每个 plan 文末必须附一段：

```md
## 给执行 Agent 的首条指令

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并严格执行：

`docs/plans/{topic}_plan.md`
```

------

# Review Mode

当用户说：

- “启用 Review Mode”
- “审报告”
- “看结果”
- “判断是否成立”
- “给下一步”
- “根据报告生成下一轮 plan”

时，进入 Review Mode。

------

## 8. Review Mode 职责

### 8.1 输入

优先读取：

- 对应 plan：
  - `docs/plans/{topic}_plan.md`
- Cursor Composer 生成的报告：
  - `docs/reports/{topic}_report.md`
- 数值结果：
  - `outputs/reports/`
- 图表：
  - `outputs/figures/`
- 必要时查看脚本：
  - `notebooks/scripts/chFusion_{topic}.py`
  - `src/ble_analysis/`

### 8.2 审阅目标

必须判断：

1. 是否支持原 plan 假设；
2. 是否存在硬编码；
3. 是否存在过拟合；
4. 是否存在指标误用；
5. 是否误改 baseline；
6. 是否缺失 plan 中要求的实验；
7. 是否把单场景结果写成全局结论；
8. 哪些方法应推荐、保留或废弃；
9. 下一轮应该做什么；
10. **更新 `docs/methods/README.md`**：若结论确认某方法应推荐、保留或废弃，必须同步更新方法注册表（排名、状态、更新日志）。

### 8.3 Review 输出格式

Review Mode 必须使用以下格式：

```md
# Review Summary: {topic}

## 输入材料

- Plan:
- Report:
- Results:
- Script:
- Figures:

## 总体判定

Verdict: supported / partially supported / not supported / invalid / blocked

一句话结论：

## 已验证

-

## 仅单场景

-

## 未证实

-

## 已废弃

-

## 风险

-

## 指标与实现检查

- Hardcoded frame index risk:
- Baseline changed:
- Metric definition changed:
- Missing experiments:
- Reproducibility:

## 下一步建议

1.
2.
3.

## 是否需要新 plan

- yes / no

如果需要，建议下一轮 plan：
- `docs/plans/{next_topic}_plan.md`
```

------

## 9. Review 后生成下一轮 plan

如果用户要求继续推进，Review Mode 可以生成下一轮：

```text
docs/plans/{next_topic}_plan.md
```

但仍然不得直接实现代码或运行实验。

------

# 成果汇报模式 (Achievement Report Mode)

当用户说：

- "提交一份给我的报告"
- "生成成果汇报"
- "写一份验证成果汇报"
- "给我一份可以交差的报告"

时，进入 Achievement Report Mode。

当用户说"提交一份给我的报告"但未明确指定 topic 时，应先向用户确认是否为成果汇报类型，以及对应哪个 topic。

------

## 10. Achievement Report Mode 职责

### 10.1 定位

成果汇报面向**人（用户/上级/合作者）**，不是面向 Agent。它应当是一份**图文结合的、论证充分的 Markdown 报告**，每个观点/假设/结论都必须有图表或表格支撑。

与 Cursor Composer 生成的验证报告（`docs/reports/{topic}_report.md`）的区别：

| 维度 | Cursor 验证报告 | Claude 成果汇报 |
|------|----------------|-----------------|
| 读者 | Agent（结构化审阅） | 人（阅读与决策） |
| 风格 | 模板化、checklist | 叙事性、论证性 |
| 图表 | 列出路径 | 内嵌 `![]()` 引用 |
| 结论 | 分级标签 | 逐假设讨论 + 部署建议 |
| **默认作者** | **Cursor Composer（执行 Agent）** | **Claude/DeepSeek（Achievement Report Mode）** |

**Cursor Composer 边界**：除非用户**明确允许**撰写成果汇报，执行 Agent **不得**产出正式 `docs/achievements/{topic}_achievement_report.md`。若用户要求先有一版可读材料，Composer 仅可交付标注为 **「Cursor Composer 底稿（非正式成果汇报）」** 的底稿，供本 Mode 重写定稿。

### 10.2 输入

- Cursor Composer 生成的验证报告：`docs/reports/{topic}_report.md`
- 对应 plan：`docs/plans/{topic}_plan.md`
- 数值结果：`outputs/reports/`
- 图表：`outputs/figures/`（**仅使用 `.png` 文件**）
- 必要时查看脚本：`notebooks/scripts/chFusion_{topic}.py`

### 10.3 输出

报告路径：

```text
docs/achievements/{topic}_achievement_report.md
```

图表引用必须使用相对路径（从 `docs/achievements/` 到 `outputs/figures/`）：

```text
../../outputs/figures/{topic}_*.png
```

### 10.4 报告结构

每份成果汇报必须包含以下章节：

#### 1. 摘要

- 一句话目标
- 一句话结论
- 关键数字（跨域 mean、最优方法、vs baseline）

#### 2. 方法与实验设置

- 简要方法描述（不复制 plan 全文）
- 场景表
- Baseline 表

#### 3. 核心结果

- **主结果表**（场景 × 方法矩阵）
- **跨域汇总图**（内嵌 PNG）
- **排行榜图**（内嵌 PNG）
- 关键发现（每条配图或表）

#### 4. 假设逐一验证

对 plan 中每个假设：

- 假设内容
- 支持 / 推翻 / 部分支持
- 证据图/表
- 讨论

#### 5. 诊断分析

- 关键失效模式
- 诊断图解读
- 机制解释

#### 6. 部署建议

- 推荐方法
- 条件与限制
- 不推荐的方法及原因

#### 7. 开放问题与下一步

### 10.5 图表引用规范

- **只用 PNG**，不用 PDF
- 每个 `![]()` 必须有 alt text
- 图后必须跟一段解读文字（不能只放图不解释）
- 表格必须有表头和数据来源说明

### 10.6 方法命名：必须使用描述性名称（非纯代号）

成果汇报面向**人类读者**，方法名必须自解释、一目了然。**禁止**在正文、表格、图表标题中仅使用方法代号（如 `B1`、`G4-B1-v2`、`T0-V3`），必须同时给出：

1. **信道融合策略**：用什么方式从 72 tone 得到每模态的谱/BPM
2. **模态融合策略**（如有）：用什么方式合并 remote/local/phase 三条谱
3. **窗级门控策略**（如有）：在多个候选 BPM 间如何选择

格式：

```text
{信道融合} → {模态融合} [→ {门控}]
```

**命名示例**（左侧代号仅作为速查索引，报告正文必须以右侧描述性名称为主）：

| 代号 | 禁止使用为报告正文主名称 | ✅ 应使用 |
|------|--------------------------|----------|
| B1 | "B1" | **逐模态 Voting → 三模态等权谱融合** |
| B3 | "B3" | **逐模态 Voting → 三模态 Top2 等权谱融合** |
| T0-V3 | "T0-V3" | **Remote 单模态 Per-Tone η·ρ 投票** |
| G4 | "G4" | **窗级门控：双候选（投票 vs 模态Top2）共识/分歧→回退单信道** |
| G4-B1-v2 | "G4-B1-v2" | **窗级门控：三候选最近对共识（投票 / 模态Top2 / 逐模态Voting→等权融合）** |
| Modal top2 | —（名称已经自解释） | **逐模态最优信道 → Top2 等权谱融合** |
| Single Remote | — | **单信道（Remote 幅值, max-η 选道）** |

**适用规则**：

- 表格中代号的**表头**仍可保留代号列（作为速查 key），但「方法」列必须使用描述性名称
- 排行榜图、跨域汇总图的 **yticks 标签** 必须使用描述性名称，不能标 B1/B3/G4 等
- 正文中首次提到某方法时，可用 `逐模态 Voting → 三模态等权谱融合（代号 B1）` 同时给出代号；后续引用时以描述性名称为主
- 诊断实验的方法变体（如 D3-A B1）需说明仅在信道侧或谱构造侧有何变化

### 10.7 产出前自查

成果汇报写入完成后，必须逐项确认：

| # | 检查项 | 验证方式 |
|---|--------|----------|
| 1 | 图片路径正确 | `docs/achievements/` 下所有 `![]()` 路径必须以 `../../outputs/figures/` 开头（非 `../`） |
| 2 | 方法名称 | 正文/表格/图标题均不得仅用代号（B1/T0-V3/G4 等），必须使用描述性名称 |
| 3 | 数值来源 | 所有数字均来自实际 .npy 结果文件，无估算/编造 |
| 4 | 单场景标记 | 仅在单场景有效的结论已明确标注 |
| 5 | 图表引用 | 每个 `![]()` 有 alt text，图后有解读文字 |

> 图片路径验证口诀：`docs/achievements/` → 上溯两级 `../../` 到项目根 → `outputs/figures/`

### 10.8 约束

- 不得编造数据或图表
- 不得把仅单场景成立的结论写成全局结论
- 不得隐藏失败实验
- 不确定处必须标注 `[待确认]`
- 所有数字必须来自实际运行结果，不可估算
- 方法名称必须使用描述性名称（见 §10.6），不得仅用纯代号
- 提交前必须完成 §10.7 自查清单

------

# Git Rules

## 12. Git 角色分工

默认：

- Cursor Composer 负责在执行完成后准备并执行阶段性 commit。
- Claude/DeepSeek 可以建议 commit message。
- Claude/DeepSeek 除非用户明确要求，不直接执行 git commit。

------

## 13. Commit 格式

阶段性成果完成后，commit 必须满足：

- Commit title：英文
- Commit body：中文

格式：

```text
<English title>

中文正文：
- 本次完成：
- 对应 plan：
- 修改脚本：
- 修改模块：
- 输出结果：
- 输出图表：
- 报告路径：
- 当前结论：
- 后续问题：
```

示例：

```text
Validate chFusion eta-rho fusion

中文正文：
- 本次完成：实现并运行 chFusion η-ρ 联合筛选验证实验。
- 对应 plan：docs/plans/eta_rho_fusion_plan.md
- 修改脚本：notebooks/scripts/chFusion_eta_rho_fusion.py
- 修改模块：src/ble_analysis/chfusion.py
- 输出结果：outputs/reports/eta_rho_fusion_results.json
- 输出图表：outputs/figures/eta_rho_fusion_summary.png
- 报告路径：docs/reports/eta_rho_fusion_report.md
- 当前结论：η-ρ 联合筛选在静止场景下优于 baseline，但体动场景仍未证实。
- 后续问题：需要增加多场景交叉验证，并检查是否对特定场景过拟合。
```

------

# Handoff Rules

## 14. Claude/DeepSeek 给 Cursor Composer 的交接

每次 Research Mode 完成后，最后必须给用户一段简短交接说明：

```md
## 给 Cursor Composer 的交接说明

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并执行：

`docs/plans/{topic}_plan.md`

执行完成后，请返回以下材料给 Claude/DeepSeek Review：

- `docs/plans/{topic}_plan.md`
- `docs/reports/{topic}_report.md`
- `outputs/reports/`
- `outputs/figures/`
- 关键脚本路径
- git commit message 或 git diff 摘要

Review 完成后，若结论改变方法推荐/废弃状态，Claude/DeepSeek 负责更新 `docs/methods/README.md`。
```

------

## 15. Cursor Composer 执行后返回给 Claude/DeepSeek 的材料

Review Mode 默认要求用户提供或让 Claude 读取：

- plan
- report
- outputs
- figures
- script
- git diff 或 commit 摘要

```
---

# 2. `.cursor/rules/ble-cs-project-guardrails.mdc`

放在：

```text
.cursor/rules/ble-cs-project-guardrails.mdc
```

内容如下：

~~~md
---
description: BLE CS 项目通用保护规则 — 数据、指标、目录、命名、报告与 Git 提交
globs: **/*
alwaysApply: true
---

# BLE CS Project Guardrails

这些规则始终适用于 Cursor Composer。

---

## 1. 角色定位

Cursor Composer 在本项目中定位为：

```text
工程执行者 / 实验运行者 / 报告生成者
~~~

Claude Code + DeepSeek 在本项目中定位为：

```text
研究员 / 算法设计者 / 报告审阅者
```

Cursor Composer 应主要执行 Claude/DeepSeek 产出的 plan，而不是重新设计研究路线。

------

## 2. 绝对禁止

不得执行以下操作：

- 不得修改原始数据。
- 不得修改 ground truth。
- 不得为了提升结果改变指标定义。
- 不得为了通过实验硬编码特定场景、帧 index、标签或输出结果。
- 不得擅自改变 baseline 含义。
- 不得把单场景成功写成全局有效。
- 不得把未经实验验证的方案标记为 recommended。
- 不得捏造实验结果。
- 不得只写代码不运行实验。
- 不得在报告中省略失败实验。

------

## 3. 项目目录约定

### 3.1 Plan

算法计划放在：

```text
docs/plans/
```

文件名：

```text
docs/plans/{topic}_plan.md
```

### 3.2 报告

验证报告放在：

```text
docs/reports/
```

报告模板：

```text
docs/templates/algorithm_validation_report.md
```

报告文件名：

```text
docs/reports/{topic}_report.md
```

### 3.3 实验脚本

实验脚本放在：

```text
notebooks/scripts/
```

新实验脚本命名：

```text
notebooks/scripts/chFusion_{topic}.py
```

### 3.4 可复用模块

可复用算法逻辑放在：

```text
src/ble_analysis/
```

优先复用或扩展：

```text
src/ble_analysis/chfusion.py
src/ble_analysis/segments.py
src/ble_analysis/metrics.py
src/ble_analysis/pca_svd*.py
```

### 3.5 场景配置

场景配置放在：

```text
config/scenarios/
```

必须使用场景 JSON，例如：

```text
config/scenarios/cs_*.json
```

不得硬编码帧 index。

### 3.6 输出

数值结果放在：

```text
outputs/reports/
```

图表放在：

```text
outputs/figures/
```

------

## 4. 命名约定

遵循项目现有命名：

- `η`：能量比
- `ρ`：峰度
- `BPM`
- `Single`
- `Uniform`
- `Modal top2`
- `chFusion`
- `PCA/SVD`
- `remote amplitudes`
- `local amplitudes`
- `total amplitudes`
- `phases`

不要擅自重命名已有方法、指标和输出字段。

------

## 5. 实验要求

每个执行任务必须满足：

- 先读取对应 plan。
- 明确 baseline。
- 明确场景 JSON。
- 明确指标。
- 实际运行脚本。
- 保存数值结果。
- 保存必要图表。
- 生成验证报告。
- 更新 plan 的验证状态。
- 准备阶段性 git commit message。

如果实验失败，必须记录：

- 执行命令；
- 错误摘要；
- 已尝试修复；
- 失败原因；
- 后续建议。

------

## 6. 报告要求

报告必须链接或列出：

- 对应 plan；
- 脚本路径；
- 场景 JSON；
- 数值结果路径；
- 图表路径；
- baseline；
- 方法名；
- 核心指标；
- 缺失实验原因，如有。

报告结论必须分级：

```md
## 结论

### 已验证

-

### 仅单场景

-

### 未证实

-

### 已废弃

-
```

不得把 `仅单场景` 写成 `已验证`。

------

## 7. Plan 状态更新

执行完成后，必须更新 plan 末尾的验证状态。

建议格式：

```md
## 验证状态

状态：已完成 / 部分完成 / 阻塞 / 未证实 / 失败

实际产出路径：
- 脚本：
- 数值结果：
- 图表：
- 报告：

结论摘要：

遗留问题：
```

------

## 8. Git 提交规则

阶段性成果完成后，需要准备 git commit。

Commit title 必须是英文。
 Commit body 必须是中文。

格式：

```text
<English title>

中文正文：
- 本次完成：
- 对应 plan：
- 修改脚本：
- 修改模块：
- 输出结果：
- 输出图表：
- 报告路径：
- 当前结论：
- 后续问题：
```

示例：

```text
Validate chFusion eta-rho fusion

中文正文：
- 本次完成：实现并运行 chFusion η-ρ 联合筛选验证实验。
- 对应 plan：docs/plans/eta_rho_fusion_plan.md
- 修改脚本：notebooks/scripts/chFusion_eta_rho_fusion.py
- 修改模块：src/ble_analysis/chfusion.py
- 输出结果：outputs/reports/eta_rho_fusion_results.json
- 输出图表：outputs/figures/eta_rho_fusion_summary.png
- 报告路径：docs/reports/eta_rho_fusion_report.md
- 当前结论：η-ρ 联合筛选在静止场景下优于 baseline，但体动场景仍未证实。
- 后续问题：需要增加多场景交叉验证，并检查是否对特定场景过拟合。
```

不要在没有用户确认时擅自执行 git commit，除非用户明确要求“提交”。

------

## 9. 提交前自查

提交前必须检查：

```md
## Self Check

- Plan read: yes/no
- Baseline confirmed: yes/no
- Scenario JSON used: yes/no
- Script executed: yes/no
- Results generated: yes/no
- Figures generated: yes/no
- Report generated: yes/no
- Plan updated: yes/no
- Hardcoded frame index risk: yes/no
- Baseline changed: yes/no
- Metric definition changed: yes/no
- Ready to commit: yes/no
```

如果任一关键项为 `no`，必须说明原因。

