"""非均匀时间序列重采样。

当前仅支持线性插值（``np.interp``），由 notebook 显式调用，
不在加载或通道提取阶段自动执行。
"""

import numpy as np


def resample_to_uniform_grid(time_sec, values, target_fs=None, method="linear"):
    """将非均匀时间序列重采样到均匀网格（线性插值）。

    Parameters
    ----------
    time_sec, values : array-like
        原始时间与数值；长度不足 2 时返回空数组。
    target_fs : float, optional
        目标采样率；None 时用 ``1 / mean(diff(time_sec))``。
    method : str
        目前仅支持 ``"linear"``。

    Returns
    -------
    dict
        ``time_sec``, ``values``, ``target_fs``。
    """
    time_sec = np.asarray(time_sec, dtype=float)
    values = np.asarray(values, dtype=float)

    if len(time_sec) < 2 or len(values) < 2:
        return {
            "time_sec": np.array([]),
            "values": np.array([]),
            "target_fs": target_fs,
        }

    if method != "linear":
        raise ValueError(f"Unsupported resampling method: {method}")

    if target_fs is None:
        mean_dt = float(np.mean(np.diff(time_sec)))
        target_fs = 1.0 / mean_dt if mean_dt > 0 else 1.0

    dt = 1.0 / target_fs
    uniform_time = np.arange(time_sec[0], time_sec[-1] + dt / 2, dt)
    resampled_values = np.interp(uniform_time, time_sec, values)

    return {
        "time_sec": uniform_time,
        "values": resampled_values,
        "target_fs": float(target_fs),
    }
