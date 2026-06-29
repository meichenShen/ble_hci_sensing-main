# BLE HCI Sensing

BLE 信道探测（CS）与方向估计（DF）数据的离线分析与算法验证项目。从原 BLE Host 上位机项目中拆分而来，保留 notebook 实验与数据处理核心模块。

## 项目结构

```
├── notebooks/                    # Jupyter 分析 notebook（详见 notebooks/README.md）
│   ├── glb_cs_*.ipynb            # Globecom 26 投稿：CS/DF 金属板呼吸指标
│   ├── dip_load_and_filter_example.ipynb  # Direct IQ Pipeline 加载与滤波
│   └── load_*/show_*             # 早期代码，可忽略
├── sampleData/                   # 示例 JSONL/JSON 帧数据
├── outputs/
│   ├── figures/                  # 图表
│   ├── processed/                # 中间处理结果 (.npy)
│   └── reports/                  # 误差报告 (.npy)
├── src/
│   ├── ble_analysis/             # CS 分析工具包（详见 src/ble_analysis/README.md）
│   ├── data_saver.py             # JSONL 帧数据加载
│   ├── config.py                 # 配置（data_saver 依赖）
│   └── utils/
│       └── signal_algrithom.py   # 滤波与信号处理
└── docs/
    └── jsonl_format.md           # JSONL 数据格式说明
```

## 环境要求

- Python 3.9+
- Jupyter Lab / Notebook

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

1. 在项目根目录或 `notebooks/` 下启动 Jupyter
2. 打开对应 notebook，**先运行第一个 cell**（会自动定位项目根目录并将 `src/` 加入 Python 路径）
3. 修改 `filepath` 指向 `sampleData/` 下的 JSONL 文件
4. 按顺序执行 cell

### CS 数据分析推荐流程

| 步骤 | Notebook | 说明 |
|------|----------|------|
| 1 | `glb_cs_load_and_explore.ipynb` | 加载数据、选通道、看采样率与时间间隔 |
| 2 | `glb_cs_segment_breath_analysis.ipynb` | 配置段落 GT，跑 BPM/IE/apnea 指标与误差图 |
| （参考） | `glb_cs_full_pipeline_demo.ipynb` | 全通道滤波算法步骤演示，**不再维护** |

### Notebook 引导代码

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
```

## ble_analysis 工具包

通用分析函数已从 notebook 抽取至 `src/ble_analysis/`，包括：

- 数据加载与通道提取
- 时间间隔诊断与绘图
- 滤波 pipeline 封装
- 分段呼吸处理与 GT 误差评估

完整 API 说明见 **[src/ble_analysis/README.md](src/ble_analysis/README.md)**。

## 数据格式

采集数据为 JSONL 格式，详见 [docs/jsonl_format.md](docs/jsonl_format.md)。

## 与原 BLE Host 的关系

本项目由原 [ble_host](https://github.com/cwdao/ble_host) 仓库的 `examples/` 目录及 notebook 依赖的 `src/` 模块拆分而来，不包含 GUI 上位机、串口通信与打包相关代码。
