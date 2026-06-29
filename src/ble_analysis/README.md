# ble_analysis

BLE Channel Sounding (CS) 离线分析工具包。从 notebook 中抽取的通用函数，供 Jupyter 实验脚本调用。

## 设计原则

- **复用底层模块**：数据加载走 `data_saver.DataSaver`，滤波走 `utils.signal_algrithom`（经 `filters.py` 封装）。
- **不在加载时偷偷重采样**：重采样、插帧由 notebook 显式调用 `resample_to_uniform_grid`。
- **通道缺失是正常情况**：不抛异常，通过诊断字段记录 `missing_frames`。
- **兼容 int/str 通道 key**：CS 帧数据中通道号可能以整数或字符串保存。

## 目录结构

| 模块 | 职责 |
|------|------|
| `paths.py` | 项目根目录查找、标准输出目录创建 |
| `bootstrap.py` | Notebook 环境初始化（`sys.path`、输出目录、绘图风格） |
| `data.py` | JSON/JSONL 帧数据加载 |
| `channels.py` | 通道枚举、匹配、单通道时间序列提取 |
| `diagnostics.py` | 文件元信息、通道覆盖率、时间间隔统计 |
| `plotting.py` | Matplotlib 风格与通用绘图 |
| `resampling.py` | 非均匀时间序列线性重采样 |
| `filters.py` | 滤波 pipeline（中值 / Hampel / 高通 / 带通） |
| `workflow.py` | 一键探索工作流 `run_cs_exploration` |
| `segments.py` | 分段提取、滤波、apnea 检测、BPM/IE 估计 |
| `metrics.py` | 与 GT 对比的误差收集与可视化 |

## Notebook 中使用

**第一步**：在 import `ble_analysis` 之前，必须把 `src/` 加入 `sys.path`：

```python
import sys
from pathlib import Path

_cwd = Path.cwd().resolve()
project_root = next(
    (p for p in [_cwd, *_cwd.parents] if (p / "src").is_dir()),
    None,
)
sys.path.insert(0, str(project_root / "src"))

from ble_analysis.bootstrap import init_notebook

_env = init_notebook(project_root)
FIGURES_DIR = _env["FIGURES_DIR"]
PROCESSED_DIR = _env["PROCESSED_DIR"]
REPORTS_DIR = _env["REPORTS_DIR"]
```

也可直接调用 `init_notebook()`（内部会再次确保 `src/` 在路径中）。

## 输出目录

| 路径 | 用途 |
|------|------|
| `outputs/figures/` | 探索图、误差图、分段可视化 |
| `outputs/processed/` | `segment_processed_data.npy` 等中间结果 |
| `outputs/reports/` | `segment_error_results.npy` 等报告数据 |

## 常用 API

### 快速探索（单通道）

```python
from ble_analysis.workflow import run_cs_exploration

result = run_cs_exploration(
    filepath,
    channel=2,
    figures_dir=FIGURES_DIR,
    verbose=False,
    save_figures=True,
)
series = result["series"]           # 幅值、相位、时间戳等
actual_sampling_rate = result["actual_sampling_rate"]
```

### 分段呼吸评估

```python
from ble_analysis.data import load_ble_frames
from ble_analysis.segments import run_segment_breath_analysis
from ble_analysis.metrics import run_error_analysis

_, frames = load_ble_frames(filepath, verbose=False)

pipeline = run_segment_breath_analysis(
    frames,
    segment_config,      # 各段起止 index、类型、GT
    segment_channel=2,
    segment_variables=["remote_amplitudes"],
    save_path=PROCESSED_DIR / "segment_processed_data.npy",
)

error_out = run_error_analysis(
    pipeline["segment_processed"],
    segment_config,
    pipeline["segment_data"],
    figures_dir=FIGURES_DIR,
    reports_dir=REPORTS_DIR,
)
```

### 滤波 pipeline

```python
from ble_analysis.filters import apply_filter_pipeline

y = apply_filter_pipeline(
    signal,
    fs=actual_sampling_rate,
    pipeline=[
        {"type": "median", "window_size": 3},
        {"type": "hampel", "window_size": 3, "n_sigma": 3},
        {"type": "highpass", "cutoff": 0.05, "order": 1},
        {"type": "bandpass", "lowcut": 0.1, "highcut": 0.35, "order": 2},
    ],
)
```

支持的 `type`：`median`、`hampel`、`highpass`、`bandpass`（`lowpass` 暂未实现）。需要采样率的步骤在 `fs=None` 时会 warning 并跳过。

## 数据结构约定

### `extract_channel_series` 返回值

| 键 | 说明 |
|----|------|
| `channel` | 实际匹配到的通道 key（int 或 str） |
| `indices` | 原始帧 index 数组 |
| `timestamps_ms` | 毫秒时间戳 |
| `time_sec` | 以首点为 0 的相对时间（秒） |
| `amplitudes` / `phases` / `local_*` / `remote_*` | 各物理量 numpy 数组 |
| `presence` | 每帧是否含该通道 |
| `missing_frames` | 缺失帧诊断列表 |

### `segment_config` 段落配置

```python
segment_config = {
    "1a": {
        "start": 131,          # 原始帧 index 起点
        "end": 244,            # 原始帧 index 终点
        "type": "breath",      # "breath" 或 "apnea"
        "bpm_gt": 8.675,       # 可选，用于误差评估
        "ie_gt": 0.985,        # 可选
    },
    "p1": {
        "start": 419,
        "end": 437,
        "type": "apnea",
        "apnea_gt_sec": 10.0,  # 可选
    },
}
```

`apnea` 段提取时会自动在前后各扩展约 10 秒 context（用于阈值学习）。

## 对应 Notebook

| Notebook | 说明 |
|----------|------|
| `notebooks/glb_cs_load_and_explore.ipynb` | 单通道快速探索 |
| `notebooks/glb_cs_segment_breath_analysis.ipynb` | 分段处理 + 性能评估 |
| `notebooks/glb_cs_full_pipeline_demo.ipynb` | 全量滤波算法演示（冻结） |

## 依赖关系

```
ble_analysis
├── data_saver.py      (src/)
└── utils/signal_algrithom.py
```

外部：`numpy`、`matplotlib`、`scipy`
