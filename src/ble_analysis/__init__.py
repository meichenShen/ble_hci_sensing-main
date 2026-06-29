"""BLE CS 数据分析工具包 ``ble_analysis``.

从 notebook 抽取的通用函数集合，详见同目录 ``README.md``。
"""

from ble_analysis.channels import (
    extract_channel_series,
    find_channel_key,
    get_available_channels,
    resolve_channel,
)
from ble_analysis.data import load_ble_frames
from ble_analysis.diagnostics import (
    analyze_time_intervals,
    diagnose_channel_presence,
    print_file_info,
    print_time_interval_summary,
)
from ble_analysis.filters import apply_filter_pipeline
from ble_analysis.paths import ensure_output_dirs, find_project_root
from ble_analysis.plotting import (
    plot_channel_amplitude_phase,
    plot_time_intervals,
    setup_plot_style,
)
from ble_analysis.resampling import resample_to_uniform_grid

from ble_analysis.bootstrap import init_notebook
from ble_analysis.metrics import (
    collect_error_metrics,
    plot_error_analysis,
    plot_window_error_distribution,
    run_error_analysis,
    save_error_results,
)
from ble_analysis.segments import (
    detect_apnea_segments,
    estimate_segment_breath_metrics,
    extract_segment_data,
    process_segments,
    run_segment_breath_analysis,
    save_segment_processed,
)
from ble_analysis.workflow import run_cs_exploration

__all__ = [
    "load_ble_frames",
    "get_available_channels",
    "find_channel_key",
    "resolve_channel",
    "extract_channel_series",
    "print_file_info",
    "diagnose_channel_presence",
    "analyze_time_intervals",
    "print_time_interval_summary",
    "resample_to_uniform_grid",
    "apply_filter_pipeline",
    "setup_plot_style",
    "plot_channel_amplitude_phase",
    "plot_time_intervals",
    "find_project_root",
    "ensure_output_dirs",
    "init_notebook",
    "run_cs_exploration",
    "extract_segment_data",
    "process_segments",
    "detect_apnea_segments",
    "estimate_segment_breath_metrics",
    "save_segment_processed",
    "run_segment_breath_analysis",
    "collect_error_metrics",
    "plot_error_analysis",
    "plot_window_error_distribution",
    "save_error_results",
    "run_error_analysis",
]
