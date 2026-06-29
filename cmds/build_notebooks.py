"""Build the three CS analysis notebooks from the legacy monolithic notebook."""

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "notebooks" / "glb_load_cs_saved_frames_show_analysis.ipynb"
OUT_EXPLORE = ROOT / "notebooks" / "glb_cs_load_and_explore.ipynb"
OUT_DEMO = ROOT / "notebooks" / "glb_cs_full_pipeline_demo.ipynb"
OUT_SEGMENT = ROOT / "notebooks" / "glb_cs_segment_breath_analysis.ipynb"

BOOTSTRAP = """\
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# 必须先加入 src/，再 import ble_analysis
_cwd = Path.cwd().resolve()
project_root = next(
    (p for p in [_cwd, *_cwd.parents] if (p / "src").is_dir()),
    None,
)
if project_root is None:
    raise FileNotFoundError("未找到项目根目录（缺少 src/ 目录）")

_src = project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from ble_analysis.bootstrap import init_notebook

_env = init_notebook(project_root)
project_root = _env["project_root"]
FIGURES_DIR = _env["FIGURES_DIR"]
PROCESSED_DIR = _env["PROCESSED_DIR"]
REPORTS_DIR = _env["REPORTS_DIR"]
"""

EXPLORE_PARAMS = """\
# === 参数（仅改这里）===
filepath = project_root / "sampleData" / "CS_frames_all_20260113_091339.jsonl"
channel = 2
"""

EXPLORE_RUN = """\
from ble_analysis.workflow import run_cs_exploration

result = run_cs_exploration(
    filepath,
    channel,
    figures_dir=FIGURES_DIR,
    verbose=False,
    save_figures=True,
    show_plots=True,
)

data, frames = result["data"], result["frames"]
series = result["series"]
channel = result["channel"]
actual_sampling_rate = result["actual_sampling_rate"]
time_info = result["time_info"]

# 兼容旧变量名
amplitudes = series["amplitudes"]
phases = series["phases"]
local_amplitudes = series["local_amplitudes"]
remote_amplitudes = series["remote_amplitudes"]
timestamps_ms = series["timestamps_ms"]
time_sec = series["time_sec"]
"""

SEGMENT_CONFIG = Path(ROOT / "cmds/_nb_cells/cell_26.txt").read_text(encoding="utf-8")
# strip the print table at bottom - keep only segment_config dict
SEGMENT_CONFIG = SEGMENT_CONFIG.split("# 显示配置")[0].strip()

SEGMENT_NOTEBOOK = {
    "cells": [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# CS 分段呼吸分析与性能评估\n",
                "\n",
                "加载 CS 帧数据 → 按段落配置提取 → 滤波 → apnea 检测 → BPM/IE 指标 → 误差可视化。\n",
                "\n",
                "依赖 `src/ble_analysis/segments.py` 与 `metrics.py`。\n",
            ],
        },
        {"cell_type": "code", "metadata": {}, "source": BOOTSTRAP.splitlines(keepends=True)},
        {
            "cell_type": "code",
            "metadata": {},
            "source": [
                "from ble_analysis.data import load_ble_frames\n",
                "from ble_analysis.segments import run_segment_breath_analysis\n",
                "from ble_analysis.metrics import run_error_analysis\n",
                "\n",
                "# === 数据与分段参数 ===\n",
                'filepath = project_root / "sampleData" / "CS_frames_all_20260113_091339.jsonl"\n',
                "segment_channel = 2\n",
                'segment_variables = ["remote_amplitudes"]\n',
                "\n",
            ]
            + SEGMENT_CONFIG.splitlines(keepends=True),
        },
        {
            "cell_type": "code",
            "metadata": {},
            "source": [
                "data, frames = load_ble_frames(filepath, verbose=False)\n",
                "\n",
                "pipeline = run_segment_breath_analysis(\n",
                "    frames,\n",
                "    segment_config,\n",
                "    segment_channel,\n",
                "    segment_variables,\n",
                "    save_path=PROCESSED_DIR / 'segment_processed_data.npy',\n",
                ")\n",
                "\n",
                "segment_data = pipeline['segment_data']\n",
                "segment_processed = pipeline['segment_processed']\n",
                "actual_sampling_rate = pipeline['sampling_rate']\n",
            ],
        },
        {
            "cell_type": "code",
            "metadata": {},
            "source": [
                "error_out = run_error_analysis(\n",
                "    segment_processed,\n",
                "    segment_config,\n",
                "    segment_data,\n",
                "    figures_dir=FIGURES_DIR,\n",
                "    reports_dir=REPORTS_DIR,\n",
                "    show=True,\n",
                "    save=True,\n",
                ")\n",
                "\n",
                "bpm_data = error_out['bpm_data']\n",
                "ie_data = error_out['ie_data']\n",
                "apnea_data = error_out['apnea_data']\n",
                "error_results = error_out['error_results']\n",
            ],
        },
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.11.0"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}


