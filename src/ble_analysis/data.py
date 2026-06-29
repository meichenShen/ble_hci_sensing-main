"""BLE 帧数据加载。

封装 ``data_saver.DataSaver``，对 notebook 提供统一的
``load_ble_frames(filepath) -> (data, frames)`` 接口。
"""

import os
from pathlib import Path

from data_saver import DataSaver


def load_ble_frames(filepath, verbose=True):
    """加载 BLE JSON/JSONL 帧数据。

    内部使用 ``DataSaver.load_frames``，自动识别 JSON 与 JSONL 格式。

    Parameters
    ----------
    filepath : str or Path
        帧数据文件路径。
    verbose : bool, optional
        是否打印文件大小、加载状态、帧数量；默认 True。

    Returns
    -------
    data : dict or None
        含 ``version``, ``frames``, ``saved_at`` 等字段；失败时为 None。
    frames : list
        ``data["frames"]``，失败或缺失时为 ``[]``。
    """
    filepath = str(filepath)

    if not os.path.exists(filepath):
        if verbose:
            print(f"⚠️  文件不存在: {filepath}")
            print(f"当前目录: {os.getcwd()}")
            print("\n请修改 filepath 变量，指向正确的文件路径")
        return None, []

    if verbose:
        print(f"✓ 找到文件: {filepath}")
        print(f"文件大小: {os.path.getsize(filepath) / 1024 / 1024:.2f} MB")
        print(f"正在加载: {filepath}")

    saver = DataSaver()
    data = saver.load_frames(filepath)

    if data is None:
        if verbose:
            print("✗ 加载失败")
        return None, []

    frames = data.get("frames", [])
    if verbose:
        print("✓ 加载成功")
        print(f"✓ 共加载 {len(frames)} 帧数据")
    return data, frames
