"""chFusion Plan 2 — cross-domain repeatability verification.

Re-runs the full Plan 2 pipeline on a target scenario and compares leaderboard
metrics across multiple metal-plate recordings (``config/scenarios/*.json``).

Run: ``python notebooks/scripts/chFusion_plan2_diff_domain_verify.py``
"""

# %% [markdown]
# # Plan 2 cross-domain verify
#
# | Step | Content |
# |------|---------|
# | 0 | Bootstrap + scenario config |
# | 1 | Run Plan 2 validation (η selector) on target scenario |
# | 2 | Complementarity waveforms |
# | 3 | Comparison table + overview figures |
# | 4 | Multi-domain leaderboard + hypothesis checklist |
# | 5 | Cross-domain aggregate mean ± std bar chart |

# %% [markdown]
# ## 0. Environment bootstrap

# %%
import sys
from pathlib import Path

import numpy as np

_cwd = Path.cwd().resolve()
project_root = next(
    (p for p in [_cwd, *_cwd.parents] if (p / "src").is_dir()),
    None,
)
if project_root is None:
    raise FileNotFoundError("Project root not found (missing src/ directory)")

_src = project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from ble_analysis.bootstrap import init_notebook

_env = init_notebook(project_root)
project_root = _env["project_root"]
FIGURES_DIR = _env["FIGURES_DIR"]
REPORTS_DIR = _env["REPORTS_DIR"]

# %% [markdown]
# ## 0b. Parameters

# %%
from ble_analysis.chfusion import (
    COMPLEMENTARITY_REFERENCE_VARIABLES,
    ChFusionConfig,
    Plan2Config,
    build_plan2_leaderboard_rows,
    plot_complementarity_waveforms_all,
    plot_plan2_leaderboard_bars,
    plot_plan2_cross_domain_aggregate_bars,
    plot_plan2_segment_method_heatmap,
    plot_plan2_violins_by_category,
    print_complementarity_window_summary,
    print_plan2_cross_domain_aggregate_table,
    print_plan2_comparison_table,
    run_plan2_validation,
)
from ble_analysis.data import load_ble_frames
from ble_analysis.scenarios import ScenarioConfig, load_scenario, print_scenario_summary
from ble_analysis.segments import BreathMetricParams, FilterParams

# Target scenario: full pipeline + figures
SCENARIO_ID = "cs_102621"
# All scenarios included in cross-domain comparison table
COMPARE_SCENARIO_IDS = ("cs_091339", "cs_095806", "cs_102621")

scenario = load_scenario(SCENARIO_ID, project_root=project_root)
filepath = scenario.resolve_data_path(project_root)
segment_config = scenario.segment_config
print_scenario_summary(scenario)

DOMAIN_ID = scenario.tag

filter_params = FilterParams()
metric_params = BreathMetricParams()
chfusion_config = ChFusionConfig(
    breath_freq_low=metric_params.breath_freq_low,
    breath_freq_high=metric_params.breath_freq_high,
    window_length_sec=metric_params.window_length_sec,
    step_length_sec=metric_params.step_length_sec,
    enable_consensus=False,
)

REFERENCE_VARIABLE = "phases"
COMPLEMENTARITY_VARS = list(COMPLEMENTARITY_REFERENCE_VARIABLES)
plan2_config = Plan2Config(channel_metric="energy_ratio")

FIG_PREFIX = f"plan2_{DOMAIN_ID}"

print(f"Target domain: {DOMAIN_ID} | file: {filepath.name}")
print("Compare scenarios:", ", ".join(COMPARE_SCENARIO_IDS))
print("Plan 2 channel metric:", plan2_config.channel_metric)
print("Complementarity refs:", ", ".join(COMPLEMENTARITY_VARS))

# %% [markdown]
# ## Helpers — report paths, load-or-run, multi-domain table

# %%


def plan2_report_path(scenario_id: str) -> Path:
    sc = load_scenario(scenario_id, project_root=project_root)
    if scenario_id == "cs_091339":
        return REPORTS_DIR / "chfusion_plan2_validation.npy"
    return REPORTS_DIR / f"chfusion_plan2_{sc.tag}_validation.npy"


