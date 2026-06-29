"""Jupyter Notebook 环境引导。

注意：在 ``from ble_analysis... import ...`` 之前，
notebook 必须先把 ``project_root / "src"`` 加入 ``sys.path``，
否则会出现 ``ModuleNotFoundError``。
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def find_project_root(start=None):
    """向上查找含 ``src/`` 的项目根目录。见 ``paths.find_project_root``。"""
    start = Path.cwd().resolve() if start is None else Path(start).resolve()
    root = next((p for p in [start, *start.parents] if (p / "src").is_dir()), None)
    if root is None:
        raise FileNotFoundError("未找到项目根目录（缺少 src/ 目录）")
    return root


def ensure_src_on_path(project_root=None):
    """将 ``project_root/src`` 插入 ``sys.path`` 首位。

    **必须在 import ble_analysis 之前调用**（或在 notebook 中内联等价代码）。

    Returns
    -------
    tuple[Path, Path]
        ``(project_root, src_dir)``。
    """
    project_root = find_project_root() if project_root is None else Path(project_root)
    src_dir = project_root / "src"
    src_str = str(src_dir)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)
    return project_root, src_dir


def init_notebook(project_root=None):
    """初始化 notebook 运行环境。

    依次完成：确保 ``src/`` 在路径中 → 创建输出目录 → 设置 matplotlib 默认风格。

    Parameters
    ----------
    project_root : Path-like, optional
        若已在外部找到项目根，可传入以避免重复搜索。

    Returns
    -------
    dict
        含 ``project_root``, ``FIGURES_DIR``, ``PROCESSED_DIR``, ``REPORTS_DIR``,
        以及 ``plt``、``np`` 引用。
    """
    project_root, src_dir = ensure_src_on_path(project_root)

    from ble_analysis.paths import ensure_output_dirs
    from ble_analysis.plotting import setup_plot_style

    output_dirs = ensure_output_dirs(project_root)
    setup_plot_style()

    return {
        "project_root": project_root,
        "src_dir": src_dir,
        "FIGURES_DIR": output_dirs["figures_dir"],
        "PROCESSED_DIR": output_dirs["processed_dir"],
        "REPORTS_DIR": output_dirs["reports_dir"],
        "plt": plt,
        "np": np,
    }
