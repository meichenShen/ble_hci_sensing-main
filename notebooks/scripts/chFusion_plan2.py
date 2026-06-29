"""chFusion Plan 2 — amplitude–phase complementarity & modal fusion validation.

Implements **改进方案2** from ``docs/CS呼吸算法验证整体进度.md``:

Part A — 幅值相位互补性（波形对比）
------------------------------------
For **phase / remote / local** Single best-channel windows, pick best / worst / median
accuracy windows across all breath segments. At each window's reference-best channel,
plot normalized **bandpass** waveforms for all four CS variables.

Part B — 只联合最好的信道 × 最好的变量
---------------------------------------
Per sliding window, each variable picks its own best channel (``Plan2Config.channel_metric``,
default **peak** ρ); fuse spectra of phase + remote amplitude + local amplitude:

- **Modal equal**           — equal weights (1/3 each)
- **Modal η-weight**        — weights ∝ breath-band energy ratio η
- **Modal 0.5/0.25/0.25**   — phase 0.5, remote/local 0.25
- **Modal top2 equal**      — top-2 variables by selector metric, equal 0.5 each
- **Modal top2 ρ-weight**   — top-2 variables by selector metric, weights ∝ ρ

Run: ``python notebooks/scripts/chFusion_plan2.py``
"""

# %% [markdown]
# # chFusion Plan 2 — 互补性波形 + 模态融合
#
# | Step | Content |
# |------|---------|
# | 0 | Bootstrap + parameters |
# | 1 | Run Plan 2 validation (filter 4 vars, collect windows, modal fusion) |
# | 2 | Complementarity waveform figures (phase + remote + local, 3×3 PDFs) |
# | 3 | Modal fusion BPM tables |
# | 4 | Overview figures: leaderboard bars, segment×method heatmap, 3-panel violins |

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
    COMPLEMENTARITY_REFERENCE_VARIABLES,
    CS_SIGNAL_VARIABLES,
    ChFusionConfig,
    Plan2Config,
    build_plan2_comparison_method_labels,
    plot_complementarity_waveforms_all,
    plot_plan2_comparison_figures,
    print_complementarity_window_summary,
    print_plan2_comparison_table,
    run_plan2_validation,
)
from ble_analysis.data import load_ble_frames
from ble_analysis.scenarios import load_scenario, print_scenario_summary
from ble_analysis.segments import BreathMetricParams, FilterParams

SCENARIO_ID = "cs_095806"
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

# 以 phase 作为基准参考变量，评估幅值变量的互补性
REFERENCE_VARIABLE = "phases"
# 拷贝一份避免外部修改影响常量定义
COMPLEMENTARITY_VARS = list(COMPLEMENTARITY_REFERENCE_VARIABLES)

# 信道选择指标：energy_ratio 侧重呼吸频带能量占比，峰值则用 peak
plan2_config = Plan2Config(channel_metric="energy_ratio")

print("Plan 2 primary reference:", REFERENCE_VARIABLE)
print("Complementarity refs:", ", ".join(COMPLEMENTARITY_VARS))
print("Plan 2 channel metric:", plan2_config.channel_metric)
print("CS variables:", ", ".join(f"{k} ({lbl})" for k, lbl in CS_SIGNAL_VARIABLES))
print("Comparison methods:", len(build_plan2_comparison_method_labels()), "total (4×Single + 4×Uniform + 5×modal)")

# %% [markdown]
# ## 1. Run Plan 2 validation
#
# Filters all four variables on all channels, collects per-window Single records
# for phase / remote / local reference variables, and runs modal-fusion strategies.

# %%
# data 为原始 DataFrame，仅 frames 参与后续处理
data, frames = load_ble_frames(filepath, verbose=False)

plan2 = run_plan2_validation(
    frames,
    segment_config,
    filter_params=filter_params,
    metric_params=metric_params,
    config=chfusion_config,
    plan2_config=plan2_config,
    reference_variable=REFERENCE_VARIABLE,
    complementarity_variables=COMPLEMENTARITY_VARS,
    verbose=True,
)

print_complementarity_window_summary(plan2["complementarity_by_reference"])

# %% [markdown]
# ## 2. Complementarity waveform figures
#
# Nine PDFs (3 refs × best/worst/median): four normalized bandpass waveforms on
# each reference variable's best channel, annotated with selector metric + BPM per variable.

# %%
complementarity_paths = plot_complementarity_waveforms_all(
    plan2["complementarity_by_reference"],
    reference_variables=COMPLEMENTARITY_VARS,
    figures_dir=FIGURES_DIR,
    show=True,
    save=True,
)
print(f"Saved {len(complementarity_paths)} complementarity figure(s)")

# %% [markdown]
# ## 3. Baseline + modal fusion comparison table

# %%
print_plan2_comparison_table(plan2)

# %% [markdown]
# ## 4. Save results + comparison figures (leaderboard / heatmap / violins)

# %%
report_path = REPORTS_DIR / "chfusion_plan2_validation.npy"
np.save(report_path, plan2, allow_pickle=True)
print(f"Saved: {report_path}")

overview_paths = plot_plan2_comparison_figures(
    plan2,
    figures_dir=FIGURES_DIR,
    show=True,
    save=True,
)
print(f"Saved {len(overview_paths)} Plan 2 overview figure(s)")
for p in overview_paths:
    print(f"  {p}")