REPORT_PATH = plan2_report_path(SCENARIO_ID)


def _run_plan2_for_scenario(sc: ScenarioConfig, *, verbose: bool = True) -> dict:
    _data, frames = load_ble_frames(sc.resolve_data_path(project_root), verbose=False)
    return run_plan2_validation(
        frames,
        sc.segment_config,
        filter_params=filter_params,
        metric_params=metric_params,
        config=chfusion_config,
        plan2_config=plan2_config,
        reference_variable=REFERENCE_VARIABLE,
        complementarity_variables=COMPLEMENTARITY_VARS,
        verbose=verbose,
    )


def ensure_plan2_report(scenario_id: str, *, verbose: bool = False) -> tuple[dict, str]:
    """Return (plan2_result, tag); run validation if cached report missing."""
    sc = load_scenario(scenario_id, project_root=project_root)
    path = plan2_report_path(scenario_id)
    if path.is_file():
        print(f"Loaded cached report: {path.name}")
        return np.load(path, allow_pickle=True).item(), sc.tag
    print(f"Running Plan 2 validation for {scenario_id} …")
    result = _run_plan2_for_scenario(sc, verbose=verbose)
    np.save(path, result, allow_pickle=True)
    print(f"Saved: {path}")
    return result, sc.tag


def _leaderboard_lookup(plan2_result: dict) -> dict:
    return {r["label"]: r for r in build_plan2_leaderboard_rows(plan2_result)}


def _err(plan2_result: dict, label: str) -> float:
    row = _leaderboard_lookup(plan2_result).get(label)
    return float(row["mean_rel_err_pct"]) if row else float("nan")


COMPARE_LABELS = [
    "Single Remote amplitude",
    "Single Local amplitude",
    "Single Total phase (unwrapped)",
    "Uniform Remote amplitude",
    "Modal top2 equal",
    "Modal η-weight",
    "Modal equal",
]


def print_multi_domain_leaderboard(
    results_by_tag: dict[str, dict],
    scenario_order: list[str],
) -> None:
    tags = [load_scenario(sid, project_root=project_root).tag for sid in scenario_order]
    col_w = 10
    header = f"{'方法':<32}" + "".join(f"{t:>{col_w}}" for t in tags)
    print(f"\n=== Cross-domain leaderboard ({' / '.join(tags)}) ===")
    print(header)
    print("-" * (32 + col_w * len(tags)))
    for lbl in COMPARE_LABELS:
        row = f"{lbl:<32}"
        for tag in tags:
            val = _leaderboard_lookup(results_by_tag[tag]).get(lbl, {}).get(
                "mean_rel_err_pct", np.nan
            )
            row += f"{val:>{col_w}.2f}" if np.isfinite(val) else f"{'—':>{col_w}}"
        print(row)


def print_hypothesis_checklist(plan2_result: dict, domain_tag: str) -> None:
    s_rem = _err(plan2_result, "Single Remote amplitude")
    s_loc = _err(plan2_result, "Single Local amplitude")
    s_pha = _err(plan2_result, "Single Total phase (unwrapped)")
    u_rem = _err(plan2_result, "Uniform Remote amplitude")
    m_top2 = _err(plan2_result, "Modal top2 equal")
    m_eq = _err(plan2_result, "Modal equal")

    print(f"\n=== Hypothesis checklist ({domain_tag}) ===")
    checks = [
        (
            "Single remote 优于 Single local",
            np.isfinite(s_rem) and np.isfinite(s_loc) and s_rem < s_loc,
            f"remote={s_rem:.2f}% local={s_loc:.2f}%",
        ),
        (
            "Single remote 优于 Uniform remote",
            np.isfinite(s_rem) and np.isfinite(u_rem) and s_rem < u_rem,
            f"single={s_rem:.2f}% uniform={u_rem:.2f}%",
        ),
        (
            "Modal 介于 Single remote 与 Single phase 之间",
            np.isfinite(s_rem) and np.isfinite(s_pha) and np.isfinite(m_eq)
            and min(s_rem, s_pha) <= m_eq <= max(s_rem, s_pha),
            f"remote={s_rem:.2f}% modal={m_eq:.2f}% phase={s_pha:.2f}%",
        ),
        (
            "Modal top2 ≤ Modal equal（动态去掉较差变量）",
            np.isfinite(m_top2) and np.isfinite(m_eq) and m_top2 <= m_eq + 0.01,
            f"top2={m_top2:.2f}% equal={m_eq:.2f}%",
        ),
    ]
    for name, ok, detail in checks:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}  ({detail})")

