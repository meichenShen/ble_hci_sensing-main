"""Recorded analysis scenarios (data path + segment boundaries).

Scenario JSON files live under ``config/scenarios/``. Scripts and notebooks
load them via :func:`load_scenario` instead of inlining ``segment_config``.

Example::

    from ble_analysis.scenarios import load_scenario, print_scenario_summary

    scenario = load_scenario("cs_091339", project_root=project_root)
    filepath = scenario.resolve_data_path(project_root)
    segment_config = scenario.segment_config
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

from ble_analysis.paths import find_project_root

PathLike = Union[str, Path]


@dataclass(frozen=True)
class ScenarioConfig:
    """One recorded CS/DF analysis scenario."""

    id: str
    name: str
    data_file: str
    segments: Dict[str, dict]
    modality: str = "CS"
    description: str = ""
    source_notebook: str = ""
    default_channel: Optional[int] = None

    @property
    def segment_config(self) -> Dict[str, dict]:
        """Alias for ``segments`` (matches ``segments.py`` API)."""
        return self.segments

    @property
    def tag(self) -> str:
        """Short id for figure/report prefixes (e.g. ``091339`` from ``cs_091339``)."""
        if self.id.startswith("cs_"):
            return self.id[3:]
        if self.id.startswith("df_"):
            return self.id[3:]
        return self.id

    def resolve_data_path(self, project_root: Optional[PathLike] = None) -> Path:
        root = Path(project_root) if project_root is not None else find_project_root()
        path = Path(self.data_file)
        if path.is_absolute():
            return path
        return (root / path).resolve()


def default_scenarios_dir(project_root: Optional[PathLike] = None) -> Path:
    root = Path(project_root) if project_root is not None else find_project_root()
    return root / "config" / "scenarios"


def list_scenario_ids(*, scenarios_dir: Optional[PathLike] = None) -> List[str]:
    directory = Path(scenarios_dir) if scenarios_dir is not None else default_scenarios_dir()
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.json"))


def load_scenario(
    scenario_id: str,
    *,
    project_root: Optional[PathLike] = None,
    scenarios_dir: Optional[PathLike] = None,
) -> ScenarioConfig:
    """Load a scenario by id (``cs_091339``) or explicit ``.json`` path."""
    explicit = Path(scenario_id)
    if explicit.suffix == ".json" and explicit.is_file():
        config_path = explicit.resolve()
    else:
        directory = (
            Path(scenarios_dir)
            if scenarios_dir is not None
            else default_scenarios_dir(project_root)
        )
        config_path = directory / f"{scenario_id}.json"
        if not config_path.is_file():
            available = list_scenario_ids(scenarios_dir=directory)
            hint = ", ".join(available) if available else "(none)"
            raise FileNotFoundError(
                f"Scenario '{scenario_id}' not found at {config_path}. Available: {hint}"
            )

    with config_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return _parse_scenario(raw, default_id=config_path.stem)


def _parse_scenario(raw: dict, *, default_id: str) -> ScenarioConfig:
    segments = raw.get("segments") or raw.get("segment_config")
    if not segments:
        raise ValueError(f"Scenario '{default_id}' must define 'segments'")

    data_file = raw.get("data_file") or raw.get("filepath")
    if not data_file:
        raise ValueError(f"Scenario '{default_id}' must define 'data_file'")

    return ScenarioConfig(
        id=raw.get("id", default_id),
        name=raw.get("name", default_id),
        data_file=data_file,
        segments=segments,
        modality=raw.get("modality", "CS"),
        description=raw.get("description", ""),
        source_notebook=raw.get("source_notebook", ""),
        default_channel=raw.get("default_channel"),
    )


def print_scenario_summary(scenario: ScenarioConfig) -> None:
    """Print segment table (same layout as analysis notebooks)."""
    print(f"=== Scenario: {scenario.id} — {scenario.name} ===")
    if scenario.description:
        print(scenario.description)
    print(f"Data: {scenario.data_file}")
    if scenario.source_notebook:
        print(f"Source: {scenario.source_notebook}")
    print(f"{'段落':<6} {'起始index':<12} {'结束index':<12} {'类型':<10} {'长度':<10}")
    print("-" * 60)
    for seg_name in sorted(scenario.segments.keys()):
        seg = scenario.segments[seg_name]
        start_idx = seg["start"]
        end_idx = seg["end"]
        seg_type = seg.get("type", "breath")
        length = end_idx - start_idx + 1
        print(f"{seg_name:<6} {start_idx:<12} {end_idx:<12} {seg_type:<10} {length:<10}")
    n_breath = sum(1 for s in scenario.segments.values() if s.get("type") == "breath")
    n_apnea = sum(1 for s in scenario.segments.values() if s.get("type") == "apnea")
    print(
        f"\n✓ 共 {len(scenario.segments)} 段：{n_breath} breath + {n_apnea} apnea"
    )
