# {算法名称} — 验证报告

> **Plan**：[`docs/plans/{topic}_plan.md`](../plans/{topic}_plan.md)  
> **脚本**：`notebooks/scripts/{script}.py`（核心模块：`src/ble_analysis/{module}.py`）  
> **场景**：`config/scenarios/{scenario}.json`（可列多个）  
> **日期**：{YYYY-MM-DD}  
> **状态**：{已完成 / 部分完成 /  blocked}

---

## 1. 目标与假设

（1–3 句）本实验要验证 plan 中的哪条假设；成功标准是什么（例如跨场景 mean BPM err% < X%）。

| ID | 假设 | Plan 引用 |
|----|------|-----------|
| H1 | … | §x |

---

## 2. 方法摘要

与 plan 一致即可；若实现有偏差，在此说明。

| 项目 | 内容 |
|------|------|
| 观测量 | remote / local / total amp, phase, … |
| 信道融合 | Single / Uniform / η-weight / PCA / … |
| 模态融合 | 无 / Modal top2 / … |
| 滑窗与寻峰 | 窗长、步长、呼吸频段、寻峰规则 |

---

## 3. 实验设置

| 场景 ID | 数据文件 | 备注 |
|---------|----------|------|
| cs_091339 | `sampleData/...` | 金属板脚本 |
| … | … | … |

- **Baseline**（与 plan 对齐）：Single Remote、Uniform、Plan2 Modal top2、…
- **待测方法**：…
- **指标**：分段 BPM 相对误差 %、mean/std、apnea 检测（如有）

---

## 4. 结果

### 4.1 主结果表

（按场景 × 方法；数字来自实际运行）

| 方法 | cs_091339 | cs_095806 | cs_102621 | 跨域 mean |
|------|-----------|-----------|-----------|-----------|
| Baseline: Single Remote | | | | |
| **本方案** | | | | |
| … | | | | |

### 4.2 与 plan 预期对比

| 预期（Plan §x） | 实际 | 是否一致 |
|-----------------|------|----------|
| … | … | ✅ / ❌ / 部分 |

### 4.3 现象与图

- 关键现象（1–3 条 bullet）
- 图：`outputs/figures/{name}.png`（如有）

---

## 5. 结论

| 结论 | 证据强度 |
|------|----------|
| … | **已验证** / **仅单场景** / **未证实** |

**相对 baseline**：本方案 vs 当前推荐（Plan2 Modal / Single Remote）— 更好 / 相当 / 更差。

**部署建议**（可选）：是否值得进入默认 pipeline。

---

## 6. 开放问题与下一步

| ID | 问题 | 建议 |
|----|------|------|
| Q1 | … | 回研究 Agent 修订 plan / 补场景 / … |

---

## 7. 复现

```bash
# 填写实际命令
python notebooks/scripts/{script}.py
```

| 产出 | 路径 |
|------|------|
| 数值报告 | `outputs/reports/{name}.npy` |
| 图表 | `outputs/figures/...` |
| 本报告 | `docs/reports/{topic}_report.md` |

---

## 8. Plan 回填（执行 Agent 更新 plan 末尾）

- **验证状态**：{已完成 / 部分完成 / 废弃}
- **实际脚本**：`...`
- **结论一句话**：…