# %% [markdown]
# ## 1. Run Plan 2 validation (target scenario)

# %%
data, frames = load_ble_frames(filepath, verbose=False)

plan2 = run_plan2_validation(
    frames,
    segment_config,
    filter_params=filter_params,
    metric_params=metric_params,
    config=chfusion_config,
    plan2_config=plan2_config,
    reference_variable=REFERENCE_VARIABLE,
    complementarity_variables=COMPLEMENTARITY_VARS,
    verbose=True,
)

print_complementarity_window_summary(plan2["complementarity_by_reference"])

# %% [markdown]
# ## 2. Complementarity waveform figures

# %%
complementarity_paths = plot_complementarity_waveforms_all(
    plan2["complementarity_by_reference"],
    reference_variables=COMPLEMENTARITY_VARS,
    figures_dir=FIGURES_DIR,
    filename_prefix=f"{FIG_PREFIX}_complementarity",
    show=True,
    save=True,
)
print(f"Saved {len(complementarity_paths)} complementarity figure(s)")

# %% [markdown]
# ## 3. Comparison table + overview figures (target domain only)
#
# ``leaderboard_bars`` = 当前场景单域排行；§5 的 aggregate 才是三场景 mean±std，勿混淆。

# %%
print_plan2_comparison_table(plan2)

np.save(REPORT_PATH, plan2, allow_pickle=True)
print(f"Saved: {REPORT_PATH}")

overview_paths = []
for fname, plot_fn in (
    (f"{FIG_PREFIX}_leaderboard_bars.pdf", plot_plan2_leaderboard_bars),
    (f"{FIG_PREFIX}_segment_method_heatmap.pdf", plot_plan2_segment_method_heatmap),
    (f"{FIG_PREFIX}_violins_by_category.pdf", plot_plan2_violins_by_category),
):
    plot_fn(plan2, figures_dir=FIGURES_DIR, filename=fname, show=True, save=True)
    overview_paths.append(FIGURES_DIR / fname)
print(f"Saved {len(overview_paths)} overview figure(s)")

# %% [markdown]
# ## 4. Multi-domain comparison (all scenarios)

# %%
results_by_tag: dict[str, dict] = {}
for sid in COMPARE_SCENARIO_IDS:
    if sid == SCENARIO_ID:
        results_by_tag[DOMAIN_ID] = plan2
        continue
    result, tag = ensure_plan2_report(sid, verbose=False)
    results_by_tag[tag] = result

print_multi_domain_leaderboard(results_by_tag, list(COMPARE_SCENARIO_IDS))

for sid in COMPARE_SCENARIO_IDS:
    tag = load_scenario(sid, project_root=project_root).tag
    print_hypothesis_checklist(results_by_tag[tag], tag)

# %% [markdown]
# ## 5. Cross-domain aggregate (mean ± std over scenarios)
#
# 与 §3 单域 ``leaderboard_bars`` 不同：此处对三场景 err% 取 mean，误差线为跨场景 std。

# %%
compare_tags = [load_scenario(sid, project_root=project_root).tag for sid in COMPARE_SCENARIO_IDS]

print_plan2_cross_domain_aggregate_table(
    results_by_tag,
    domain_order=compare_tags,
)

plot_plan2_cross_domain_aggregate_bars(
    results_by_tag,
    domain_order=compare_tags,
    figures_dir=FIGURES_DIR,
    filename="plan2_cross_domain_aggregate_bars.pdf",
    show=True,
    save=True,
)
