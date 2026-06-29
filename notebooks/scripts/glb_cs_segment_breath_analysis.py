"""Segmented script converted from ``glb_cs_segment_breath_analysis.ipynb``.

Run section-by-section using ``# %%`` cell markers (VS Code Python Interactive / Spyder / ``jupyter lab``).
Source notebook: ``notebooks/glb_cs_segment_breath_analysis.ipynb``.
"""

# %% [markdown]
# # CS 分段呼吸分析与性能评估
#
# 加载 CS 帧数据 → 按段落配置提取 → 滤波 → apnea 检测 → BPM/IE 指标 → 误差可视化。
#
# 依赖 `src/ble_analysis/segments.py` 与 `metrics.py`。

# %%
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

# %%
from ble_analysis.data import load_ble_frames
from ble_analysis.metrics import run_error_analysis
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import run_segment_breath_analysis

# === 数据与分段参数（切换场景时只改 SCENARIO_ID）===
SCENARIO_ID = "cs_091339"
scenario = load_scenario(SCENARIO_ID, project_root=project_root)
filepath = scenario.resolve_data_path(project_root)
segment_config = scenario.segment_config
segment_channel = scenario.default_channel or 2
segment_variables = ["remote_amplitudes"]
print_scenario_summary(scenario)

# %%
data, frames = load_ble_frames(filepath, verbose=False)

pipeline = run_segment_breath_analysis(
    frames,
    segment_config,
    segment_channel,
    segment_variables,
    save_path=PROCESSED_DIR / 'segment_processed_data.npy',
)

segment_data = pipeline['segment_data']
segment_processed = pipeline['segment_processed']
actual_sampling_rate = pipeline['sampling_rate']

# %%
error_out = run_error_analysis(
    segment_processed,
    segment_config,
    segment_data,
    figures_dir=FIGURES_DIR,
    reports_dir=REPORTS_DIR,
    show=True,
    save=True,
)

bpm_data = error_out['bpm_data']
ie_data = error_out['ie_data']
apnea_data = error_out['apnea_data']
error_results = error_out['error_results']
