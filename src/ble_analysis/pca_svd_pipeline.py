"""chFusion PCA/SVD 实验流水线 — 可复用配置、排行榜与跨场景聚合。

脚本 ``chFusion_pca_svd*.py`` 应从此模块导入实验表与 pipeline，
避免在 notebook 与 CLI 之间重复定义。

参见 ``docs/chFusion_pca_svd_plan.md`` §10.5–§11。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from ble_analysis.chfusion import (
    CS_SIGNAL_VARIABLES,
    ChFusionConfig,
    Plan2Config,
    _overall_rel_error,
    _seg_bpm_stats,
    build_plan2_leaderboard_rows,
    estimate_segment_bpm_methods,
    run_multichannel_segment_filtering,
    run_plan2_validation,
)
from ble_analysis.data import load_ble_frames
from ble_analysis.pca_svd import (
    MODAL_PCA_VARIABLES,
    PcaSvdConfig,
    align_waveform_sign,
    build_channel_data_matrix,
    build_multivariable_data_matrix,
    compute_channel_energy_weights,
    diagnose_complex_integration_harmonics,
    extract_breath_waveform_complex_pca,
    extract_breath_waveform_complex_svd,
    extract_breath_waveform_pca,
    extract_breath_waveform_svd,
    extract_integration_pc1_spectrum,
    run_pca_complex_dual_amp,
    run_pca_complex_eta_blend,
    run_pca_complex_fusion,
    run_pca_complex_modal_fusion,
    run_pca_modal_fusion,
    run_pca_topk_bpm,
)
from ble_analysis.scenarios import load_scenario
from ble_analysis.segments import (
    BreathMetricParams,
    FilterParams,
    _estimate_breathing_freq_hz,
    _sliding_window_indices,
)

# ---------------------------------------------------------------------------
# 默认场景与实验表
# ---------------------------------------------------------------------------

DEFAULT_SCENARIO_ID = "cs_102621"
COMPARE_SCENARIO_IDS: Tuple[str, ...] = ("cs_091339", "cs_095806", "cs_102621")
DIAG_SCENARIO_ID = "cs_091339"

REQUIRED_PCA_V2_CACHE_KEYS: Tuple[str, ...] = (
    "PCA-Modal3 top2/ch-η",
    "PCA-Cmplx-Modal rem+loc top2",
    "PCA-Cmplx η-blend ch-η",
    "PCA-Modal3 top8/ch-η",
    "PCA-HP Remote top8/ch-η",
)

CROSS_DOMAIN_COMPARE_LABELS: Tuple[str, ...] = (
    "Modal η-weight",
    "Modal top2 equal",
    "PCA-Modal3 top2/ch-η",
    "PCA-Modal3 top8/ch-η",
    "PCA-Modal3 top16/ch-η",
    "PCA-Cmplx-Modal rem+loc top2",
    "PCA-Cmplx Total ch-η",
    "PCA-Cmplx Total top8/ch-η",
    "PCA-Cmplx η-blend ch-η",
    "PCA-Cmplx-Modal rem+loc η",
    "PCA-Modal3 η/ch-η",
    "PCA-HP Remote top8/ch-η",
    "PCA-HP Remote ch-η",
    "PCA Total Amp",
    "Uniform Remote amplitude",
    "Single Remote amplitude",
)

PCA_SVD_EXPERIMENTS: Dict[str, dict] = {
    "PCA Remote Amp": {"method": "pca", "variable": "remote_amplitudes"},
    "PCA Local Amp": {"method": "pca", "variable": "local_amplitudes"},
    "PCA Total Amp": {"method": "pca", "variable": "amplitudes"},
    "SVD Remote Amp": {"method": "svd_real", "variable": "remote_amplitudes"},
    "SVD Local Amp": {"method": "svd_real", "variable": "local_amplitudes"},
    "SVD Total Amp": {"method": "svd_real", "variable": "amplitudes"},
    "PCA Phase": {"method": "pca", "variable": "phases"},
    "SVD Phase": {"method": "svd_real", "variable": "phases"},
    "SVD Complex Total": {
        "method": "svd_complex", "variable": "phases", "complex_amp_var": "amplitudes",
    },
    "SVD Complex Remote": {
        "method": "svd_complex", "variable": "phases", "complex_amp_var": "remote_amplitudes",
    },
    "SVD Complex Local": {
        "method": "svd_complex", "variable": "phases", "complex_amp_var": "local_amplitudes",
    },
    "PCA Stacked": {
        "method": "pca",
        "variable": ["remote_amplitudes", "local_amplitudes", "amplitudes"],
    },
}

PCA_V2_EXPERIMENTS: Dict[str, dict] = {
    "PCA-HP Remote ch-uniform": {
        "method": "pca", "variable": "remote_amplitudes",
        "channel_weight": "uniform", "signal_key": "highpass_filtered",
    },
    "PCA-HP Remote ch-η": {
        "method": "pca", "variable": "remote_amplitudes",
        "channel_weight": "energy_ratio", "signal_key": "highpass_filtered",
    },
    "PCA-HP Phase ch-uniform": {
        "method": "pca", "variable": "phases",
        "channel_weight": "uniform", "signal_key": "highpass_filtered",
    },
    "PCA-HP Phase ch-η": {
        "method": "pca", "variable": "phases",
        "channel_weight": "energy_ratio", "signal_key": "highpass_filtered",
    },
    "PCA-HP Total ch-uniform": {
        "method": "pca", "variable": "amplitudes",
        "channel_weight": "uniform", "signal_key": "highpass_filtered",
    },
    "PCA-HP Total ch-η": {
        "method": "pca", "variable": "amplitudes",
        "channel_weight": "energy_ratio", "signal_key": "highpass_filtered",
    },
}

PCA_MODAL_EXPERIMENTS: Dict[str, dict] = {
    "PCA-Modal3 eq/ch-uni": {
        "modal_variables": MODAL_PCA_VARIABLES,
        "channel_weight": "uniform", "modal_weight": "equal",
    },
    "PCA-Modal3 η/ch-η": {
        "modal_variables": MODAL_PCA_VARIABLES,
        "channel_weight": "energy_ratio", "modal_weight": "energy_ratio",
    },
    "PCA-Modal amp+pha eq": {
        "modal_variables": ("remote_amplitudes", "phases"),
        "channel_weight": "uniform", "modal_weight": "equal",
    },
    "PCA-Modal amp+pha η": {
        "modal_variables": ("remote_amplitudes", "phases"),
        "channel_weight": "energy_ratio", "modal_weight": "energy_ratio",
    },
    "PCA-Modal3 top2/ch-η": {
        "modal_variables": MODAL_PCA_VARIABLES,
        "channel_weight": "energy_ratio", "modal_weight": "top2_equal",
    },
    "PCA-Modal amp+pha top2": {
        "modal_variables": ("remote_amplitudes", "phases"),
        "channel_weight": "energy_ratio", "modal_weight": "top2_equal",
    },
}

PCA_COMPLEX_EXPERIMENTS: Dict[str, dict] = {
    "PCA-Cmplx Total ch-uni": {"amp_var": "amplitudes", "channel_weight": "uniform"},
    "PCA-Cmplx Total ch-η": {"amp_var": "amplitudes", "channel_weight": "energy_ratio"},
}

PCA_COMPLEX_INTEGRATION_EXPERIMENTS: Dict[str, dict] = {
    "PCA-Cmplx Dual-Amp ch-uni": {"runner": "dual_amp", "channel_weight": "uniform"},
    "PCA-Cmplx Dual-Amp ch-η": {"runner": "dual_amp", "channel_weight": "energy_ratio"},
    "PCA-Cmplx η-blend ch-uni": {"runner": "eta_blend", "channel_weight": "uniform"},
    "PCA-Cmplx η-blend ch-η": {"runner": "eta_blend", "channel_weight": "energy_ratio"},
    "PCA-Cmplx-Modal rem+loc eq": {
        "runner": "complex_modal",
        "amp_variables": ("remote_amplitudes", "local_amplitudes"),
        "channel_weight": "uniform", "modal_weight": "equal",
    },
    "PCA-Cmplx-Modal rem+loc η": {
        "runner": "complex_modal",
        "amp_variables": ("remote_amplitudes", "local_amplitudes"),
        "channel_weight": "energy_ratio", "modal_weight": "energy_ratio",
    },
    "PCA-Cmplx-Modal rem+loc top2": {
        "runner": "complex_modal",
        "amp_variables": ("remote_amplitudes", "local_amplitudes"),
        "channel_weight": "energy_ratio", "modal_weight": "top2_equal",
    },
}

PCA_TOPK_EXPERIMENTS: Dict[str, dict] = {
    "PCA-HP Remote top8/ch-η": {
        "runner": "variable", "variable": "remote_amplitudes",
        "top_k": 8, "channel_weight": "energy_ratio",
    },
    "PCA-HP Remote top16/ch-η": {
        "runner": "variable", "variable": "remote_amplitudes",
        "top_k": 16, "channel_weight": "energy_ratio",
    },
    "PCA-Modal3 top8/ch-η": {
        "runner": "modal", "modal_variables": MODAL_PCA_VARIABLES,
        "channel_weight": "energy_ratio", "modal_weight": "energy_ratio",
        "top_k_channels": 8,
    },
    "PCA-Modal3 top16/ch-η": {
        "runner": "modal", "modal_variables": MODAL_PCA_VARIABLES,
        "channel_weight": "energy_ratio", "modal_weight": "energy_ratio",
        "top_k_channels": 16,
    },
    "PCA-Cmplx Total top8/ch-η": {
        "runner": "complex", "amp_var": "amplitudes",
        "channel_weight": "energy_ratio", "top_k_channels": 8,
    },
}

METHOD_CATEGORY_COLORS: Dict[str, str] = {
    "PCA": "#5A9BD5",
    "PCA HP": "#4A8BC2",
    "PCA Modal": "#9B7FBF",
    "SVD": "#70AD47",
    "SVD Complex": "#BF8FBF",
    "Stacked": "#EDB144",
    "Baseline": "#F0C8A0",
    "Single": "#E8A0A0",
    "Uniform": "#F0C8A0",
    "Modal": "#C9A0DC",
    "Plan2": "#C9A0DC",
}


@dataclass
class PcaSvdPipelineConfig:
    """单场景 / 跨场景 pipeline 共用配置。"""

    filter_params: FilterParams
    metric_params: BreathMetricParams
    chfusion_config: ChFusionConfig
    plan2_config: Plan2Config
    pca_svd_config: PcaSvdConfig
    pca_hp_config: PcaSvdConfig


def make_default_pipeline_config(
    metric_params: Optional[BreathMetricParams] = None,
) -> PcaSvdPipelineConfig:
    mp = metric_params or BreathMetricParams()
    return PcaSvdPipelineConfig(
        filter_params=FilterParams(),
        metric_params=mp,
        chfusion_config=ChFusionConfig(
            breath_freq_low=mp.breath_freq_low,
            breath_freq_high=mp.breath_freq_high,
            window_length_sec=mp.window_length_sec,
            step_length_sec=mp.step_length_sec,
            enable_consensus=False,
        ),
        plan2_config=Plan2Config(channel_metric="energy_ratio"),
        pca_svd_config=PcaSvdConfig(
            method="pca",
            normalize="zscore",
            min_channels=4,
            min_variance_ratio=0.10,
            signal_key="bandpass_filtered",
            breath_freq_low=mp.breath_freq_low,
            breath_freq_high=mp.breath_freq_high,
        ),
        pca_hp_config=PcaSvdConfig(
            method="pca",
            normalize="zscore",
            min_channels=4,
            min_variance_ratio=0.10,
            signal_key="highpass_filtered",
            breath_freq_low=mp.breath_freq_low,
            breath_freq_high=mp.breath_freq_high,
        ),
    )


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def window_bpm_from_waveform(
    waveform: np.ndarray,
    fs: float,
    breath_freq_low: float,
    breath_freq_high: float,
) -> float:
    if len(waveform) < 4 or not np.all(np.isfinite(waveform)):
        return np.nan
    wf = waveform - np.mean(waveform)
    f_hz = _estimate_breathing_freq_hz(wf, fs, breath_freq_low, breath_freq_high)
    return f_hz * 60.0 if np.isfinite(f_hz) else np.nan


def segment_rel_err_pct(errs: Sequence[float]) -> Tuple[float, float, int]:
    if not errs:
        return np.nan, np.nan, 0
    a = np.asarray(errs, dtype=float)
    std = float(np.std(a, ddof=1) * 100.0) if len(a) > 1 else 0.0
    return float(np.mean(a) * 100.0), std, len(a)


def modal_to_per_seg(modal_raw: dict, method_key: str) -> dict:
    out: Dict[str, Optional[dict]] = {}
    for seg_name, row in modal_raw.items():
        if row is None:
            out[seg_name] = None
            continue
        block = row.get(method_key)
        if block is None:
            out[seg_name] = None
            continue
        out[seg_name] = {**block, "bpm_gt": row.get("bpm_gt")}
    return out


def category_color(label: str, category: Optional[str] = None) -> str:
    if category:
        return METHOD_CATEGORY_COLORS.get(category, "#CCCCCC")
    if label.startswith("SVD Complex"):
        return METHOD_CATEGORY_COLORS["SVD Complex"]
    return METHOD_CATEGORY_COLORS.get(label.split()[0], "#CCCCCC")


def pca_svd_category(exp_name: str) -> str:
    if exp_name.startswith("SVD Complex"):
        return "SVD Complex"
    if (
        exp_name.startswith("PCA-Modal")
        or exp_name.startswith("PCA-Cmplx")
        or exp_name.startswith("PCA-Cmplx-Modal")
    ):
        return "PCA Modal"
    if exp_name.startswith("PCA-HP"):
        return "PCA HP"
    return exp_name.split()[0]


def leaderboard_lookup(leaderboard_rows: List[dict]) -> Dict[str, dict]:
    return {r["label"]: r for r in leaderboard_rows}


# ---------------------------------------------------------------------------
# v1 带通 PCA/SVD BPM
# ---------------------------------------------------------------------------


def run_pca_svd_bpm(
    multichannel_by_var: dict,
    segment_config: dict,
    *,
    method: str,
    variable_or_vars: Union[str, Sequence[str]],
    fs: float,
    metric_params: BreathMetricParams,
    pca_svd_config: Optional[PcaSvdConfig] = None,
    complex_amp_var: Optional[str] = None,
    verbose: bool = True,
) -> Dict[str, Optional[dict]]:
    """对每个呼吸段做滑窗 PCA/SVD → BPM 估计（v1 带通 / v2 高通由 config 决定）。"""
    pca_cfg = pca_svd_config or PcaSvdConfig()
    mp = metric_params
    win_len = int(round(mp.window_length_sec * fs))
    step_len = int(round(mp.step_length_sec * fs))
    results: Dict[str, Optional[dict]] = {}

    if isinstance(variable_or_vars, str):
        var_list = [variable_or_vars]
        is_stack = False
        label = variable_or_vars
    else:
        var_list = list(variable_or_vars)
        is_stack = True
        label = "+".join(var_list)

    if verbose:
        print(f"\n--- {method.upper()} on {label} ---")

    for seg_name in sorted(segment_config.keys()):
        seg_cfg = segment_config[seg_name]
        ref_mc = multichannel_by_var.get(
            var_list[0] if not is_stack else "remote_amplitudes", {}
        )
        ref_seg = ref_mc.get(seg_name)
        metadata = ref_seg.get("metadata", {}) if ref_seg else {}
        if metadata.get("segment_type") == "apnea" or seg_cfg.get("type") == "apnea":
            results[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt") or seg_cfg.get("bpm_gt")
        if is_stack:
            ch_lengths: Dict[Any, int] = {}
            for var in var_list:
                seg = multichannel_by_var.get(var, {}).get(seg_name)
                if seg is None or seg.get("channels") is None:
                    continue
                for ch, proc in seg["channels"].items():
                    sig = proc[var].get(pca_cfg.signal_key)
                    if sig is not None:
                        ch_lengths[ch] = min(ch_lengths.get(ch, len(sig)), len(sig))
            ch_list = sorted(k for k in ch_lengths if ch_lengths[k] >= win_len)
            ref_len = max(ch_lengths[c] for c in ch_list) if ch_list else 0
        else:
            var = var_list[0]
            seg = multichannel_by_var.get(var, {}).get(seg_name)
            if seg is None or seg.get("channels") is None:
                results[seg_name] = None
                continue
            ch_map = seg["channels"]
            ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
            ref_len = max(
                len(ch_map[c][var].get(pca_cfg.signal_key, [])) for c in ch_list
            )

        if ref_len < win_len:
            if verbose:
                print(f"  WARN {seg_name}: len={ref_len} < win={win_len}")
            results[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        bpms: List[float] = []
        prev_wf = None
        pc1_ratios: List[float] = []

        for st in starts:
            end_val = st + win_len
            sk = pca_cfg.signal_key
            if method in ("svd_complex", "pca_complex") and not is_stack:
                amp_var = complex_amp_var or "amplitudes"
                seg_amp = multichannel_by_var.get(amp_var, {}).get(seg_name)
                seg_pha = multichannel_by_var.get("phases", {}).get(seg_name)
                if seg_amp is None or seg_pha is None:
                    bpms.append(np.nan)
                    continue
                ch_map_amp = seg_amp["channels"]
                ch_map_pha = seg_pha["channels"]
                cols_c: List[np.ndarray] = []
                used: List[Any] = []
                for ch in ch_list:
                    pa = ch_map_amp.get(ch)
                    pp = ch_map_pha.get(ch)
                    if pa is None or pp is None:
                        continue
                    ba = pa[amp_var].get(sk)
                    bp = pp["phases"].get(sk)
                    if ba is None or bp is None or len(ba) < end_val or len(bp) < end_val:
                        continue
                    cols_c.append(ba[st:end_val] * np.exp(1j * bp[st:end_val]))
                    used.append(ch)
                if len(cols_c) < pca_cfg.min_channels:
                    bpms.append(np.nan)
                    continue
                x_c = np.column_stack(cols_c)
                ch_w = None
                if pca_cfg.channel_weight == "energy_ratio":
                    ch_w = compute_channel_energy_weights(
                        ch_map_amp, amp_var, used, st, end_val, fs, pca_cfg
                    )
                if method == "pca_complex":
                    waveform, info = extract_breath_waveform_complex_pca(
                        x_c, pca_cfg, seg_name, channel_weights=ch_w
                    )
                else:
                    waveform, info = extract_breath_waveform_complex_svd(x_c, pca_cfg, seg_name)
            elif not is_stack:
                x_mat, used_ch = build_channel_data_matrix(
                    ch_map, var, ch_list, st, end_val, sk
                )
                if x_mat.shape[1] < pca_cfg.min_channels:
                    bpms.append(np.nan)
                    continue
                ch_w = None
                if pca_cfg.channel_weight == "energy_ratio":
                    ch_w = compute_channel_energy_weights(
                        ch_map, var, used_ch, st, end_val, fs, pca_cfg
                    )
                if method == "pca":
                    waveform, info = extract_breath_waveform_pca(
                        x_mat, pca_cfg, seg_name, channel_weights=ch_w
                    )
                else:
                    waveform, info = extract_breath_waveform_svd(x_mat, pca_cfg, seg_name)
            else:
                ch_maps = {
                    v: multichannel_by_var.get(v, {}).get(seg_name, {}).get("channels", {})
                    for v in var_list
                }
                x_mat = build_multivariable_data_matrix(
                    ch_maps, var_list, ch_list, st, end_val, sk
                )
                if x_mat.shape[1] < pca_cfg.min_channels:
                    bpms.append(np.nan)
                    continue
                if method == "pca":
                    waveform, info = extract_breath_waveform_pca(x_mat, pca_cfg, seg_name)
                else:
                    waveform, info = extract_breath_waveform_svd(x_mat, pca_cfg, seg_name)

            pc1_ratios.append(info.get("pc1_variance_ratio", np.nan))
            waveform = align_waveform_sign(waveform, prev_wf)
            prev_wf = waveform.copy()
            bpms.append(
                window_bpm_from_waveform(
                    waveform, fs, mp.breath_freq_low, mp.breath_freq_high
                )
            )

        stats = _seg_bpm_stats(np.asarray(bpms, dtype=float), bpm_gt, len(starts))
        stats["bpm_gt"] = bpm_gt
        stats["pc1_variance_ratios"] = pc1_ratios
        stats["mean_pc1_ratio"] = float(np.nanmean(pc1_ratios)) if pc1_ratios else np.nan
        results[seg_name] = stats
        if verbose:
            e = stats["bpm_rel_err"]
            err_str = f"{e * 100:.2f}%" if np.isfinite(e) else "---"
            print(
                f"  {seg_name}: mean_rel_err={err_str}  "
                f"pc1_ratio={stats['mean_pc1_ratio']:.3f}"
            )
    return results


def run_pca_v2_suite(
    multichannel_by_var: dict,
    segment_config: dict,
    fs: float,
    metric_params: BreathMetricParams,
    pca_hp_cfg: PcaSvdConfig,
    *,
    verbose: bool = True,
) -> Dict[str, dict]:
    """高通 PCA 单变量 + 模态融合 + 复 PCA + 整合 + Top-K。"""
    pca_v2: Dict[str, dict] = {}
    for exp_name, exp_cfg in PCA_V2_EXPERIMENTS.items():
        cfg = replace(pca_hp_cfg, channel_weight=exp_cfg["channel_weight"])
        if verbose:
            print(f"\n--- PCA v2: {exp_name} ---")
        pca_v2[exp_name] = run_pca_svd_bpm(
            multichannel_by_var,
            segment_config,
            method=exp_cfg["method"],
            variable_or_vars=exp_cfg["variable"],
            fs=fs,
            metric_params=metric_params,
            pca_svd_config=cfg,
            verbose=verbose,
        )
    for exp_name, exp_cfg in PCA_MODAL_EXPERIMENTS.items():
        cfg = replace(pca_hp_cfg, channel_weight=exp_cfg["channel_weight"])
        raw = run_pca_modal_fusion(
            multichannel_by_var,
            modal_variables=exp_cfg["modal_variables"],
            channel_weight=exp_cfg["channel_weight"],
            modal_weight=exp_cfg["modal_weight"],
            top_k_channels=exp_cfg.get("top_k_channels"),
            metric_params=metric_params,
            pca_svd_config=cfg,
            verbose=verbose,
        )
        top_suffix = (
            f"_top{exp_cfg['top_k_channels']}" if exp_cfg.get("top_k_channels") else ""
        )
        mkey = (
            f"pca_modal_{exp_cfg['modal_weight']}_ch_{exp_cfg['channel_weight']}{top_suffix}"
        )
        pca_v2[exp_name] = modal_to_per_seg(raw, mkey)
    for exp_name, exp_cfg in PCA_COMPLEX_EXPERIMENTS.items():
        cfg = replace(pca_hp_cfg, channel_weight=exp_cfg["channel_weight"])
        raw = run_pca_complex_fusion(
            multichannel_by_var,
            amp_var=exp_cfg["amp_var"],
            channel_weight=exp_cfg["channel_weight"],
            top_k_channels=exp_cfg.get("top_k_channels"),
            metric_params=metric_params,
            pca_svd_config=cfg,
            verbose=verbose,
        )
        top_suffix = (
            f"_top{exp_cfg['top_k_channels']}" if exp_cfg.get("top_k_channels") else ""
        )
        ckey = (
            f"pca_complex_{exp_cfg['amp_var']}_ch_{exp_cfg['channel_weight']}{top_suffix}"
        )
        pca_v2[exp_name] = modal_to_per_seg(raw, ckey)
    for exp_name, exp_cfg in PCA_COMPLEX_INTEGRATION_EXPERIMENTS.items():
        cfg = replace(pca_hp_cfg, channel_weight=exp_cfg.get("channel_weight", "uniform"))
        runner = exp_cfg["runner"]
        if verbose:
            print(f"\n--- PCA integration: {exp_name} ---")
        if runner == "dual_amp":
            raw = run_pca_complex_dual_amp(
                multichannel_by_var,
                channel_weight=exp_cfg["channel_weight"],
                metric_params=metric_params,
                pca_svd_config=cfg,
                verbose=verbose,
            )
            ikey = f"pca_complex_dual_amp_ch_{exp_cfg['channel_weight']}"
        elif runner == "eta_blend":
            raw = run_pca_complex_eta_blend(
                multichannel_by_var,
                channel_weight=exp_cfg["channel_weight"],
                metric_params=metric_params,
                pca_svd_config=cfg,
                verbose=verbose,
            )
            ikey = f"pca_complex_eta_blend_ch_{exp_cfg['channel_weight']}"
        else:
            raw = run_pca_complex_modal_fusion(
                multichannel_by_var,
                amp_variables=exp_cfg["amp_variables"],
                channel_weight=exp_cfg["channel_weight"],
                modal_weight=exp_cfg["modal_weight"],
                metric_params=metric_params,
                pca_svd_config=cfg,
                verbose=verbose,
            )
            ikey = (
                f"pca_complex_modal_{exp_cfg['modal_weight']}_ch_{exp_cfg['channel_weight']}"
            )
        pca_v2[exp_name] = modal_to_per_seg(raw, ikey)
    for exp_name, exp_cfg in PCA_TOPK_EXPERIMENTS.items():
        cfg = replace(pca_hp_cfg, channel_weight=exp_cfg.get("channel_weight", "energy_ratio"))
        runner = exp_cfg["runner"]
        if verbose:
            print(f"\n--- PCA top-K: {exp_name} ---")
        if runner == "variable":
            raw = run_pca_topk_bpm(
                multichannel_by_var,
                variable=exp_cfg["variable"],
                top_k=exp_cfg["top_k"],
                channel_weight=exp_cfg["channel_weight"],
                metric_params=metric_params,
                pca_svd_config=cfg,
                verbose=verbose,
            )
            tkey = (
                f"pca_topk_{exp_cfg['variable']}_k{exp_cfg['top_k']}"
                f"_ch_{exp_cfg['channel_weight']}"
            )
        elif runner == "modal":
            raw = run_pca_modal_fusion(
                multichannel_by_var,
                modal_variables=exp_cfg["modal_variables"],
                channel_weight=exp_cfg["channel_weight"],
                modal_weight=exp_cfg["modal_weight"],
                top_k_channels=exp_cfg["top_k_channels"],
                metric_params=metric_params,
                pca_svd_config=cfg,
                verbose=verbose,
            )
            tkey = (
                f"pca_modal_{exp_cfg['modal_weight']}_ch_{exp_cfg['channel_weight']}"
                f"_top{exp_cfg['top_k_channels']}"
            )
        else:
            raw = run_pca_complex_fusion(
                multichannel_by_var,
                amp_var=exp_cfg["amp_var"],
                channel_weight=exp_cfg["channel_weight"],
                top_k_channels=exp_cfg["top_k_channels"],
                metric_params=metric_params,
                pca_svd_config=cfg,
                verbose=verbose,
            )
            tkey = (
                f"pca_complex_{exp_cfg['amp_var']}_ch_{exp_cfg['channel_weight']}"
                f"_top{exp_cfg['top_k_channels']}"
            )
        pca_v2[exp_name] = modal_to_per_seg(raw, tkey)
    return pca_v2


def build_leaderboard(
    pca_svd_results: dict,
    baseline_results: dict,
    plan2_rows: Optional[List[dict]] = None,
) -> List[dict]:
    rows: List[dict] = []
    baseline_names_map = {
        "fft_single_max_energy": ("Single (remote amp)", "Single"),
        "fft_uniform_fusion": ("Uniform (remote amp)", "Uniform"),
        "fft_q_energy_peak_fusion": ("q_energy_peak (remote amp)", "Baseline"),
    }
    for key, (label, cat) in baseline_names_map.items():
        stats = _overall_rel_error(baseline_results, key)
        if not np.isfinite(stats["mean_rel_err_pct"]):
            continue
        rows.append({
            "label": label,
            "mean_rel_err_pct": stats["mean_rel_err_pct"],
            "std_rel_err_pct": stats["std_rel_err_pct"],
            "n_valid": stats["n_segments"],
            "category": cat,
            "color": category_color(label, cat),
            "source": "baseline",
        })
    for exp_name, per_seg in pca_svd_results.items():
        errs = []
        for _seg_name, seg_stats in per_seg.items():
            if seg_stats is None:
                continue
            err = seg_stats.get("bpm_rel_err", np.nan)
            if np.isfinite(err):
                errs.append(float(err))
        mean_err, std_err, n_valid = segment_rel_err_pct(errs)
        if not np.isfinite(mean_err):
            continue
        cat = pca_svd_category(exp_name)
        rows.append({
            "label": exp_name,
            "mean_rel_err_pct": mean_err,
            "std_rel_err_pct": std_err,
            "n_valid": n_valid,
            "category": cat,
            "color": category_color(exp_name, cat),
            "source": "pca_svd",
        })
    for prow in plan2_rows or []:
        rows.append({
            "label": prow["label"],
            "mean_rel_err_pct": prow["mean_rel_err_pct"],
            "std_rel_err_pct": prow["std_rel_err_pct"],
            "n_valid": prow.get("n_segments", 0),
            "category": prow.get("category", "Plan2"),
            "color": prow.get("color", category_color(prow["label"], "Plan2")),
            "source": "plan2",
        })
    rows.sort(key=lambda r: r["mean_rel_err_pct"] if np.isfinite(r["mean_rel_err_pct"]) else 999)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def run_scenario_pipeline(
    scenario_id: str,
    *,
    project_root: Path,
    pipe_cfg: PcaSvdPipelineConfig,
    verbose: bool = True,
) -> dict:
    """单场景：滤波 → PCA/SVD v1+v2 → Plan2 → 排行榜。"""
    sc = load_scenario(scenario_id, project_root=project_root)
    _data, run_frames = load_ble_frames(sc.resolve_data_path(project_root), verbose=False)
    seg_cfg = sc.segment_config
    vars_list = [v[0] for v in CS_SIGNAL_VARIABLES]

    mc_by_var: Dict[str, dict] = {}
    run_fs = None
    for variable in vars_list:
        mc, run_fs = run_multichannel_segment_filtering(
            run_frames,
            seg_cfg,
            variable=variable,
            filter_params=pipe_cfg.filter_params,
            verbose=verbose,
        )
        mc_by_var[variable] = mc

    baseline = estimate_segment_bpm_methods(
        mc_by_var["remote_amplitudes"],
        variable="remote_amplitudes",
        config=pipe_cfg.chfusion_config,
        metric_params=pipe_cfg.metric_params,
        methods=("single", "uniform", "q_energy_peak"),
        single_channel_metric="energy_ratio",
        verbose=verbose,
    )

    pca_results: Dict[str, dict] = {}
    for exp_name, exp_cfg in PCA_SVD_EXPERIMENTS.items():
        if verbose:
            print(f"\n--- [{sc.tag}] {exp_name} ---")
        pca_results[exp_name] = run_pca_svd_bpm(
            mc_by_var,
            seg_cfg,
            method=exp_cfg["method"],
            variable_or_vars=exp_cfg["variable"],
            complex_amp_var=exp_cfg.get("complex_amp_var"),
            fs=run_fs,
            metric_params=pipe_cfg.metric_params,
            pca_svd_config=pipe_cfg.pca_svd_config,
            verbose=verbose,
        )
    pca_results.update(
        run_pca_v2_suite(
            mc_by_var,
            seg_cfg,
            run_fs,
            pipe_cfg.metric_params,
            pipe_cfg.pca_hp_config,
            verbose=verbose,
        )
    )

    plan2_out = run_plan2_validation(
        run_frames,
        seg_cfg,
        filter_params=pipe_cfg.filter_params,
        metric_params=pipe_cfg.metric_params,
        config=pipe_cfg.chfusion_config,
        plan2_config=pipe_cfg.plan2_config,
        reference_variable="phases",
        verbose=verbose,
    )
    p2_lb = build_plan2_leaderboard_rows(plan2_out)
    lb = build_leaderboard(pca_results, baseline, p2_lb)

    return {
        "scenario_id": scenario_id,
        "scenario_tag": sc.tag,
        "segment_config": seg_cfg,
        "fs": run_fs,
        "multichannel_by_var": mc_by_var,
        "baseline_results": baseline,
        "pca_svd_results": pca_results,
        "plan2_results": plan2_out,
        "plan2_leaderboard": p2_lb,
        "leaderboard": lb,
    }


def ensure_scenario_report(
    scenario_id: str,
    *,
    project_root: Path,
    reports_dir: Path,
    pipe_cfg: PcaSvdPipelineConfig,
    current_report: Optional[dict] = None,
    verbose: bool = False,
    force: bool = False,
) -> dict:
    """加载 ``chfusion_pca_svd_{tag}.npy``；缺失或 stale 则重跑 pipeline。"""
    sc = load_scenario(scenario_id, project_root=project_root)
    path = reports_dir / f"chfusion_pca_svd_{sc.tag}.npy"
    if current_report is not None:
        return current_report
    if not force and path.is_file():
        cached = np.load(path, allow_pickle=True).item()
        pca_res = cached.get("pca_svd_results", {})
        if all(k in pca_res for k in REQUIRED_PCA_V2_CACHE_KEYS):
            if verbose:
                print(f"Loaded cached report: {path.name}")
            return cached
        if verbose:
            print(f"Stale cache: {path.name}")
    if verbose:
        print(f"Running PCA/SVD pipeline for {scenario_id} …")
    result = run_scenario_pipeline(
        scenario_id, project_root=project_root, pipe_cfg=pipe_cfg, verbose=verbose
    )
    np.save(path, result, allow_pickle=True)
    if verbose:
        print(f"Saved: {path.name}")
    return result


def aggregate_cross_domain_rows(
    results_by_tag: Dict[str, dict],
    compare_tags: Sequence[str],
    compare_labels: Sequence[str] = CROSS_DOMAIN_COMPARE_LABELS,
) -> List[dict]:
    cross_rows: List[dict] = []
    for lbl in compare_labels:
        domain_errs = []
        for tag in compare_tags:
            row = leaderboard_lookup(results_by_tag[tag]["leaderboard"]).get(lbl)
            val = row["mean_rel_err_pct"] if row else np.nan
            domain_errs.append(float(val) if np.isfinite(val) else np.nan)
        finite = [e for e in domain_errs if np.isfinite(e)]
        if not finite:
            continue
        mean_across = float(np.mean(finite))
        std_across = float(np.std(finite, ddof=1)) if len(finite) > 1 else 0.0
        cross_rows.append({
            "label": lbl,
            "domain_errs": domain_errs,
            "mean_across_domains": mean_across,
            "std_across_domains": std_across,
        })
    cross_rows.sort(key=lambda r: r["mean_across_domains"])
    return cross_rows


def print_cross_domain_table(
    cross_rows: List[dict],
    compare_tags: Sequence[str],
) -> None:
    print(f"\n{'=' * 72}")
    print("  Cross-scenario leaderboard (mean err% per domain)")
    print(f"  Scenarios: {' / '.join(compare_tags)}")
    print("=" * 72)
    col_w = 10
    header = (
        f"{'方法':<32}"
        + "".join(f"{t:>{col_w}}" for t in compare_tags)
        + f"{'mean':>8}{'±std':>8}"
    )
    print(header)
    print("-" * (32 + col_w * len(compare_tags) + 16))
    for row in cross_rows:
        line = f"{row['label']:<32}"
        for e in row["domain_errs"]:
            line += f"{e:>{col_w}.2f}" if np.isfinite(e) else f"{'—':>{col_w}}"
        line += (
            f"{row['mean_across_domains']:>{col_w}.2f}"
            f"{row['std_across_domains']:>8.2f}"
        )
        print(line)
    if cross_rows:
        best = cross_rows[0]
        print(
            f"\n  ★ 跨场景综合最优: {best['label']}  →  "
            f"{best['mean_across_domains']:.2f}% ± {best['std_across_domains']:.2f}%"
        )


def save_cross_domain_aggregate(
    cross_rows: List[dict],
    results_by_tag: Dict[str, dict],
    *,
    reports_dir: Path,
    figures_dir: Path,
    scenario_ids: Sequence[str] = COMPARE_SCENARIO_IDS,
    compare_tags: Optional[Sequence[str]] = None,
    compare_labels: Sequence[str] = CROSS_DOMAIN_COMPARE_LABELS,
) -> Tuple[Path, Path]:
    """保存跨域 ``.npy`` 与柱状图 PDF。"""
    import matplotlib.pyplot as plt

    tags = list(compare_tags or [results_by_tag[k]["scenario_tag"] for k in results_by_tag])
    report_path = reports_dir / "chfusion_pca_svd_cross_domain.npy"
    np.save(
        report_path,
        {
            "scenario_ids": list(scenario_ids),
            "scenario_tags": tags,
            "compare_labels": list(compare_labels),
            "cross_rows": cross_rows,
            "results_by_tag": {k: v["leaderboard"] for k, v in results_by_tag.items()},
        },
        allow_pickle=True,
    )
    fig_path = figures_dir / "pca_svd_cross_domain_aggregate_bars.pdf"
    if cross_rows:
        fig, ax = plt.subplots(figsize=(10, max(5.0, 0.38 * len(cross_rows) + 1.5)))
        y = np.arange(len(cross_rows))
        means = [r["mean_across_domains"] for r in cross_rows]
        stds = [r["std_across_domains"] for r in cross_rows]
        ax.barh(
            y, means, xerr=stds, color="#7B9FD4", edgecolor="black",
            alpha=0.85, height=0.72, capsize=3,
        )
        ax.set_yticks(y)
        ax.set_yticklabels([r["label"] for r in cross_rows], fontsize=9)
        ax.invert_yaxis()
        ax.set_xlabel("Mean relative BPM error (%) across scenarios")
        ax.set_title("PCA/SVD + Plan2 — cross-domain aggregate (lower = better)")
        ax.grid(True, axis="x", alpha=0.25)
        for i, (m, s) in enumerate(zip(means, stds)):
            ax.text(m + s + 0.3, i, f"{m:.1f}±{s:.1f}%", va="center", fontsize=8)
        plt.tight_layout()
        fig.savefig(fig_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    return report_path, fig_path


def run_harmonic_diagnosis(
    multichannel_by_var: dict,
    *,
    pipe_cfg: PcaSvdPipelineConfig,
    integrations: Sequence[Tuple[str, str]] = (
        ("η-blend ch-η", "eta_blend"),
        ("Dual-Amp ch-η", "dual_amp"),
    ),
    verbose: bool = True,
) -> List[dict]:
    """091339 等：复 PCA 整合路线的窗级倍频/半频统计。"""
    summary: List[dict] = []
    if verbose:
        print(f"\n{'=' * 72}\n  PC1 harmonic diagnosis\n{'=' * 72}")
        print(
            f"  {'方法':<28} {'段':<12} {'GT':>5} {'err%':>7}  "
            f"{'基频':>5} {'倍频':>5} {'半频':>5} {'其它':>5}"
        )
        print("  " + "-" * 72)
    for method_label, integration in integrations:
        harm = diagnose_complex_integration_harmonics(
            multichannel_by_var,
            integration=integration,
            channel_weight="energy_ratio",
            metric_params=pipe_cfg.metric_params,
            pca_svd_config=pipe_cfg.pca_hp_config,
        )
        for seg_name, row in sorted(harm.items()):
            if row is None:
                continue
            fr = row["harmonic_fracs"]
            if verbose:
                print(
                    f"  {method_label:<28} {seg_name:<12} {row['bpm_gt']:>5.0f} "
                    f"{row['mean_rel_err_pct']:>7.1f}  "
                    f"{fr['fundamental']:>5.0%} {fr['double']:>5.0%} "
                    f"{fr['half']:>5.0%} {fr['other']:>5.0%}"
                )
            summary.append({
                "method": method_label,
                "segment": seg_name,
                "bpm_gt": row["bpm_gt"],
                "mean_rel_err_pct": row["mean_rel_err_pct"],
                **{f"frac_{k}": v for k, v in fr.items()},
            })
    return summary


def save_worst_seg_spectrum_figure(
    multichannel_by_var: dict,
    *,
    scenario_tag: str,
    figures_dir: Path,
    pipe_cfg: PcaSvdPipelineConfig,
    integrations: Sequence[Tuple[str, str]] = (
        ("η-blend ch-η", "eta_blend"),
        ("Dual-Amp ch-η", "dual_amp"),
        ("Total ch-η", "total_complex"),
    ),
    reference_integration: str = "eta_blend",
) -> Optional[Path]:
    """最差段 PC1 呼吸带谱 vs GT（P1 波形对照）。"""
    import matplotlib.pyplot as plt

    harm = diagnose_complex_integration_harmonics(
        multichannel_by_var,
        integration=reference_integration,
        channel_weight="energy_ratio",
        metric_params=pipe_cfg.metric_params,
        pca_svd_config=pipe_cfg.pca_hp_config,
    )
    worst_seg, worst_err = None, -1.0
    for seg_name, row in harm.items():
        if row is None:
            continue
        err = row.get("mean_rel_err_pct", np.nan)
        if np.isfinite(err) and err > worst_err:
            worst_err, worst_seg = float(err), seg_name
    if not worst_seg:
        return None

    fig, axes = plt.subplots(1, len(integrations), figsize=(4.2 * len(integrations), 3.8))
    if len(integrations) == 1:
        axes = [axes]
    for ax, (label, integration) in zip(axes, integrations):
        snap = extract_integration_pc1_spectrum(
            multichannel_by_var,
            worst_seg,
            integration=integration,
            window_index=0,
            channel_weight="energy_ratio",
            metric_params=pipe_cfg.metric_params,
            pca_svd_config=pipe_cfg.pca_hp_config,
        )
        if snap is None:
            ax.set_title(f"{label}\n(no data)")
            continue
        ax.plot(snap["band_freqs"] * 60.0, snap["spectrum"], color="#2E6F9E", lw=1.5, label="PC1")
        if np.isfinite(snap["gt_hz"]):
            ax.axvline(snap["gt_hz"] * 60.0, color="#C44E52", ls="--", lw=1.2, label="GT")
        if np.isfinite(snap["peak_hz"]):
            ax.axvline(snap["peak_hz"] * 60.0, color="#55A868", ls=":", lw=1.2, label="peak")
        ax.set_xlabel("BPM")
        ax.set_ylabel("Norm. power")
        ax.set_title(label)
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.25)
    fig.suptitle(
        f"{scenario_tag} worst seg {worst_seg} (err≈{worst_err:.1f}%)",
        fontsize=10,
    )
    plt.tight_layout()
    out = figures_dir / f"pca_svd_{scenario_tag}_worst_seg_pc1_spectrum.pdf"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def run_p1_diagnostics(
    scenario_id: str,
    *,
    project_root: Path,
    reports_dir: Path,
    figures_dir: Path,
    pipe_cfg: PcaSvdPipelineConfig,
    scenario_report: Optional[dict] = None,
    verbose: bool = True,
) -> dict:
    """加载场景报告 → 倍频诊断 + 最差段谱图。"""
    sc = load_scenario(scenario_id, project_root=project_root)
    if scenario_report is None:
        path = reports_dir / f"chfusion_pca_svd_{sc.tag}.npy"
        scenario_report = np.load(path, allow_pickle=True).item()
    mc = scenario_report["multichannel_by_var"]
    summary = run_harmonic_diagnosis(mc, pipe_cfg=pipe_cfg, verbose=verbose)
    diag_path = reports_dir / f"chfusion_pca_svd_{sc.tag}_harmonic_diag.npy"
    np.save(
        diag_path,
        {"scenario_id": scenario_id, "summary": summary},
        allow_pickle=True,
    )
    fig_path = save_worst_seg_spectrum_figure(
        mc, scenario_tag=sc.tag, figures_dir=figures_dir, pipe_cfg=pipe_cfg
    )
    if verbose and fig_path:
        print(f"  Saved spectrum fig -> {fig_path.name}")
    return {"harmonic_summary": summary, "harmonic_diag_path": diag_path, "spectrum_fig": fig_path}