def _code_cell(source: str):
    return {"cell_type": "code", "metadata": {}, "outputs": [], "source": source.splitlines(keepends=True)}


def _md_cell(source: str):
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def build_explore():
    nb = {
        "cells": [
            _md_cell(
                "# CS 数据加载与快速探索\n"
                "\n"
                "一键加载帧数据、提取单通道、时间间隔诊断与基础绘图。\n"
                "\n"
                "后续分段评估见 `glb_cs_segment_breath_analysis.ipynb`；"
                "全量滤波算法演示见 `glb_cs_full_pipeline_demo.ipynb`（冻结，不再修改）。\n"
            ),
            _code_cell(BOOTSTRAP),
            _code_cell(EXPLORE_PARAMS),
            _code_cell(EXPLORE_RUN),
            _code_cell(
                "# 可选：Local / Remote 幅值对比\n"
                "if len(series['amplitudes']) > 0:\n"
                "    fig, axes = plt.subplots(2, 1, figsize=(12, 6))\n"
                "    axes[0].plot(time_sec, local_amplitudes, 'g-', alpha=0.7, label='Local')\n"
                "    axes[0].plot(time_sec, remote_amplitudes, 'm-', alpha=0.7, label='Remote')\n"
                "    axes[0].legend(); axes[0].set_title(f'Channel {channel} Local/Remote')\n"
                "    axes[0].grid(True, alpha=0.3)\n"
                "    axes[1].plot(time_sec, amplitudes, 'b-', alpha=0.8, label='Total')\n"
                "    axes[1].legend(); axes[1].set_title('Total Amplitude')\n"
                "    axes[1].grid(True, alpha=0.3)\n"
                "    plt.tight_layout()\n"
                "    fig.savefig(FIGURES_DIR / f'channel_{channel}_local_remote.png')\n"
                "    plt.show()\n"
            ),
        ],
        "metadata": SEGMENT_NOTEBOOK["metadata"],
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUT_EXPLORE.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Wrote", OUT_EXPLORE.name)


def build_demo(legacy_cells):
    cells = [
        _md_cell(
            "# CS 全量滤波管线 Demo（冻结）\n"
            "\n"
            "> **此 notebook 为算法步骤演示，后期不再修改。**\n"
            "> 日常评估请使用 `glb_cs_segment_breath_analysis.ipynb`。\n"
            "\n"
            "流程：全通道提取 → 中值/Hampel 去尖刺 → 高通去趋势 → 呼吸窗能量判定 → 带通滤波。\n"
        ),
        _code_cell(
            BOOTSTRAP
            + "\nfrom ble_analysis.data import load_ble_frames\n"
            + "from ble_analysis.filters import apply_filter_pipeline\n",
        ),
        _code_cell(
            'filepath = project_root / "sampleData" / "CS_frames_all_20260113_091339.jsonl"\n'
            "data, frames = load_ble_frames(filepath)\n"
        ),
    ]
    # legacy cells 14-23 (markdown + code)
    for i in range(14, 24):
        c = copy.deepcopy(legacy_cells[i])
        c["outputs"] = []
        c["execution_count"] = None
        src = "".join(c.get("source", []))
        # remove debug prints in cell 15
        if i == 15:
            src = src.replace(
                '            print(f"数据：{key}原始类型为：{type(ch_data_dict[key])}")\n', ""
            )
        c["source"] = src.splitlines(keepends=True)
        cells.append(c)

    nb = {
        "cells": cells,
        "metadata": SEGMENT_NOTEBOOK["metadata"],
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUT_DEMO.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Wrote", OUT_DEMO.name)


def build_segment():
    OUT_SEGMENT.write_text(
        json.dumps(SEGMENT_NOTEBOOK, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("Wrote", OUT_SEGMENT.name)


def main():
    legacy = json.loads(LEGACY.read_text(encoding="utf-8"))
    build_explore()
    build_demo(legacy["cells"])
    build_segment()
    print("Done. Legacy notebook kept at", LEGACY.name)


if __name__ == "__main__":
    main()
