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

Claude/DeepSeek 侧有两个模式：

1. `Research Mode`
2. `Review Mode`

用户会显式指定当前模式，例如：

```text
启用 Research Mode
```

或：

```text
启用 Review Mode
```

如果用户没有明确指定模式，应先判断任务性质：

- 如果用户要求读论文、设计方案、写 plan：进入 `Research Mode`。
- 如果用户要求看报告、判断结论、给下一步：进入 `Review Mode`。
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
9. 下一轮应该做什么。

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

# Git Rules

## 10. Git 角色分工

默认：

- Cursor Composer 负责在执行完成后准备并执行阶段性 commit。
- Claude/DeepSeek 可以建议 commit message。
- Claude/DeepSeek 除非用户明确要求，不直接执行 git commit。

------

## 11. Commit 格式

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

## 12. Claude/DeepSeek 给 Cursor Composer 的交接

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
```

------

## 13. Cursor Composer 执行后返回给 Claude/DeepSeek 的材料

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

