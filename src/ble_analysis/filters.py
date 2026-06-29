"""滤波 pipeline 封装。

内部 try/except 导入 ``utils.signal_algrithom``；
导入失败时相关滤波器会 warning 并跳过，而不是崩溃。
Notebook 应通过 ``apply_filter_pipeline`` 使用滤波，不要直接 import signal_algrithom。
"""

import warnings

import numpy as np

try:
    from utils import signal_algrithom as sig_algm
except ImportError:
    sig_algm = None


def _warn_missing_sig_algm(filter_type):
    warnings.warn(
        f"无法导入 utils.signal_algrithom，跳过 {filter_type} 滤波器",
        stacklevel=3,
    )


def _apply_single_filter(values, fs, step):
    filter_type = step.get("type")
    values = np.asarray(values, dtype=float)

    if filter_type == "median":
        if sig_algm is None:
            _warn_missing_sig_algm("median")
            return values
        window_size = step.get("window_size", step.get("kernel_size", 3))
        return sig_algm.median_filter_1d(values, window_size=window_size)

    if filter_type == "hampel":
        if sig_algm is None:
            _warn_missing_sig_algm("hampel")
            return values
        window_size = step.get("window_size", 3)
        n_sigma = step.get("n_sigmas", step.get("n_sigma", 3))
        return sig_algm.hampel_filter(
            values, window_size=window_size, n_sigma=n_sigma
        )

    if filter_type in ("highpass", "lowpass", "bandpass"):
        if fs is None:
            warnings.warn(
                f"采样率 fs 未提供，跳过 {filter_type} 滤波器",
                stacklevel=3,
            )
            return values
        if sig_algm is None:
            _warn_missing_sig_algm(filter_type)
            return values

    if filter_type == "highpass":
        cutoff = step.get("cutoff", step.get("cutoff_freq", 0.05))
        order = step.get("order", 1)
        return sig_algm.highpass_filter_zero_phase(
            values, cutoff_freq=cutoff, sampling_rate=fs, order=order
        )

    if filter_type == "bandpass":
        lowcut = step.get("lowcut", 0.1)
        highcut = step.get("highcut", 0.35)
        order = step.get("order", 2)
        return sig_algm.bandpass_filter_zero_phase(
            values,
            lowcut=lowcut,
            highcut=highcut,
            sampling_rate=fs,
            order=order,
        )

    if filter_type == "lowpass":
        warnings.warn("lowpass 滤波器尚未实现，已跳过", stacklevel=3)
        return values

    warnings.warn(f"未知滤波器类型: {filter_type}，已跳过", stacklevel=3)
    return values


def apply_filter_pipeline(values, fs=None, pipeline=None):
    """按顺序对一维信号应用多个滤波器。

    Parameters
    ----------
    values : array-like
        输入信号。
    fs : float or None
        采样率（Hz）；高通/带通必需，缺失时跳过并 warning。
    pipeline : list[dict], str, or None
        滤波步骤列表。每步为 ``{"type": "median", ...}``。
        ``None`` 时原样返回。

    支持的 type
    -----------
    median, hampel, highpass, bandpass
    （lowpass 暂未实现）

    Returns
    -------
    np.ndarray
        滤波后的信号。
    """
    values = np.asarray(values, dtype=float)
    if pipeline is None:
        return values

    if isinstance(pipeline, str):
        pipeline = [{"type": pipeline}]

    filtered = values
    for step in pipeline:
        filtered = _apply_single_filter(filtered, fs, step)
    return filtered
