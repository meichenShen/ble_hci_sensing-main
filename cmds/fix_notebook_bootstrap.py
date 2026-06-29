"""Fix notebook bootstrap cells: set sys.path before importing ble_analysis."""

import json
from pathlib import Path

BOOTSTRAP = """import sys
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
"""

DEMO_EXTRA = """
from ble_analysis.data import load_ble_frames
from ble_analysis.filters import apply_filter_pipeline
"""

NB_DIR = Path(__file__).resolve().parents[1] / "notebooks"

for name in [
    "glb_cs_load_and_explore.ipynb",
    "glb_cs_full_pipeline_demo.ipynb",
    "glb_cs_segment_breath_analysis.ipynb",
]:
    path = NB_DIR / name
    nb = json.loads(path.read_text(encoding="utf-8"))
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        src = "".join(cell.get("source", []))
        if "from ble_analysis.bootstrap import init_notebook" not in src:
            continue
        if "_src = project_root" in src:
            print(f"skip (already fixed): {name}")
            break
        source = BOOTSTRAP.splitlines(keepends=True)
        if name == "glb_cs_full_pipeline_demo.ipynb":
            source.extend(DEMO_EXTRA.strip().splitlines(keepends=True))
            source.append("\n")
        cell["source"] = source
        path.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"fixed: {name}")
        break
