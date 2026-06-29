# 双 Agent 工作流（研究 / 执行）

在 Cursor 中开 **两个 Agent 对话窗口**，分别启用不同 rule，用仓库文件交接。

## 窗口配置

| 窗口 | 启用 Rule | 主要目录 |
|------|-----------|----------|
| 研究 | `BLE CS 研究 Agent` | `docs/papers/`、`docs/plans/` |
| 执行 | `BLE CS 执行 Agent` | `notebooks/scripts/`、`src/ble_analysis/`、`docs/reports/` |

在 Chat 的 **Rules** 面板勾选对应 rule；或打开上述目录下的文件时 rule 会自动关联（glob）。

## 目录约定

```
docs/
  papers/          # PDF、论文笔记（研究 Agent 阅读）
  plans/           # *_plan.md（研究 Agent 产出 → 执行 Agent 输入）
  reports/         # *_report.md（执行 Agent 产出）
  templates/       # plan / 报告模板
outputs/
  figures/         # 图
  reports/         # .npy 等数值结果
```

## 典型一轮

1. **研究窗口**：@ 论文 → 产出 `docs/plans/xxx_plan.md`
2. **执行窗口**：「请按 `docs/plans/xxx_plan.md` 实现并写报告」
3. **执行窗口**：跑脚本 → `docs/reports/xxx_report.md` + 更新 plan 验证状态
4. 若结论需新方向 → 回到 **研究窗口** 修订或新建 plan

## 首条消息模板

**研究窗口：**

> 请阅读 `@docs/papers/...`，按 `@docs/templates/algorithm_plan.md` 写 `docs/plans/xxx_plan.md`，不要写实现代码。

**执行窗口：**

> 请按 `@docs/plans/xxx_plan.md` 实现实验，使用 `@docs/templates/algorithm_validation_report.md` 写 `docs/reports/xxx_report.md`。
