"""项目路径与输出目录管理。

Notebook 与脚本通过向上查找含 ``src/`` 的目录来定位项目根，
并在 ``outputs/`` 下使用 figures / processed / reports 三个子目录。
"""

from pathlib import Path

FIGURES_DIR_NAME = "figures"
PROCESSED_DIR_NAME = "processed"
REPORTS_DIR_NAME = "reports"


def find_project_root(start=None, marker="src"):
    """向上查找项目根目录。

    从 ``start``（默认当前工作目录）开始，逐级向父目录搜索，
    直到找到包含 ``marker`` 子目录（默认 ``src``）的路径。

    Parameters
    ----------
    start : Path-like, optional
        起始目录；默认 ``Path.cwd()``。
    marker : str, optional
        标记子目录名，默认 ``"src"``。

    Returns
    -------
    Path
        项目根目录绝对路径。

    Raises
    ------
    FileNotFoundError
        找不到含 marker 的目录时抛出。
    """
    start = Path.cwd().resolve() if start is None else Path(start).resolve()
    for path in [start, *start.parents]:
        if (path / marker).is_dir():
            return path
    raise FileNotFoundError(f"未找到项目根目录（缺少 {marker}/ 目录）")


def ensure_output_dirs(project_root=None):
    """创建标准输出目录并返回路径字典。

    在 ``project_root/outputs/`` 下创建 ``figures``、``processed``、``reports``，
    若已存在则跳过。

    Returns
    -------
    dict
        ``project_root``, ``figures_dir``, ``processed_dir``, ``reports_dir``。
    """
    if project_root is None:
        project_root = find_project_root()
    project_root = Path(project_root)
    figures_dir = project_root / "outputs" / FIGURES_DIR_NAME
    processed_dir = project_root / "outputs" / PROCESSED_DIR_NAME
    reports_dir = project_root / "outputs" / REPORTS_DIR_NAME
    for directory in (figures_dir, processed_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return {
        "project_root": project_root,
        "figures_dir": figures_dir,
        "processed_dir": processed_dir,
        "reports_dir": reports_dir,
    }
