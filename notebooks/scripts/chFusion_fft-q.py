"""chFusion FFT+q — CS metal-plate segment BPM benchmark script.

Overview
========

End-to-end experiment for BLE CS respiration-rate (BPM) on scripted metal-plate
segments. Compares **five methods** (two baselines + three q-weighted fusion)
across four CS observables.

Methods (see ``docs/chfusion_q_energy_peak.md``)
------------------------------------------------

- **Single**            — max energy-ratio channel, single-channel FFT peak
- **Uniform**           — equal-weight average of normalized spectra
- **FFT+q_energy**      — weight by log-mapped breath/total energy ratio η
- **FFT+q_peak**        — weight by log-mapped spectral peak SNR ρ
- **FFT+q_energy_peak** — weight by √(q_energy · q_peak), all channels

Variables: ``amplitudes``, ``remote_amplitudes``, ``local_amplitudes``, ``phases``
(phase unwrapped before filtering).

Pipeline
--------

1. Load CS frames → segment extract → median / HP / BP filter (all channels)
2. Sliding-window FFT → q scores → weighted spectral fusion → BPM
3. Tables + PDF figures under ``outputs/``

Run: ``python notebooks/scripts/chFusion_fft-q.py``
"""

# %% [markdown]
# # chFusion — 4 variables × 5 methods
#
# | Step | Content |
# |------|---------|
# | 0 | Bootstrap + parameters |
# | 1 | Run benchmark |
# | 2 | Method tables per variable |
# | 3 | Leaderboard + save `.npy` |
# | 4 | Violin / overview PDF figures |

# %% [markdown]
# ## 0. Environment bootstrap

# %%
import sys
from pathlib import Path

import numpy as np

_cwd = Path.cwd().resolve()
project_root = next(
    (p for p in [_cwd, *_cwd.parents] if (p / "src").is_dir()),
    None,
)
if project_root is None:
    raise FileNotFoundError("Project root not found (missing src/ directory)")

_src = project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from ble_analysis.bootstrap import init_notebook

_env = init_notebook(project_root)
project_root = _env["project_root"]
FIGURES_DIR = _env["FIGURES_DIR"]
REPORTS_DIR = _env["REPORTS_DIR"]

# %% [markdown]
# ## 0b. Parameters

# %%
from ble_analysis.chfusion import (
    CS_SIGNAL_VARIABLES,
    ChFusionConfig,
    plot_benchmark_violins,
    print_benchmark_leaderboard,
    print_part2_method_tables,
    print_q_score_documentation,
    run_chfusion_benchmark,
)
from ble_analysis.data import load_ble_frames
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import BreathMetricParams, FilterParams

SCENARIO_ID = "cs_102621"
scenario = load_scenario(SCENARIO_ID, project_root=project_root)
filepath = scenario.resolve_data_path(project_root)
segment_config = scenario.segment_config
print_scenario_summary(scenario)

filter_params = FilterParams()
metric_params = BreathMetricParams()
chfusion_config = ChFusionConfig(
    breath_freq_low=metric_params.breath_freq_low,
    breath_freq_high=metric_params.breath_freq_high,
    window_length_sec=metric_params.window_length_sec,
    step_length_sec=metric_params.step_length_sec,
    enable_consensus=False,
)

# 从 (key, label) 元组中提取变量名（如 amplitudes, phases 等）
variables = [v[0] for v in CS_SIGNAL_VARIABLES]
print("Variables:", ", ".join(f"{k} ({lbl})" for k, lbl in CS_SIGNAL_VARIABLES))
print_q_score_documentation(chfusion_config)

# %% [markdown]
# ## 1. Run benchmark (4 variables × 5 methods)

# %%
# data 为原始 DataFrame，仅 frames 参与后续处理
data, frames = load_ble_frames(filepath, verbose=False)

benchmark = run_chfusion_benchmark(
    frames,
    segment_config,
    variables=variables,
    filter_params=filter_params,
    metric_params=metric_params,
    config=chfusion_config,
    verbose=True,
)

# %% [markdown]
# ## 2. Method comparison per variable

# %%
print_part2_method_tables(benchmark["part2"])

# %% [markdown]
# ## 3. Leaderboard and save results

# %%
print_benchmark_leaderboard(benchmark["leaderboard"])

report_path = REPORTS_DIR / "chfusion_benchmark_matrix.npy"
np.save(report_path, benchmark, allow_pickle=True)
print(f"Saved: {report_path}")

# %% [markdown]
# ## 4. PDF figures (violins + 4×5 overview)
#
# Methods: Single / Uniform / FFT+q_energy / FFT+q_peak / FFT+q_energy_peak
# show=True 弹出 matplotlib 窗口，便于调试观察；save=True 同时写入 outputs/figures/

# %%
figure_paths = plot_benchmark_violins(
    benchmark,
    figures_dir=FIGURES_DIR,
    show=True,
    save=True,
)
print(f"共 {len(figure_paths)} 张图")
