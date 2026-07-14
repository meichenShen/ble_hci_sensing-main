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
from ble_analysis.liu_2016 import (
    Liu2016PaperConfig,
    MODAL_LIU_VARIABLES,
    estimate_fft_phase_slope_bpm,
    estimate_liu_2016_paper_window,
    estimate_liu_eta_rho_adapted_window_bpms,
    estimate_liu_style_segment,
    estimate_liu_style_window_bpms,
    modified_z_score_filter,
    run_liu_2016_paper_benchmark,
    run_liu_eta_rho_adapted_benchmark,
    run_liu_2016_benchmark,
    score_sinusoid_periodicity,
    weighted_median_frequency,
)
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
from ble_analysis.multivariable_fusion import (
    CHANNEL_FUSION_METHODS,
    HIERARCHICAL_COMPARISON_METHODS,
    MULTIVARIABLE_VARIABLES,
    VARIABLE_FUSION_METHODS,
    MultivariableFusionConfig,
    best_tone_selection,
    equal_average_fusion,
    geometric_quality,
    hierarchical_quality_fusion,
    liu_weighted_median_channel_fusion,
    normalized_weights,
    quality_mrc_channel_fusion,
    run_channel_fusion_methods,
    run_hierarchical_comparisons,
    snr_mrc_channel_fusion,
    variable_level_fusion,
    weighted_median,
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
    "Liu2016PaperConfig",
    "MODAL_LIU_VARIABLES",
    "estimate_fft_phase_slope_bpm",
    "score_sinusoid_periodicity",
    "modified_z_score_filter",
    "weighted_median_frequency",
    "estimate_liu_2016_paper_window",
    "run_liu_2016_paper_benchmark",
    "estimate_liu_eta_rho_adapted_window_bpms",
    "run_liu_eta_rho_adapted_benchmark",
    "estimate_liu_style_segment",
    "estimate_liu_style_window_bpms",
    "run_liu_2016_benchmark",
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
    "MultivariableFusionConfig",
    "MULTIVARIABLE_VARIABLES",
    "CHANNEL_FUSION_METHODS",
    "VARIABLE_FUSION_METHODS",
    "HIERARCHICAL_COMPARISON_METHODS",
    "best_tone_selection",
    "equal_average_fusion",
    "liu_weighted_median_channel_fusion",
    "snr_mrc_channel_fusion",
    "quality_mrc_channel_fusion",
    "variable_level_fusion",
    "hierarchical_quality_fusion",
    "run_channel_fusion_methods",
    "run_hierarchical_comparisons",
    "geometric_quality",
    "normalized_weights",
    "weighted_median",
]
