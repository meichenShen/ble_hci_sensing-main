# {算法名称} — 实现计划

> **来源**：{论文标题 / 笔记路径，如 `docs/papers/xxx.pdf`}  
> **目标报告**：`docs/reports/{topic}_report.md`（模板：`docs/templates/algorithm_validation_report.md`）  
> **建议 plan 路径**：`docs/plans/{topic}_plan.md`  
> **日期**：{YYYY-MM-DD}  
> **验证状态**：待实现

---

## 1. 动机与背景

（2–4 句）要解决什么问题；与现有工作的关系。

| 项目 | 说明 |
|------|------|
| 问题 | 例如：多信道融合是否优于 Single max-η |
| 相关脚本/文档 | `chFusion_fft-q.py`、`chFusion_plan2.py`、`docs/CS呼吸算法验证整体进度.md` |
| 本 plan 定位 | 新方案 / 改进 Plan2 / 验证论文方法 / … |

---

## 2. 物理与变量

### 2.1 可用观测量

| 变量 | 是否使用 | 理由 |
|------|----------|------|
| `remote_amplitudes` | ✅ / ❌ | … |
| `local_amplitudes` | ✅ / ❌ | … |
| `amplitudes`（总幅值） | ✅ / ❌ | … |
| `phases`（总相位，unwrap） | ✅ / ❌ | … |

### 2.2 不使用的变量及原因

- 例如：不用 local/remote **单端相位**（含 LO 漂移）；见 `chFusion_pca_svd_plan.md` §2.2

### 2.3 符号约定

| 符号 | 含义 |
|------|------|
| η | 呼吸频段能量比 |
| ρ | 峰度（谱峰尖锐度） |
| B_r | 呼吸频段 |
| … | … |

---

## 3. 算法步骤

按处理顺序写清；可附公式或伪代码。

### 3.1 预处理

- 重采样：`resample_to_uniform_grid`（如需）
- 滤波：中值 / Hampel / 高通 / 带通 — 参数 `{…}`

### 3.2 滑窗

| 参数 | 值 | 说明 |
|------|-----|------|
| 窗长 | {秒或样本数} | … |
| 步长 | … | … |
| 呼吸频段 | … Hz | … |

### 3.3 信道融合

（Single / Uniform / η-weight / PCA / Top-K / …）

```
伪代码或步骤：
1. 每窗对 72 信道 …
2. …
```

### 3.4 模态融合（如有）

- 参与模态：phase / remote / local
- 权重：equal / η-weight / top2 / …

### 3.5 寻峰与 BPM

- 频谱估计方式（FFT / …）
- 寻峰规则；半频/倍频处理 `[待确认]`

---

## 4. Baseline 对比

执行 Agent **必须**跑齐下表方法（可增不可减，除非注明原因）。

| 方法 ID | 说明 | 实现参考 |
|---------|------|----------|
| B0 | Single Remote（max-η 单信道） | `chfusion.py` |
| B1 | Uniform（或 plan 指定的一种多信道融合） | … |
| B2 | Plan2 Modal top2 equal（或当前跨域默认） | `chFusion_plan2.py` |
| **T0** | **本 plan 待测方案** | 本节 §3 |

**预期相对关系**（研究阶段假设，可被实验推翻）：

| 对比 | 预期 |
|------|------|
| T0 vs B0 | 更好 / 相当 / 更差 — 因为 … |
| T0 vs B2 | … |

---

## 5. 评估设计

### 5.1 场景

| 场景 JSON | 用途 |
|-----------|------|
| `config/scenarios/cs_091339.json` | 主场景 / 跨域之一 |
| `config/scenarios/cs_095806.json` | 跨域重复性 |
| `config/scenarios/cs_102621.json` | 跨域重复性 |
| `{其他}` | `[待确认]` |

### 5.2 指标

| 指标 | 说明 |
|------|------|
| 分段 BPM 相对误差 % | 主指标；报告 mean / std |
| IE ratio 误差 | 如需 |
| Apnea 检测 | 如需 |
| 跨域 mean | 三场景（或指定子集）平均 |

### 5.3 成功标准

| 级别 | 条件 |
|------|------|
| **最低** | 跨域 mean BPM err% ≤ {X}% 或 不劣于 B2 |
| **理想** | 单场景最优 ≤ {Y}%，且 091339 无灾难性退化 |
| **失败** | 例如：091339 mean > {Z}% 或 半频窗占比 > … |

---

## 6. 实现要点

### 6.1 建议文件

| 类型 | 路径 |
|------|------|
| 实验脚本 | `notebooks/scripts/chFusion_{topic}.py` |
| 可复用模块 | `src/ble_analysis/{module}.py`（新建或扩展） |
| 场景配置 | 沿用现有 JSON，或新增 `config/scenarios/…` |

### 6.2 复用 API

```python
# 示例：列出要调用的 ble_analysis 入口
from ble_analysis.chfusion import ...
from ble_analysis.segments import ...
from ble_analysis.metrics import ...
```

### 6.3 接口草案（可选）

```python
def estimate_bpm_{topic}(frames, scenario, ...) -> ...:
    """输入/输出说明"""
```

### 6.4 不做的事

- 不修改 unrelated 模块
- 不在 plan 阶段写完整实现代码

---

## 7. 预期产出

| 产出 | 路径 |
|------|------|
| 验证报告 | `docs/reports/{topic}_report.md` |
| 数值结果 | `outputs/reports/{topic}_*.npy` |
| 关键图 | `outputs/figures/{topic}_*.png` |
| 跨域 CLI（如需） | `notebooks/scripts/chFusion_{topic}_cross_domain.py` |

### 7.1 建议运行命令

```bash
python notebooks/scripts/chFusion_{topic}.py
# python notebooks/scripts/chFusion_{topic}_cross_domain.py
```

---

## 8. 验证状态与保留问题

> 由 **执行 Agent** 在实验后更新本节。

| 字段 | 内容 |
|------|------|
| **验证状态** | 待实现 |
| **实际脚本** | — |
| **报告链接** | — |
| **一句话结论** | — |

### 保留问题

| ID | 问题 | 备注 |
|----|------|------|
| Q1 | … | `[待确认]` |

---

## 9. 给执行 Agent 的首条指令

> 请按 `docs/plans/{topic}_plan.md` 实现 §3 算法，跑 §4 baseline 与 §5 场景，使用 `docs/templates/algorithm_validation_report.md` 撰写 `docs/reports/{topic}_report.md`，并回填本 plan §8。
