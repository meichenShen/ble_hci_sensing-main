"""Convert selected Jupyter notebooks to segmented .py scripts.

Output goes to ``notebooks/scripts/``. Each markdown/code cell becomes a
``# %% [markdown]`` or ``# %%`` section (VS Code / Spyder / Jupyter compatible).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS_DIR = ROOT / "notebooks"
OUT_DIR = NOTEBOOKS_DIR / "scripts"

# (source .ipynb, output .py basename)
TARGETS = [
    ("glb_cs_full_pipeline_demo.ipynb", "glb_cs_full_pipeline_demo.py"),
    ("glb_cs_segment_breath_analysis.ipynb", "glb_cs_segment_breath_analysis.py"),
    ("load_df_saved_frames_show_analysis.ipynb", "load_df_saved_frames_show_analysis.py"),
]


def _markdown_cell_lines(source: str) -> list[str]:
    lines = ["# %% [markdown]\n"]
    for line in source.splitlines():
        lines.append(f"# {line}\n" if line else "#\n")
    return lines


def _code_cell_lines(source: str) -> list[str]:
    lines = ["# %%\n"]
    if source:
        if not source.endswith("\n"):
            source = source + "\n"
        lines.append(source)
    return lines


def notebook_to_py(nb_path: Path) -> str:
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    out: list[str] = [
        f'"""Segmented script converted from ``{nb_path.name}``.\n\n'
        f"Run section-by-section using ``# %%`` cell markers "
        f"(VS Code Python Interactive / Spyder / ``jupyter lab``).\n"
        f'Source notebook: ``notebooks/{nb_path.name}``.\n"""\n\n',
    ]

    for cell in nb["cells"]:
        cell_type = cell.get("cell_type")
        source = "".join(cell.get("source", []))

        if cell_type == "markdown":
            if not source.strip():
                continue
            out.extend(_markdown_cell_lines(source))
            out.append("\n")
        elif cell_type == "code":
            out.extend(_code_cell_lines(source))
            out.append("\n")

    return "".join(out).rstrip() + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for nb_name, py_name in TARGETS:
        nb_path = NOTEBOOKS_DIR / nb_name
        if not nb_path.is_file():
            raise FileNotFoundError(nb_path)

        out_path = OUT_DIR / py_name
        out_path.write_text(notebook_to_py(nb_path), encoding="utf-8")
        print(f"Wrote {out_path.relative_to(ROOT)}")

    print(f"Done. Scripts in {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
