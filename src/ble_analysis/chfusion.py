"""Multi-channel FFT + quality-weighted fusion (FFT+q).

Pipeline (see ``docs/chfusion_fft-q.md``):

1. Reuse segment filter chain from ``segments.process_segments``:
   median → highpass → bandpass (per channel, per script segment).
2. Sliding-window FFT on bandpass signals → normalized spectra ``P̄_c(f)``.
3. Compute per-channel quality sub-scores and fuse spectra with weights ``w_c``.

Comparison methods (benchmark — see ``docs/chfusion_q_energy_peak.md``)
---------------------------------------------------------------------
- **fft_q_energy_fusion**: ``q_energy`` only (log-mapped η = E_breath/E_total).
- **fft_q_peak_fusion**: ``q_peak`` only (log-mapped spectral peak SNR).
- **fft_q_energy_peak_fusion**: ``(q_energy · q_peak)^(1/2)``, all channels, no Top-K.

Quality score (q_c)
-----------------
``q_energy``
    Breath-band energy ratio η on highpass signal; **log-linear** map to [0, 1]
    (same formula as ``q_peak``; thresholds ``energy_ratio_min/good``).

``q_peak``
    Peak prominence ρ = max(P)/median(P) in breath band; log-linear map to [0, 1].

Fusion weights::

    q_energy only:  w_c ∝ q_energy
    q_peak only:    w_c ∝ q_peak
    energy+peak:    w_c ∝ (q_energy · q_peak)^(1/2)

Fusion (doc §1.4 / chfusion_q_energy_peak.md)::

    S(f) = Σ_c w_c · P̄_c(f),   w_c = q_c / Σ_j q_j
    BPM  = 60 · argmax_{f∈B} S(f)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

import numpy as np

from ble_analysis.channels import get_available_channels
from ble_analysis.segments import (
    BreathMetricParams,
    FilterParams,
    _estimate_breathing_freq_hz,
    _sliding_window_indices,
    estimate_sampling_rate_from_frames,
    extract_segment_data,
    process_segments,
)

# CS 可融合的四种有效观测量（本地/远程单端相位无独立物理意义，不纳入）
CS_SIGNAL_VARIABLES: Tuple[Tuple[str, str], ...] = (
    ("amplitudes", "总幅值 amp"),
    ("remote_amplitudes", "远程幅值 remote"),
    ("local_amplitudes", "本地幅值 local"),
    ("phases", "总相位 phase"),
)

# English labels for matplotlib titles/legends (avoid CJK font issues)
VARIABLE_PLOT_LABELS: Dict[str, str] = {
    "amplitudes": "Total amplitude",
    "remote_amplitudes": "Remote amplitude",
    "local_amplitudes": "Local amplitude",
    "phases": "Total phase (unwrapped)",
}

# Benchmark methods (baselines first, then q-weighted fusion; docs/chfusion_q_energy_peak.md)
FUSION_METHOD_KEYS: Tuple[str, ...] = (
    "fft_single_max_energy",
    "fft_uniform_fusion",
    "fft_q_energy_fusion",
    "fft_q_peak_fusion",
    "fft_q_energy_peak_fusion",
)

FUSION_METHOD_LABELS: Tuple[Tuple[str, str, str], ...] = (
    ("Single", "fft_single_max_energy", "steelblue"),
    ("Uniform", "fft_uniform_fusion", "seagreen"),
    ("FFT+q_energy", "fft_q_energy_fusion", "darkorange"),
    ("FFT+q_peak", "fft_q_peak_fusion", "mediumpurple"),
    ("FFT+q_energy_peak", "fft_q_energy_peak_fusion", "coral"),
)

# q_c composition modes (compact/peak used internally; benchmark uses energy / peak / energy_peak)
QWeightMode = Literal["compact", "peak_only", "energy_only", "energy_peak"]

Q_WEIGHT_MODE_LABELS: Dict[str, str] = {
    "compact": "q_c = (q_valid × q_peak × q_phi)^(1/3)",
    "peak_only": "q_c = q_peak",
    "energy_only": "q_c = q_energy",
    "energy_peak": "q_c = (q_energy × q_peak)^(1/2)",
}


@dataclass
class ChFusionConfig:
    """FFT+q sliding-window parameters (aligned with ``BreathMetricParams``)."""

    # Breath band for FFT peak search [Hz]
    breath_freq_low: float = 0.1
    breath_freq_high: float = 0.35
    # Denominator band for single-channel energy-ratio baseline [Hz]
    total_freq_low: float = 0.05
    total_freq_high: float = 0.8
    # Sliding window
    window_length_sec: float = 20.0
    step_length_sec: float = 1.0
    nfft: Optional[int] = None

    # --- q_valid: valid sample fraction threshold ---
    min_valid_frac: float = 0.70

    # --- q_peak: ρ = peak/median mapped in log domain ---
    peak_snr_min: float = 1.5
    peak_snr_good: float = 6.0

    # --- q_energy: breath/total band energy ratio (Single selector metric) ---
    energy_ratio_min: float = 0.02
    energy_ratio_good: float = 0.20

    # --- q_phi: unwrap phase jump penalty ---
    phase_jump_rad: float = 1.2
    jump_rate_good: float = 0.05

    # How to combine sub-scores into fusion weight q_c
    q_weight_mode: QWeightMode = "compact"

    # Optional consensus gate (doc §1.5); off by default
    enable_consensus: bool = False
    consensus_sigma_bpm: float = 2.0
    eps: float = 1e-12


def print_q_score_documentation(cfg: Optional[ChFusionConfig] = None) -> None:
    """Print q sub-score definitions and the active q_c formula to stdout."""
    cfg = cfg or ChFusionConfig()
    print("\n=== q 分数组成（docs/chfusion_fft-q.md §1.3）===")
    print("子项          | 含义                         | 计算方式")
    print("-" * 72)
    print(
        f"q_valid       | 窗内有效采样比例             | "
        f"linear map, min_valid_frac={cfg.min_valid_frac}"
    )
    print(
        f"q_peak        | 呼吸频带谱峰突出程度         | "
        f"ρ=max(P)/median(P), log map [{cfg.peak_snr_min}, {cfg.peak_snr_good}]"
    )
    print(
        f"q_energy      | 呼吸/全频段能量比 η           | "
        f"log map [{cfg.energy_ratio_min}, {cfg.energy_ratio_good}]"
    )
    print(
        f"q_phi         | 相位 unwrap 后平滑度         | "
        f"exp(-jump_rate/{cfg.jump_rate_good}), jump>{cfg.phase_jump_rad} rad"
    )
    print("-" * 72)
    print(f"energy_only   | 仅 q_energy 加权               | {Q_WEIGHT_MODE_LABELS['energy_only']}")
    print(f"peak-only     | 仅 q_peak 加权                 | {Q_WEIGHT_MODE_LABELS['peak_only']}")
    print(f"energy_peak   | q_energy + q_peak 几何平均     | {Q_WEIGHT_MODE_LABELS['energy_peak']}")
    print(f"详细说明见 docs/chfusion_q_energy_peak.md")
    print(f"当前配置 q_weight_mode = '{cfg.q_weight_mode}'\n")


def _is_phase_variable(variable: str) -> bool:
    """True for composite or per-end phase series that require unwrap before filtering."""
    return variable == "phases" or variable.endswith("_phases")


def _preprocess_raw_series(raw: np.ndarray, variable: str) -> np.ndarray:
    """Apply variable-specific preprocessing before the filter chain.

    Phase (total ``phases`` from local⊗remote product) must be unwrapped so that
    highpass/bandpass see continuous incremental change, not 2π wraps.
    Amplitude variables are passed through unchanged.
    """
    x = np.asarray(raw, dtype=float)
    if not _is_phase_variable(variable):
        return x
    mask = np.isfinite(x)
    if np.sum(mask) < 2:
        return x
    out = x.copy()
    out[mask] = np.unwrap(x[mask])
    return out


def _variable_display_name(variable: str) -> str:
    for key, label in CS_SIGNAL_VARIABLES:
        if key == variable:
            return label
    return variable


def _variable_plot_label(variable: str) -> str:
    """English-only label for figure titles and legends."""
    return VARIABLE_PLOT_LABELS.get(variable, variable.replace("_", " "))


def _next_pow2(n: int) -> int:
    return 1 << int(np.ceil(np.log2(max(1, n))))


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    mask = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if np.sum(mask) == 0:
        return float(np.nanmedian(values))
    values = values[mask]
    weights = weights[mask]
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cdf = np.cumsum(weights) / np.sum(weights)
    return float(values[np.searchsorted(cdf, 0.5)])


def _quality_from_snr(snr: float, snr_min: float, snr_good: float, eps: float) -> float:
    """Map peak/median ratio ρ to q_peak ∈ [0, 1] via log-linear clipping."""
    snr = max(float(snr), eps)
    numerator = np.log(snr) - np.log(snr_min)
    denominator = np.log(snr_good) - np.log(snr_min) + eps
    return float(np.clip(numerator / denominator, 0.0, 1.0))


def _quality_from_energy_ratio(
    energy_ratio: float, er_min: float, er_good: float, eps: float
) -> float:
    """Map breath/total band energy ratio η to q_energy ∈ [0, 1] (log-linear, same as q_peak)."""
    er = max(float(np.clip(energy_ratio, 0.0, 1.0)), eps)
    return _quality_from_snr(er, er_min, er_good, eps)


def _compose_q_weight(
    q_valid: float,
    q_peak: float,
    q_phi: float,
    mode: QWeightMode,
    eps: float,
    *,
    q_energy: float = 0.0,
) -> float:
    """Combine sub-scores into scalar fusion weight q_c."""
    if mode == "peak_only":
        return float(q_peak)
    if mode == "energy_only":
        return float(q_energy)
    if mode == "energy_peak":
        return float((q_energy * q_peak + eps) ** 0.5)
    # compact: geometric mean of three sub-scores (doc §1.3)
    return float((q_valid * q_peak * q_phi + eps) ** (1.0 / 3.0))


def _parabolic_peak_freq(f_band: np.ndarray, power_band: np.ndarray, k: int, eps: float) -> float:
    f_hat = float(f_band[k])
    if 0 < k < len(power_band) - 1:
        y0, y1, y2 = power_band[k - 1], power_band[k], power_band[k + 1]
        denom = y0 - 2.0 * y1 + y2
        if abs(denom) > eps:
            delta = 0.5 * (y0 - y2) / denom
            df = f_band[1] - f_band[0]
            f_hat = float(f_band[k] + delta * df)
    return f_hat


def _bpm_from_fused_spectrum(
    fused: np.ndarray, band_freqs: np.ndarray, cfg: ChFusionConfig
) -> float:
    k = int(np.argmax(fused))
    f_hat = _parabolic_peak_freq(band_freqs, fused, k, cfg.eps)
    return 60.0 * f_hat


def _channel_spectrum_and_q(
    bandpass_seg: np.ndarray,
    raw_phase_seg: np.ndarray,
    fs: float,
    cfg: ChFusionConfig,
    nfft: int,
    band_mask: np.ndarray,
    band_freqs: np.ndarray,
    hann: np.ndarray,
    *,
    q_weight_mode: QWeightMode = "compact",
    compute_q_phi: bool = True,
) -> Tuple[np.ndarray, float, float, Dict[str, float]]:
    """FFT spectrum + q sub-scores for one channel/window.

    For **amplitude** variables set ``compute_q_phi=False`` (q_phi=1).
    For **phase** variables pass unwrapped phase as ``raw_phase_seg`` and
    ``compute_q_phi=True``.

    Returns
    -------
    p_norm, q_c, f_peak, detail
        ``detail`` includes ``q_valid``, ``q_peak``, ``q_phi``, ``q_c``, ``peak_snr``.
    """
    zero_spec = np.zeros_like(band_freqs)
    bad_detail: Dict[str, float] = {
        "q_valid": 0.0,
        "q_peak": 0.0,
        "q_phi": 0.0,
        "q_c": 0.0,
        "peak_snr": 0.0,
    }

    if len(bandpass_seg) != len(hann) or not np.all(np.isfinite(bandpass_seg)):
        return zero_spec, 0.0, np.nan, bad_detail

    # q_valid: linear ramp above min_valid_frac
    valid_frac = float(np.mean(np.isfinite(raw_phase_seg)))
    q_valid = float(
        np.clip(
            (valid_frac - cfg.min_valid_frac) / (1.0 - cfg.min_valid_frac + cfg.eps),
            0.0,
            1.0,
        )
    )

    seg = bandpass_seg - np.mean(bandpass_seg)
    if np.std(seg) < cfg.eps:
        d = {**bad_detail, "q_valid": q_valid, "valid_frac": valid_frac, "q_weight_mode": q_weight_mode}
        return zero_spec, 0.0, np.nan, d

    # FFT power in breath band → q_peak
    x = np.fft.rfft(seg * hann, n=nfft)
    p_band = (np.abs(x) ** 2)[band_mask]
    peak_power = float(np.max(p_band))
    noise_floor = float(np.median(p_band) + cfg.eps)
    peak_snr = peak_power / noise_floor  # ρ in doc
    q_peak = _quality_from_snr(peak_snr, cfg.peak_snr_min, cfg.peak_snr_good, cfg.eps)
    k = int(np.argmax(p_band))
    f_peak = _parabolic_peak_freq(band_freqs, p_band, k, cfg.eps)

    # q_phi: phase smoothness (only meaningful for phase signals)
    if compute_q_phi:
        dphi = np.diff(np.unwrap(raw_phase_seg[np.isfinite(raw_phase_seg)]))
        if len(dphi) == 0:
            q_phi, jump_rate = 0.0, 1.0
        else:
            jump_rate = float(np.mean(np.abs(dphi) > cfg.phase_jump_rad))
            q_phi = float(np.exp(-jump_rate / (cfg.jump_rate_good + cfg.eps)))
    else:
        q_phi, jump_rate = 1.0, 0.0

    q_c = _compose_q_weight(q_valid, q_peak, q_phi, q_weight_mode, cfg.eps)
    p_norm = p_band / (np.sum(p_band) + cfg.eps)
    detail = {
        "q_valid": q_valid,
        "q_peak": q_peak,
        "q_phi": q_phi,
        "q_c": q_c,
        "q_weight_mode": q_weight_mode,
        "peak_snr": peak_snr,
        "jump_rate": jump_rate,
        "valid_frac": valid_frac,
    }
    return p_norm, q_c, f_peak, detail


def _energy_ratio(signal_seg: np.ndarray, fs: float, cfg: ChFusionConfig) -> float:
    """Breath-band energy / total-band energy (single-channel baseline selector)."""
    if len(signal_seg) < 4 or not np.all(np.isfinite(signal_seg)):
        return 0.0
    windowed = (signal_seg - np.mean(signal_seg)) * np.hanning(len(signal_seg))
    fft_power = np.abs(np.fft.rfft(windowed)) ** 2
    fft_freq = np.fft.rfftfreq(len(windowed), 1.0 / fs)
    breath_mask = (fft_freq >= cfg.breath_freq_low) & (fft_freq <= cfg.breath_freq_high)
    total_mask = (fft_freq >= cfg.total_freq_low) & (fft_freq <= cfg.total_freq_high)
    breath_energy = float(np.sum(fft_power[breath_mask]))
    total_energy = float(np.sum(fft_power[total_mask]))
    if total_energy <= cfg.eps:
        return 0.0
    return breath_energy / total_energy


def _fuse_weighted_spectrum(
    spectra_arr: np.ndarray,
    q_weights: np.ndarray,
    band_freqs: np.ndarray,
    cfg: ChFusionConfig,
    peak_freqs: Optional[np.ndarray] = None,
) -> float:
    """Fuse normalized spectra with q_c weights; optional consensus gate."""
    q_arr = np.asarray(q_weights, dtype=float)
    n_ch = spectra_arr.shape[0]

    if np.sum(q_arr) <= cfg.eps:
        weights = np.ones(n_ch) / n_ch
    else:
        q_eff = q_arr.copy()
        if cfg.enable_consensus and peak_freqs is not None:
            peak_freqs_arr = np.asarray(peak_freqs, dtype=float)
            consensus_hz = _weighted_median(peak_freqs_arr, q_arr)
            sigma_hz = cfg.consensus_sigma_bpm / 60.0
            gate = np.exp(-0.5 * ((peak_freqs_arr - consensus_hz) / (sigma_hz + cfg.eps)) ** 2)
            gate[~np.isfinite(gate)] = 0.0
            q_eff = q_arr * gate
            if np.sum(q_eff) <= cfg.eps:
                q_eff = q_arr.copy()
        weights = q_eff / (np.sum(q_eff) + cfg.eps)

    fused = np.sum(weights[:, None] * spectra_arr, axis=0)
    return _bpm_from_fused_spectrum(fused, band_freqs, cfg)


MODAL_FILTER_VARIABLES: Tuple[str, ...] = (
    "remote_amplitudes",
    "local_amplitudes",
    "phases",
)


def _data_fingerprint_from_frames(frames) -> str:
    """Fingerprint loaded frames (legacy; used when no scenario path is available)."""
    ts_sample = []
    for i, f in enumerate(frames):
        if i >= 5:
            break
        ts_sample.append(str(f.get("timestamp", "")))
    n_frames = len(frames)
    n_channels = len(get_available_channels(frames))
    return "|".join(ts_sample) + f"|n={n_frames}|ch={n_channels}"


def data_fingerprint_from_path(data_path: Path) -> str:
    """Fingerprint raw data file without loading frames (path + size + mtime)."""
    path = Path(data_path).resolve()
    stat = path.stat()
    return f"file={path}|size={stat.st_size}|mtime={stat.st_mtime_ns}"


def _filter_cache_key(
    data_fp: str,
    segment_config: Dict[str, dict],
    variable: str,
    filter_params: Optional[FilterParams],
) -> str:
    """Deterministic short hash for data fingerprint + config + variable + filter params."""
    fp = filter_params or FilterParams()
    cfg_str = json.dumps(segment_config, sort_keys=True, default=str)
    fp_str = repr(
        (
            fp.median_window,
            fp.highpass_cutoff,
            fp.highpass_order,
            fp.bandpass_lowcut,
            fp.bandpass_highcut,
            fp.bandpass_order,
        )
    )
    key_str = f"{data_fp}|{cfg_str}|{variable}|{fp_str}"
    return hashlib.md5(key_str.encode()).hexdigest()[:16]


def _filter_cache_file(
    cache_dir: str,
    data_fp: str,
    segment_config: Dict[str, dict],
    variable: str,
    filter_params: Optional[FilterParams],
) -> Path:
    cache_key = _filter_cache_key(data_fp, segment_config, variable, filter_params)
    return Path(cache_dir) / f"{cache_key}_{variable}_filtered.npy"


def _try_load_filter_cache(
    cache_dir: str,
    data_fp: str,
    segment_config: Dict[str, dict],
    variable: str,
    filter_params: Optional[FilterParams],
) -> Optional[Tuple[Dict[str, Optional[dict]], float]]:
    cache_file = _filter_cache_file(
        cache_dir, data_fp, segment_config, variable, filter_params
    )
    if not cache_file.is_file():
        return None
    try:
        cached = np.load(cache_file, allow_pickle=True).item()
        return cached["out"], cached["fs"]
    except (ValueError, KeyError, OSError):
        return None


def load_multichannel_filtered(
    segment_config: Dict[str, dict],
    variables: Sequence[str],
    *,
    frames=None,
    data_fingerprint: Optional[str] = None,
    filter_params: Optional[FilterParams] = None,
    cache_dir: Optional[str] = None,
    verbose: bool = True,
) -> Tuple[Dict[str, Dict[str, Optional[dict]]], float, bool]:
    """Load or compute multichannel filtered segments for ``variables``.

    When ``cache_dir`` and ``data_fingerprint`` are set, tries disk cache first
    without requiring ``frames``. On full cache hit, returns
    ``skipped_raw_load=True`` so callers can skip ``load_ble_frames``.

    On any cache miss, ``frames`` must be provided to compute missing variables.
    """
    fp = filter_params or FilterParams()
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]] = {}
    fs: Optional[float] = None
    missing: List[str] = []

    if cache_dir is not None and data_fingerprint is not None:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        for variable in variables:
            hit = _try_load_filter_cache(
                cache_dir, data_fingerprint, segment_config, variable, fp
            )
            if hit is not None:
                multichannel_by_var[variable], fs_hit = hit
                fs = fs if fs is not None else fs_hit
                if verbose:
                    tag = _variable_display_name(variable)
                    n_ok = sum(
                        1 for v in multichannel_by_var[variable].values() if v is not None
                    )
                    print(
                        f"✓ [{tag}] 缓存命中 {n_ok}/{len(segment_config)} 段 | "
                        f"(已缓存，无需原始数据)"
                    )
            else:
                missing.append(variable)
    else:
        missing = list(variables)

    if missing:
        if frames is None:
            raise ValueError(
                "Filter cache miss: provide ``frames`` or warm cache via "
                "``load_multichannel_for_scenario``."
            )
        if data_fingerprint is None:
            data_fingerprint = _data_fingerprint_from_frames(frames)
        for variable in missing:
            mc, fs_new = run_multichannel_segment_filtering(
                frames,
                segment_config,
                variable=variable,
                filter_params=fp,
                verbose=verbose,
                cache_dir=cache_dir,
                data_fingerprint=data_fingerprint,
            )
            multichannel_by_var[variable] = mc
            fs = fs_new

    skipped_raw_load = not missing
    if skipped_raw_load and verbose:
        print(
            f"✓ 全部 {len(variables)} 变量滤波缓存命中，跳过原始数据加载与分段"
        )
    if fs is None:
        raise RuntimeError("Failed to obtain sampling rate fs")
    return multichannel_by_var, fs, skipped_raw_load


def load_multichannel_for_scenario(
    scenario,
    *,
    project_root: Optional[PathLike] = None,
    variables: Sequence[str] = MODAL_FILTER_VARIABLES,
    filter_params: Optional[FilterParams] = None,
    cache_dir: Optional[str] = None,
    verbose: bool = True,
) -> Tuple[Dict[str, Dict[str, Optional[dict]]], float, bool]:
    """Load filtered multichannel data for a scenario, skipping raw JSON when cached."""
    from ble_analysis.data import load_ble_frames

    data_path = scenario.resolve_data_path(project_root)
    data_fp = data_fingerprint_from_path(data_path)
    segment_config = scenario.segment_config

    if cache_dir is not None:
        fp = filter_params or FilterParams()
        all_hit = all(
            _try_load_filter_cache(cache_dir, data_fp, segment_config, var, fp)
            is not None
            for var in variables
        )
        if all_hit:
            return load_multichannel_filtered(
                segment_config,
                variables,
                data_fingerprint=data_fp,
                filter_params=fp,
                cache_dir=cache_dir,
                verbose=verbose,
            )

    if verbose:
        print(f"缓存未完整命中，加载原始数据: {data_path.name}")
    _data, frames = load_ble_frames(data_path, verbose=verbose)
    if not frames:
        raise RuntimeError(f"No frames loaded from {data_path}")
    return load_multichannel_filtered(
        segment_config,
        variables,
        frames=frames,
        data_fingerprint=data_fp,
        filter_params=filter_params,
        cache_dir=cache_dir,
        verbose=verbose,
    )


def run_multichannel_segment_filtering(
    frames,
    segment_config: Dict[str, dict],
    variable: str = "amplitudes",
    *,
    filter_params: Optional[FilterParams] = None,
    verbose: bool = True,
    cache_dir: Optional[str] = None,
    data_fingerprint: Optional[str] = None,
) -> Tuple[Dict[str, Optional[dict]], float]:
    """Extract and filter **all channels** for one signal variable per segment.

    For ``phases``, raw series are **unwrapped** before median/highpass/bandpass.
    Only the requested ``variable`` is extracted (no separate remote/local phase).

    If ``cache_dir`` is provided, filtered results are cached to disk as
    ``{cache_dir}/{hash}_{variable}_filtered.npy`` and reused on subsequent
    calls with identical inputs. Pass ``data_fingerprint`` (from
    :func:`data_fingerprint_from_path`) to allow cache lookup without ``frames``.
    """
    fp = filter_params or FilterParams()
    cache_file: Optional[Path] = None

    # --- cache lookup ---
    if cache_dir is not None:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        fp_str = data_fingerprint
        if fp_str is None:
            if frames is None:
                raise ValueError(
                    "``frames`` or ``data_fingerprint`` required for cache lookup"
                )
            fp_str = _data_fingerprint_from_frames(frames)
        cache_file = _filter_cache_file(cache_dir, fp_str, segment_config, variable, fp)
        if cache_file.is_file():
            try:
                cached = np.load(cache_file, allow_pickle=True).item()
                if verbose:
                    tag = _variable_display_name(variable)
                    n_ok = sum(1 for v in cached["out"].values() if v is not None)
                    n_ch = "—"
                    if frames is not None:
                        n_ch = str(len(get_available_channels(frames)))
                    print(
                        f"✓ [{tag}] 缓存命中 {n_ok}/{len(segment_config)} 段 | "
                        f"{n_ch} 信道 (已缓存)"
                    )
                return cached["out"], cached["fs"]
            except (ValueError, KeyError, OSError):
                if verbose:
                    print(f"⚠ 缓存文件损坏，重新计算: {cache_file.name}")

    if frames is None:
        raise ValueError("``frames`` required when filter cache misses")

    fs = estimate_sampling_rate_from_frames(frames)
    min_points = max(fp.median_window, 20)
    channels = get_available_channels(frames)
    out: Dict[str, Optional[dict]] = {}

    for seg_name in sorted(segment_config.keys()):
        ch_map: Dict[Any, dict] = {}
        metadata = None
        for ch in channels:
            seg_data = extract_segment_data(
                frames,
                {seg_name: segment_config[seg_name]},
                ch,
                [variable],
                estimated_fs=fs,
                verbose=False,
            )
            seg_raw = seg_data.get(seg_name)
            if seg_raw is None or seg_raw.get("n_points", 0) < min_points:
                continue
            # Unwrap phase (if needed) then filter
            seg_raw = dict(seg_raw)
            seg_raw[variable] = _preprocess_raw_series(seg_raw[variable], variable)
            try:
                seg_proc = process_segments(
                    {seg_name: seg_raw},
                    fs,
                    [variable],
                    fp,
                    verbose=False,
                )
            except (ValueError, RuntimeError):
                continue
            proc = seg_proc.get(seg_name)
            if proc is None:
                continue
            ch_map[ch] = proc
            if metadata is None:
                metadata = proc["metadata"]

        if not ch_map:
            out[seg_name] = None
            continue
        out[seg_name] = {
            "metadata": metadata,
            "channels": ch_map,
            "variable": variable,
            "is_phase": _is_phase_variable(variable),
        }

    if verbose:
        n_ok = sum(1 for v in out.values() if v is not None)
        tag = _variable_display_name(variable)
        print(
            f"✓ [{tag}] 多信道滤波 {n_ok}/{len(segment_config)} 段 | "
            f"{len(channels)} 信道 | fs≈{fs:.2f} Hz"
        )

    # --- cache save ---
    if cache_dir is not None and cache_file is not None:
        try:
            np.save(cache_file, {"out": out, "fs": fs}, allow_pickle=True)
        except OSError:
            if verbose:
                print(f"⚠ 缓存写入失败: {cache_file}")

    return out, fs


def _seg_bpm_stats(bpm_arr: np.ndarray, bpm_gt: Optional[float], n_windows: int) -> dict:
    """Aggregate window BPM estimates into mean / signed / relative error stats."""
    bpm_mean = float(np.nanmean(bpm_arr))
    rel_per_win = np.array(
        [
            abs(b - bpm_gt) / bpm_gt
            if (bpm_gt and bpm_gt > 0 and np.isfinite(b))
            else np.nan
            for b in bpm_arr
        ],
        dtype=float,
    )
    valid = rel_per_win[~np.isnan(rel_per_win)]
    rel_mean = float(np.mean(valid)) if valid.size else np.nan
    rel_std = float(np.std(valid, ddof=1)) if valid.size > 1 else 0.0
    signed_per_win = np.array(
        [b - bpm_gt if (bpm_gt is not None and np.isfinite(b)) else np.nan for b in bpm_arr],
        dtype=float,
    )
    return {
        "bpm_mean": bpm_mean,
        "bpm_per_window": bpm_arr,
        "bpm_signed_err_per_window": signed_per_win,
        "bpm_rel_err": rel_mean,
        "bpm_rel_err_std": rel_std,
        "n_windows": n_windows,
    }


def _aggregate_q_details(q_details: List[Dict[str, float]]) -> dict:
    """Mean q sub-scores over all channel×window entries."""
    if not q_details:
        return {}
    keys = (
        "q_valid", "q_peak", "q_energy", "q_phi", "q_c",
        "peak_snr", "energy_ratio", "jump_rate", "valid_frac",
    )
    out = {}
    for k in keys:
        vals = [d[k] for d in q_details if k in d and np.isfinite(d[k])]
        out[f"mean_{k}"] = float(np.mean(vals)) if vals else np.nan
    return out


def estimate_segment_bpm_methods(
    multichannel_segments: Dict[str, Optional[dict]],
    *,
    variable: str = "amplitudes",
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    methods: Sequence[str] = ("single", "uniform", "q_energy", "q_peak", "q_energy_peak"),
    single_channel_metric: Plan2ChannelMetric = "energy_ratio",
    verbose: bool = False,
) -> Dict[str, Optional[dict]]:
    """Per-segment BPM for Single / Uniform / q-weighted fusion (see docs/chfusion_q_energy_peak.md)."""
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()
    want_single = "single" in methods
    want_uniform = "uniform" in methods
    want_q_energy = "q_energy" in methods
    want_q_peak = "q_peak" in methods
    want_q_energy_peak = "q_energy_peak" in methods
    compute_q_phi = _is_phase_variable(variable)
    results: Dict[str, Optional[dict]] = {}

    for seg_name in sorted(multichannel_segments.keys()):
        seg = multichannel_segments[seg_name]
        if seg is None:
            results[seg_name] = None
            continue

        metadata = seg["metadata"]
        if metadata.get("segment_type") == "apnea":
            results[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]
        ch_map = seg["channels"]
        if not ch_map:
            results[seg_name] = None
            continue

        ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
        ref_len = max(len(ch_map[c][variable]["bandpass_filtered"]) for c in ch_list)
        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            if verbose:
                print(f"⚠️  {seg_name}: 长度 {ref_len} < 窗长 {win_len}，跳过")
            results[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        nfft = cfg.nfft or _next_pow2(4 * win_len)
        freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
        band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
        band_freqs = freqs[band_mask]
        hann = np.hanning(win_len)

        single_bpms: List[float] = []
        uniform_bpms: List[float] = []
        q_energy_bpms: List[float] = []
        q_peak_bpms: List[float] = []
        q_energy_peak_bpms: List[float] = []
        selected_channels: List[Any] = []
        all_q_details: List[Dict[str, float]] = []

        for st in starts:
            end = st + win_len

            if want_single:
                best_ch, _best_score = _find_best_channel(
                    ch_map, variable, st, end, fs, cfg, metric=single_channel_metric
                )
                if best_ch is not None:
                    bp_slice = ch_map[best_ch][variable]["bandpass_filtered"][st:end]
                    f_hz = _estimate_breathing_freq_hz(
                        bp_slice, fs, cfg.breath_freq_low, cfg.breath_freq_high
                    )
                    single_bpms.append(f_hz * 60.0 if np.isfinite(f_hz) else np.nan)
                    selected_channels.append(best_ch)
                else:
                    single_bpms.append(np.nan)
                    selected_channels.append(None)

            spectra: List[np.ndarray] = []
            q_energy_w: List[float] = []
            q_peak_w: List[float] = []
            q_ep_w: List[float] = []
            peak_freqs: List[float] = []

            for ch in ch_list:
                bp = ch_map[ch][variable]["bandpass_filtered"]
                hp = ch_map[ch][variable]["highpass_filtered"]
                raw = ch_map[ch][variable]["original"]
                if len(bp) < end:
                    spectra.append(np.zeros_like(band_freqs))
                    q_energy_w.append(0.0)
                    q_peak_w.append(0.0)
                    q_ep_w.append(0.0)
                    peak_freqs.append(np.nan)
                    continue

                ref_slice = raw[st:end] if len(raw) >= end else bp[st:end]
                p_norm, _qc, f_peak, detail_c = _channel_spectrum_and_q(
                    bp[st:end],
                    ref_slice,
                    fs,
                    cfg,
                    nfft,
                    band_mask,
                    band_freqs,
                    hann,
                    q_weight_mode="compact",
                    compute_q_phi=compute_q_phi,
                )
                energy_ratio = (
                    _energy_ratio(hp[st:end], fs, cfg) if len(hp) >= end else 0.0
                )
                q_energy = _quality_from_energy_ratio(
                    energy_ratio,
                    cfg.energy_ratio_min,
                    cfg.energy_ratio_good,
                    cfg.eps,
                )
                q_ep = _compose_q_weight(
                    detail_c["q_valid"],
                    detail_c["q_peak"],
                    detail_c["q_phi"],
                    "energy_peak",
                    cfg.eps,
                    q_energy=q_energy,
                )
                detail_c = {
                    **detail_c,
                    "energy_ratio": energy_ratio,
                    "q_energy": q_energy,
                    "q_energy_peak": q_ep,
                }
                q_energy_w.append(q_energy)
                q_peak_w.append(detail_c["q_peak"])
                q_ep_w.append(q_ep)
                peak_freqs.append(f_peak)
                all_q_details.append(detail_c)
                spectra.append(p_norm)

            spectra_arr = np.vstack(spectra)

            if want_uniform:
                valid_rows = np.sum(spectra_arr, axis=1) > cfg.eps
                if np.any(valid_rows):
                    uniform_fused = np.mean(spectra_arr[valid_rows], axis=0)
                else:
                    uniform_fused = np.zeros_like(band_freqs)
                uniform_bpms.append(_bpm_from_fused_spectrum(uniform_fused, band_freqs, cfg))

            if want_q_energy:
                q_energy_bpms.append(
                    _fuse_weighted_spectrum(
                        spectra_arr, np.asarray(q_energy_w), band_freqs, cfg, peak_freqs
                    )
                )
            if want_q_peak:
                q_peak_bpms.append(
                    _fuse_weighted_spectrum(
                        spectra_arr, np.asarray(q_peak_w), band_freqs, cfg, peak_freqs
                    )
                )
            if want_q_energy_peak:
                q_energy_peak_bpms.append(
                    _fuse_weighted_spectrum(
                        spectra_arr, np.asarray(q_ep_w), band_freqs, cfg, peak_freqs
                    )
                )

        seg_out: dict = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "variable": variable,
            "metadata": metadata,
            "q_summary": _aggregate_q_details(all_q_details),
        }
        if want_single:
            seg_out["fft_single_max_energy"] = {
                **_seg_bpm_stats(np.asarray(single_bpms), bpm_gt, len(starts)),
                "selected_channels": selected_channels,
            }
        if want_uniform:
            seg_out["fft_uniform_fusion"] = _seg_bpm_stats(
                np.asarray(uniform_bpms), bpm_gt, len(starts)
            )
        if want_q_energy:
            seg_out["fft_q_energy_fusion"] = _seg_bpm_stats(
                np.asarray(q_energy_bpms), bpm_gt, len(starts)
            )
        if want_q_peak:
            seg_out["fft_q_peak_fusion"] = _seg_bpm_stats(
                np.asarray(q_peak_bpms), bpm_gt, len(starts)
            )
        if want_q_energy_peak:
            seg_out["fft_q_energy_peak_fusion"] = _seg_bpm_stats(
                np.asarray(q_energy_peak_bpms), bpm_gt, len(starts)
            )
        results[seg_name] = seg_out

    return results


# ---------------------------------------------------------------------------
# Plan 2 (docs/CS呼吸算法验证整体进度.md §改进方案2):
#   A) amplitude–phase complementarity waveform inspection
#   B) per-window best-channel × best-variable modal fusion
# ---------------------------------------------------------------------------

MODAL_FUSION_VARIABLES: Tuple[Tuple[str, str], ...] = (
    ("phases", "总相位 phase"),
    ("remote_amplitudes", "远程幅值 remote"),
    ("local_amplitudes", "本地幅值 local"),
)

Plan2ChannelMetric = Literal["energy_ratio", "peak"]

ModalFusionWeightMode = Literal["equal", "energy_ratio", "fixed", "top2_equal", "top2_peak"]

MODAL_FUSION_METHOD_LABELS: Tuple[Tuple[str, str, str], ...] = (
    ("Modal equal", "modal_equal_fusion", "mediumpurple"),
    ("Modal η-weight", "modal_energy_ratio_fusion", "darkorange"),
    ("Modal 0.5/0.25/0.25", "modal_fixed_fusion", "seagreen"),
    ("Modal top2 equal", "modal_top2_equal_fusion", "steelblue"),
    ("Modal top2 ρ-weight", "modal_top2_peak_fusion", "coral"),
)

_MODAL_FUSION_WEIGHT_MODES: Dict[str, ModalFusionWeightMode] = {
    "modal_equal_fusion": "equal",
    "modal_energy_ratio_fusion": "energy_ratio",
    "modal_fixed_fusion": "fixed",
    "modal_top2_equal_fusion": "top2_equal",
    "modal_top2_peak_fusion": "top2_peak",
}

_FIXED_MODAL_WEIGHTS: Dict[str, float] = {
    "phases": 0.5,
    "remote_amplitudes": 0.25,
    "local_amplitudes": 0.25,
}

# Plan 2 §A: complementarity waveform inspection reference variables
COMPLEMENTARITY_REFERENCE_VARIABLES: Tuple[str, ...] = (
    "phases",
    "remote_amplitudes",
    "local_amplitudes",
)


def _complementarity_filename_slug(variable: str) -> str:
    """Filesystem-safe slug for complementarity figure prefixes."""
    return {
        "phases": "phase",
        "remote_amplitudes": "remote",
        "local_amplitudes": "local",
        "amplitudes": "total-amp",
    }.get(variable, variable.replace("_", "-"))


@dataclass
class Plan2Config:
    """Plan 2 channel selector and annotation settings.

    ``channel_metric``
        ``energy_ratio`` — η = E_breath / E_total on highpass (legacy Single selector).
        ``peak`` — ρ = max(P) / median(P) in breath band on bandpass (峰度 / peak prominence).
    """

    channel_metric: Plan2ChannelMetric = "peak"


def _plan2_metric_symbol(metric: Plan2ChannelMetric) -> str:
    return "η" if metric == "energy_ratio" else "ρ"


def _peak_prominence(signal_seg: np.ndarray, fs: float, cfg: ChFusionConfig) -> float:
    """Breath-band spectral peak prominence ρ = max(P) / (median(P) + ε) on bandpass."""
    if len(signal_seg) < 4 or not np.all(np.isfinite(signal_seg)):
        return 0.0
    windowed = (signal_seg - np.mean(signal_seg)) * np.hanning(len(signal_seg))
    fft_power = np.abs(np.fft.rfft(windowed)) ** 2
    fft_freq = np.fft.rfftfreq(len(windowed), 1.0 / fs)
    breath_mask = (fft_freq >= cfg.breath_freq_low) & (fft_freq <= cfg.breath_freq_high)
    p_band = fft_power[breath_mask]
    if len(p_band) == 0:
        return 0.0
    return float(np.max(p_band) / (np.median(p_band) + cfg.eps))


def _channel_selector_score(
    ch_map: Dict[Any, dict],
    variable: str,
    ch: Any,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    metric: Plan2ChannelMetric,
) -> float:
    """Per-channel score for Single / best-channel selection (Plan 2 configurable)."""
    hp = ch_map[ch][variable]["highpass_filtered"]
    bp = ch_map[ch][variable]["bandpass_filtered"]
    if len(hp) < end or len(bp) < end:
        return -1.0
    if metric == "energy_ratio":
        return _energy_ratio(hp[st:end], fs, cfg)
    return _peak_prominence(bp[st:end], fs, cfg)


def _find_best_channel(
    ch_map: Dict[Any, dict],
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    metric: Plan2ChannelMetric = "peak",
) -> Tuple[Optional[Any], float]:
    """Return (channel, score) with highest selector metric in [st, end)."""
    best_ch, best_score = None, -1.0
    for ch in ch_map:
        score = _channel_selector_score(ch_map, variable, ch, st, end, fs, cfg, metric)
        if score > best_score:
            best_score, best_ch = score, ch
    return best_ch, best_score if best_ch is not None else 0.0


def _find_best_energy_channel(
    ch_map: Dict[Any, dict],
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
) -> Tuple[Optional[Any], float]:
    """Backward-compatible wrapper: max-η channel selection."""
    return _find_best_channel(ch_map, variable, st, end, fs, cfg, metric="energy_ratio")


def _normalize_waveform(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Zero-mean unit-variance normalization for overlay comparison."""
    x = np.asarray(x, dtype=float)
    std = float(np.std(x))
    if std < eps or not np.all(np.isfinite(x)):
        return x - np.nanmean(x)
    return (x - np.mean(x)) / std


def collect_single_max_energy_window_records(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    reference_variable: str = "phases",
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    plan2_config: Optional[Plan2Config] = None,
) -> List[dict]:
    """Per-window records for Single (best-channel) on one reference variable.

    Channel selection uses ``plan2_config.channel_metric`` (η or ρ).
    Each record includes bandpass waveforms plus both η and ρ for all four variables.
    """
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()
    p2 = plan2_config or Plan2Config()
    metric = p2.channel_metric
    all_vars = [v[0] for v in CS_SIGNAL_VARIABLES]
    ref_mc = multichannel_by_var[reference_variable]
    records: List[dict] = []

    for seg_name in sorted(ref_mc.keys()):
        ref_seg = ref_mc[seg_name]
        if ref_seg is None:
            continue
        metadata = ref_seg["metadata"]
        if metadata.get("segment_type") == "apnea":
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]
        ref_ch_map = ref_seg["channels"]
        if not ref_ch_map:
            continue

        ref_len = max(len(c[reference_variable]["bandpass_filtered"]) for c in ref_ch_map.values())
        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        for wi, st in enumerate(starts):
            end = st + win_len
            best_ch, ref_score = _find_best_channel(
                ref_ch_map, reference_variable, st, end, fs, cfg, metric=metric
            )
            if best_ch is None:
                continue

            bp_slice = ref_ch_map[best_ch][reference_variable]["bandpass_filtered"][st:end]
            f_hz = _estimate_breathing_freq_hz(
                bp_slice, fs, cfg.breath_freq_low, cfg.breath_freq_high
            )
            bpm = float(f_hz * 60.0) if np.isfinite(f_hz) else np.nan
            rel_err = (
                abs(bpm - bpm_gt) / bpm_gt
                if (bpm_gt and bpm_gt > 0 and np.isfinite(bpm))
                else np.nan
            )

            channel_scores: Dict[str, Dict[str, float]] = {}
            bpm_estimates: Dict[str, float] = {}
            waveforms: Dict[str, Optional[np.ndarray]] = {}
            for var in all_vars:
                var_seg = multichannel_by_var.get(var, {}).get(seg_name)
                if var_seg is None or best_ch not in var_seg["channels"]:
                    channel_scores[var] = {"energy_ratio": np.nan, "peak": np.nan}
                    bpm_estimates[var] = np.nan
                    waveforms[var] = None
                    continue
                hp = var_seg["channels"][best_ch][var]["highpass_filtered"][st:end]
                bp = var_seg["channels"][best_ch][var]["bandpass_filtered"][st:end]
                channel_scores[var] = {
                    "energy_ratio": _energy_ratio(hp, fs, cfg),
                    "peak": _peak_prominence(bp, fs, cfg),
                }
                f_hz_var = _estimate_breathing_freq_hz(
                    bp, fs, cfg.breath_freq_low, cfg.breath_freq_high
                )
                bpm_estimates[var] = float(f_hz_var * 60.0) if np.isfinite(f_hz_var) else np.nan
                waveforms[var] = bp

            records.append(
                {
                    "segment": seg_name,
                    "window_idx": wi,
                    "start": st,
                    "end": end,
                    "fs": fs,
                    "bpm_gt": bpm_gt,
                    "bpm_est": bpm,
                    "rel_err": rel_err,
                    "reference_variable": reference_variable,
                    "best_channel": best_ch,
                    "channel_metric": metric,
                    "ref_channel_score": ref_score,
                    "channel_scores": channel_scores,
                    "bpm_estimates": bpm_estimates,
                    "energy_ratios": {v: channel_scores[v]["energy_ratio"] for v in all_vars},
                    "waveforms": waveforms,
                }
            )
    return records


def select_complementarity_windows(records: List[dict]) -> Dict[str, Optional[dict]]:
    """Pick best / worst / median-BPM-accuracy windows from collected records."""
    valid = [r for r in records if np.isfinite(r.get("rel_err", np.nan))]
    if not valid:
        return {"best": None, "worst": None, "median": None}
    ranked = sorted(valid, key=lambda r: r["rel_err"])
    n = len(ranked)
    return {
        "best": ranked[0],
        "worst": ranked[-1],
        "median": ranked[n // 2],
    }


def _complementarity_trace_label(
    variable: str,
    record: dict,
    metric: Plan2ChannelMetric,
) -> str:
    """Legend text: variable name + selector score + per-variable BPM estimate."""
    sym = _plan2_metric_symbol(metric)
    scores = record.get("channel_scores", {}).get(variable, {})
    val = scores.get(metric, record.get("energy_ratios", {}).get(variable, np.nan))
    score_str = f"{sym}={val:.2f}" if np.isfinite(val) else f"{sym}=N/A"
    bpm = record.get("bpm_estimates", {}).get(variable, np.nan)
    bpm_str = f"{bpm:.1f} BPM" if np.isfinite(bpm) else "BPM N/A"
    return f"{_variable_plot_label(variable)} ({score_str}, {bpm_str})"


def plot_complementarity_waveforms(
    selected: Dict[str, Optional[dict]],
    *,
    figures_dir=None,
    filename_prefix: str = "plan2_complementarity",
    reference_variable: str = "phases",
    show: bool = True,
    save: bool = True,
) -> List[Path]:
    """Plot normalized bandpass waveforms for four variables at reference-best channel.

    Legend shows selector metric (η or ρ) and Single FFT BPM per variable on that channel.
    """
    import matplotlib.pyplot as plt

    saved: List[Path] = []
    ref_label = _variable_plot_label(reference_variable)

    for tag, record in selected.items():
        if record is None:
            print(f"⚠️  互补性图 [{tag}]：无可用窗口，跳过")
            continue

        metric: Plan2ChannelMetric = record.get("channel_metric", "peak")
        fs = record["fs"]
        t = np.arange(record["end"] - record["start"]) / fs
        fig, ax = plt.subplots(figsize=(10, 4.5))

        for var, _lbl in CS_SIGNAL_VARIABLES:
            wf = record["waveforms"].get(var)
            if wf is None or len(wf) == 0:
                continue
            ax.plot(
                t,
                _normalize_waveform(wf),
                label=_complementarity_trace_label(var, record, metric),
                color=PART1_VARIABLE_COLORS.get(var, "gray"),
                linewidth=1.2,
                alpha=0.9,
            )

        bpm_est = record["bpm_est"]
        bpm_gt = record["bpm_gt"]
        ch = record["best_channel"]
        ax.set_xlabel("Time within window (s)")
        ax.set_ylabel("Normalized bandpass amplitude")
        ax.set_title(
            f"{ref_label} — {tag} BPM window | seg={record['segment']} win={record['window_idx']} "
            f"ch={ch} | selector={metric} | est={bpm_est:.2f} GT={bpm_gt:.2f} BPM | "
            f"rel err={record['rel_err']*100:.1f}%"
        )
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.25)
        plt.tight_layout()

        if save and figures_dir is not None:
            fig_path = Path(figures_dir) / _chfusion_figure_name(f"{filename_prefix}_{tag}")
            _save_chfusion_figure(fig, fig_path)
            saved.append(fig_path)
            print(f"✓ 互补性波形图 [{tag}]: {fig_path}")
        if show:
            plt.show()
        else:
            plt.close(fig)

    return saved


def collect_complementarity_by_reference(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    reference_variables: Sequence[str] = COMPLEMENTARITY_REFERENCE_VARIABLES,
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    plan2_config: Optional[Plan2Config] = None,
) -> Dict[str, dict]:
    """Collect best / worst / median BPM windows for each reference variable."""
    out: Dict[str, dict] = {}
    for ref_var in reference_variables:
        records = collect_single_max_energy_window_records(
            multichannel_by_var,
            reference_variable=ref_var,
            config=config,
            metric_params=metric_params,
            plan2_config=plan2_config,
        )
        out[ref_var] = {
            "reference_variable": ref_var,
            "window_records": records,
            "complementarity_windows": select_complementarity_windows(records),
        }
    return out


def print_complementarity_window_summary(
    complementarity_by_reference: Dict[str, dict],
    *,
    reference_variables: Optional[Sequence[str]] = None,
) -> None:
    """Print best / worst / median window picks per reference variable."""
    refs = reference_variables or complementarity_by_reference.keys()
    print("\n=== 互补性窗口摘要（各参考变量 Single BPM best / worst / median）===")
    for ref_var in refs:
        block = complementarity_by_reference.get(ref_var)
        if block is None:
            continue
        label = _variable_display_name(ref_var)
        n = len(block.get("window_records", []))
        print(f"\n--- {label} ({ref_var}) | {n} windows ---")
        for tag, rec in block.get("complementarity_windows", {}).items():
            if rec is None:
                print(f"  [{tag}] — no window")
                continue
            print(
                f"  [{tag}] seg={rec['segment']} win={rec['window_idx']} ch={rec['best_channel']} "
                f"| est={rec['bpm_est']:.2f} GT={rec['bpm_gt']:.2f} | rel err={rec['rel_err']*100:.1f}%"
            )


def plot_complementarity_waveforms_all(
    complementarity_by_reference: Dict[str, dict],
    *,
    reference_variables: Optional[Sequence[str]] = None,
    figures_dir=None,
    filename_prefix: str = "plan2_complementarity",
    show: bool = True,
    save: bool = True,
) -> List[Path]:
    """Plot complementarity figures for each reference variable (3 tags × N refs)."""
    saved: List[Path] = []
    refs = list(reference_variables or complementarity_by_reference.keys())
    for ref_var in refs:
        block = complementarity_by_reference.get(ref_var)
        if block is None:
            continue
        slug = _complementarity_filename_slug(ref_var)
        paths = plot_complementarity_waveforms(
            block["complementarity_windows"],
            figures_dir=figures_dir,
            filename_prefix=f"{filename_prefix}_{slug}",
            reference_variable=ref_var,
            show=show,
            save=save,
        )
        saved.extend(paths)
    return saved


def estimate_modal_best_channel_fusion(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    weight_mode: ModalFusionWeightMode = "equal",
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    plan2_config: Optional[Plan2Config] = None,
    verbose: bool = False,
) -> Dict[str, Optional[dict]]:
    """Per-window modal fusion: best channel per variable, fuse phase/remote/local spectra.

    Channel selection follows ``plan2_config.channel_metric``. Weight modes ``top2_equal``
    and ``top2_peak`` keep only the two highest-scoring variables (equal 0.5 or ρ-weighted).
    """
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()
    p2 = plan2_config or Plan2Config()
    channel_metric = p2.channel_metric
    modal_vars = [v[0] for v in MODAL_FUSION_VARIABLES]
    results: Dict[str, Optional[dict]] = {}

    ref_mc = multichannel_by_var["phases"]
    for seg_name in sorted(ref_mc.keys()):
        ref_seg = ref_mc[seg_name]
        if ref_seg is None:
            results[seg_name] = None
            continue
        metadata = ref_seg["metadata"]
        if metadata.get("segment_type") == "apnea":
            results[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]

        seg_maps: Dict[str, Dict[Any, dict]] = {}
        ref_len = 0
        ok = True
        for var in modal_vars:
            seg = multichannel_by_var.get(var, {}).get(seg_name)
            if seg is None or not seg["channels"]:
                ok = False
                break
            seg_maps[var] = seg["channels"]
            ref_len = max(
                ref_len,
                max(len(c[var]["bandpass_filtered"]) for c in seg["channels"].values()),
            )
        if not ok or ref_len == 0:
            results[seg_name] = None
            continue

        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            if verbose:
                print(f"⚠️  {seg_name}: 长度 {ref_len} < 窗长 {win_len}，跳过 modal fusion")
            results[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        nfft = cfg.nfft or _next_pow2(4 * win_len)
        freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
        band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
        band_freqs = freqs[band_mask]
        hann = np.hanning(win_len)

        bpms: List[float] = []
        for st in starts:
            end = st + win_len
            var_entries: List[Tuple[str, np.ndarray, float, float, float]] = []

            for var in modal_vars:
                ch_map = seg_maps[var]
                best_ch, selector_score = _find_best_channel(
                    ch_map, var, st, end, fs, cfg, metric=channel_metric
                )
                if best_ch is None:
                    continue

                bp = ch_map[best_ch][var]["bandpass_filtered"]
                hp = ch_map[best_ch][var]["highpass_filtered"]
                raw = ch_map[best_ch][var]["original"]
                if len(bp) < end:
                    continue

                ref_slice = raw[st:end] if len(raw) >= end else bp[st:end]
                p_norm, _qc, _fp, _det = _channel_spectrum_and_q(
                    bp[st:end],
                    ref_slice,
                    fs,
                    cfg,
                    nfft,
                    band_mask,
                    band_freqs,
                    hann,
                    q_weight_mode="compact",
                    compute_q_phi=_is_phase_variable(var),
                )
                peak_score = _peak_prominence(bp[st:end], fs, cfg)
                eta = _energy_ratio(hp[st:end], fs, cfg) if len(hp) >= end else 0.0
                var_entries.append((var, p_norm, selector_score, peak_score, eta))

            if not var_entries:
                bpms.append(np.nan)
                continue

            if weight_mode in ("top2_equal", "top2_peak"):
                ranked = sorted(var_entries, key=lambda e: e[2], reverse=True)
                use = ranked[:2]
                if weight_mode == "top2_equal":
                    w_arr = np.ones(len(use), dtype=float)
                else:
                    w_arr = np.asarray([max(e[3], cfg.eps) for e in use], dtype=float)
                if np.sum(w_arr) <= cfg.eps:
                    bpms.append(np.nan)
                    continue
                w_arr = w_arr / np.sum(w_arr)
                fused = np.sum(w_arr[:, None] * np.vstack([e[1] for e in use]), axis=0)
                bpms.append(_bpm_from_fused_spectrum(fused, band_freqs, cfg))
                continue

            spectra: List[np.ndarray] = []
            weights: List[float] = []
            for var, p_norm, _selector_score, _peak_score, eta in var_entries:
                spectra.append(p_norm)
                if weight_mode == "equal":
                    weights.append(1.0)
                elif weight_mode == "energy_ratio":
                    weights.append(max(eta, cfg.eps))
                else:
                    weights.append(_FIXED_MODAL_WEIGHTS[var])

            w_arr = np.asarray(weights, dtype=float)
            if np.sum(w_arr) <= cfg.eps:
                bpms.append(np.nan)
            else:
                w_arr = w_arr / np.sum(w_arr)
                fused = np.sum(w_arr[:, None] * np.vstack(spectra), axis=0)
                bpms.append(_bpm_from_fused_spectrum(fused, band_freqs, cfg))

        method_key = {
            "equal": "modal_equal_fusion",
            "energy_ratio": "modal_energy_ratio_fusion",
            "fixed": "modal_fixed_fusion",
            "top2_equal": "modal_top2_equal_fusion",
            "top2_peak": "modal_top2_peak_fusion",
        }[weight_mode]
        results[seg_name] = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "variable": "modal_fusion",
            "metadata": metadata,
            method_key: _seg_bpm_stats(np.asarray(bpms), bpm_gt, len(starts)),
        }

    return results


def run_modal_fusion_benchmark(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    config: Optional[ChFusionConfig] = None,
    metric_params: Optional[BreathMetricParams] = None,
    plan2_config: Optional[Plan2Config] = None,
    verbose: bool = True,
) -> Dict[str, dict]:
    """Run all Plan-2 modal fusion weight strategies (5 methods)."""
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()
    p2 = plan2_config or Plan2Config()
    merged: Dict[str, Optional[dict]] = {}

    for label, key, _color in MODAL_FUSION_METHOD_LABELS:
        mode = _MODAL_FUSION_WEIGHT_MODES[key]
        partial = estimate_modal_best_channel_fusion(
            multichannel_by_var,
            weight_mode=mode,
            config=cfg,
            metric_params=mp,
            plan2_config=p2,
            verbose=verbose,
        )
        for seg_name, row in partial.items():
            if row is None:
                merged.setdefault(seg_name, None)
                continue
            if merged.get(seg_name) is None:
                merged[seg_name] = {
                    "segment": seg_name,
                    "bpm_gt": row["bpm_gt"],
                    "metadata": row["metadata"],
                }
            merged[seg_name][key] = row[key]
        if verbose:
            stats = _overall_rel_error(partial, key)
            print(
                f"✓ [{label}] modal fusion | mean err {stats['mean_rel_err_pct']:.2f}% "
                f"± {stats['std_rel_err_pct']:.2f}% | n_seg={stats['n_segments']}"
            )

    return {"results": merged, "methods": MODAL_FUSION_METHOD_LABELS}


def _baseline_single_key(variable: str) -> str:
    return f"baseline_single_{variable}"


def _baseline_uniform_key(variable: str) -> str:
    return f"baseline_uniform_{variable}"


def build_plan2_comparison_method_labels() -> Tuple[Tuple[str, str, str], ...]:
    """Method registry for Plan 2 violins: 4×Single, 4×Uniform, 5×modal fusion."""
    labels: List[Tuple[str, str, str]] = []
    for var, _lbl in CS_SIGNAL_VARIABLES:
        color = PART1_VARIABLE_COLORS[var]
        vlabel = _variable_plot_label(var)
        labels.append((f"Single {vlabel}", _baseline_single_key(var), color))
        labels.append((f"Uniform {vlabel}", _baseline_uniform_key(var), color))
    labels.extend(MODAL_FUSION_METHOD_LABELS)
    return tuple(labels)


def build_plan2_violin_results(plan2: dict) -> Dict[str, Optional[dict]]:
    """Flatten variable baselines + modal fusion into one method_results dict."""
    variable_baselines = plan2["variable_baselines"]
    modal_results = plan2["modal_benchmark"]["results"]
    merged: Dict[str, Optional[dict]] = {}

    all_segs: set = set()
    for results in variable_baselines.values():
        all_segs.update(results.keys())
    all_segs.update(modal_results.keys())

    for seg_name in sorted(all_segs):
        row: dict = {"bpm_gt": None}
        for var, results in variable_baselines.items():
            base = results.get(seg_name)
            if base is None:
                continue
            if row["bpm_gt"] is None:
                row["bpm_gt"] = base.get("bpm_gt")
            single = base.get("fft_single_max_energy")
            uniform = base.get("fft_uniform_fusion")
            if single is not None:
                row[_baseline_single_key(var)] = single
            if uniform is not None:
                row[_baseline_uniform_key(var)] = uniform

        modal = modal_results.get(seg_name)
        if modal is not None:
            if row["bpm_gt"] is None:
                row["bpm_gt"] = modal.get("bpm_gt")
            for _label, key, _color in MODAL_FUSION_METHOD_LABELS:
                if key in modal:
                    row[key] = modal[key]

        merged[seg_name] = row if row.get("bpm_gt") is not None else None
    return merged


PLAN2_CATEGORY_COLORS: Dict[str, str] = {
    "Single": "steelblue",
    "Uniform": "seagreen",
    "Modal": "coral",
}


def _plan2_method_specs() -> List[dict]:
    """Registry of all Plan 2 comparison methods (baselines + modal fusion)."""
    specs: List[dict] = []
    short_var = {
        "amplitudes": "amp",
        "remote_amplitudes": "rem",
        "local_amplitudes": "loc",
        "phases": "pha",
    }
    for var, _lbl in CS_SIGNAL_VARIABLES:
        vlabel = _variable_plot_label(var)
        sv = short_var.get(var, var[:3])
        specs.append(
            {
                "category": "Single",
                "label": f"Single {vlabel}",
                "short_label": f"S {sv}",
                "result_key": "fft_single_max_energy",
                "storage_key": _baseline_single_key(var),
                "baseline_var": var,
                "color": PART1_VARIABLE_COLORS[var],
            }
        )
        specs.append(
            {
                "category": "Uniform",
                "label": f"Uniform {vlabel}",
                "short_label": f"U {sv}",
                "result_key": "fft_uniform_fusion",
                "storage_key": _baseline_uniform_key(var),
                "baseline_var": var,
                "color": PART1_VARIABLE_COLORS[var],
            }
        )
    modal_short = {
        "modal_equal_fusion": "M eq",
        "modal_energy_ratio_fusion": "M η",
        "modal_fixed_fusion": "M 0.5",
        "modal_top2_equal_fusion": "M t2=",
        "modal_top2_peak_fusion": "M t2ρ",
    }
    for label, key, color in MODAL_FUSION_METHOD_LABELS:
        specs.append(
            {
                "category": "Modal",
                "label": label,
                "short_label": modal_short.get(key, label[:6]),
                "result_key": key,
                "storage_key": key,
                "baseline_var": None,
                "color": color,
            }
        )
    return specs


def _plan2_results_for_spec(plan2: dict, spec: dict) -> Dict[str, Optional[dict]]:
    if spec["baseline_var"] is not None:
        return plan2["variable_baselines"][spec["baseline_var"]]
    return plan2["modal_benchmark"]["results"]


def build_plan2_leaderboard_rows(plan2: dict) -> List[dict]:
    """Overall mean relative BPM error per method, sorted ascending (best first)."""
    rows: List[dict] = []
    for spec in _plan2_method_specs():
        stats = _overall_rel_error(
            _plan2_results_for_spec(plan2, spec), spec["result_key"]
        )
        if not np.isfinite(stats["mean_rel_err_pct"]):
            continue
        rows.append({**spec, **stats})
    rows.sort(key=lambda r: r["mean_rel_err_pct"])
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def build_plan2_segment_error_matrix(
    plan2: dict,
) -> Tuple[List[str], List[str], np.ndarray, List[dict]]:
    """Segment × method matrix of segment-mean relative BPM error (%)."""
    specs = _plan2_method_specs()
    violin_results = build_plan2_violin_results(plan2)
    segments = [
        s
        for s in sorted(violin_results.keys())
        if violin_results[s] is not None and violin_results[s].get("bpm_gt") is not None
    ]
    n_seg, n_meth = len(segments), len(specs)
    matrix = np.full((n_seg, n_meth), np.nan)
    for j, spec in enumerate(specs):
        results = _plan2_results_for_spec(plan2, spec)
        for i, seg in enumerate(segments):
            row = results.get(seg)
            if row is None:
                continue
            block = row.get(spec["result_key"])
            if block is None:
                continue
            err = block.get("bpm_rel_err")
            if err is not None and np.isfinite(err):
                matrix[i, j] = float(err) * 100.0
    short_labels = [s["short_label"] for s in specs]
    return segments, short_labels, matrix, specs


def _plan2_category_method_labels(category: str) -> Tuple[Tuple[str, str, str], ...]:
    return tuple(
        (s["label"], s["storage_key"], s["color"])
        for s in _plan2_method_specs()
        if s["category"] == category
    )


def plot_plan2_leaderboard_bars(
    plan2: dict,
    *,
    figures_dir=None,
    filename: str = "",
    show: bool = True,
    save: bool = True,
):
    """Horizontal bar chart: overall mean rel. BPM error (%) for all Plan 2 methods."""
    import matplotlib.pyplot as plt

    if not filename:
        filename = _chfusion_figure_name("plan2_leaderboard_bars")

    rows = build_plan2_leaderboard_rows(plan2)
    if not rows:
        print("⚠️  Plan 2 排行榜：无可用数据")
        return None

    labels = [r["label"] for r in rows]
    means = np.asarray([r["mean_rel_err_pct"] for r in rows], dtype=float)
    colors = [PLAN2_CATEGORY_COLORS.get(r["category"], "gray") for r in rows]

    fig_h = max(5.0, 0.38 * len(rows) + 1.5)
    fig, ax = plt.subplots(figsize=(9.0, fig_h))
    y = np.arange(len(rows))
    ax.barh(y, means, color=colors, edgecolor="black", alpha=0.85, height=0.72)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Mean relative BPM error (%)")
    ax.set_title("Plan 2 method leaderboard (segment mean, lower is better)")
    ax.grid(True, axis="x", alpha=0.25)

    for i, (m, r) in enumerate(zip(means, rows)):
        ax.text(m + 0.3, i, f"{m:.1f}%", va="center", fontsize=8)

    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, color=c, ec="black", alpha=0.85, label=cat)
        for cat, c in PLAN2_CATEGORY_COLORS.items()
    ]
    ax.legend(handles=legend_handles, loc="lower right", fontsize=8)
    plt.tight_layout()

    fig_path = Path(figures_dir) / filename if save and figures_dir is not None else None
    _finalize_chfusion_figure(fig, show=show, save_path=fig_path)
    if fig_path is not None:
        print(f"✓ Plan 2 排行榜柱状图: {fig_path}")
    return fig


def plot_plan2_segment_method_heatmap(
    plan2: dict,
    *,
    figures_dir=None,
    filename: str = "",
    show: bool = True,
    save: bool = True,
):
    """Heatmap: script segment × method, cell = segment mean rel. BPM error (%)."""
    import matplotlib.pyplot as plt

    if not filename:
        filename = _chfusion_figure_name("plan2_segment_method_heatmap")

    segments, meth_labels, matrix, _specs = build_plan2_segment_error_matrix(plan2)
    if not segments or matrix.size == 0:
        print("⚠️  Plan 2 热力图：无可用数据")
        return None

    gt_by_seg = {}
    vr = build_plan2_violin_results(plan2)
    for s in segments:
        row = vr.get(s)
        if row is not None and row.get("bpm_gt") is not None:
            gt_by_seg[s] = float(row["bpm_gt"])
    row_labels = [f"{seg}\nGT={gt_by_seg.get(seg, float('nan')):.1f}" for seg in segments]

    fig_w = max(10.0, 0.55 * len(meth_labels) + 3.0)
    fig, ax = plt.subplots(figsize=(fig_w, max(4.5, 0.55 * len(segments) + 2.0)))
    vmax = float(np.nanpercentile(matrix, 95)) if np.any(np.isfinite(matrix)) else 30.0
    im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd", vmin=0.0, vmax=max(vmax, 1.0))
    ax.set_xticks(np.arange(len(meth_labels)))
    ax.set_yticks(np.arange(len(segments)))
    ax.set_xticklabels(meth_labels, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(row_labels, fontsize=9)
    ax.set_title("Plan 2: segment × method mean rel. BPM error (%)")

    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            val = matrix[i, j]
            if np.isfinite(val):
                ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=7, color="black")

    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label("Rel. error (%)")
    plt.tight_layout()

    fig_path = Path(figures_dir) / filename if save and figures_dir is not None else None
    _finalize_chfusion_figure(fig, show=show, save_path=fig_path, bbox_inches="tight")
    if fig_path is not None:
        print(f"✓ Plan 2 段×方法热力图: {fig_path}")
    return fig


def plot_plan2_violins_by_category(
    plan2: dict,
    *,
    figures_dir=None,
    filename: str = "",
    show: bool = True,
    save: bool = True,
):
    """3-panel violins: Single (4) / Uniform (4) / Modal (5) window-level signed errors."""
    import matplotlib.pyplot as plt

    if not filename:
        filename = _chfusion_figure_name("plan2_violins_by_category")

    violin_results = build_plan2_violin_results(plan2)
    categories = ("Single", "Uniform", "Modal")
    panel_specs = [(cat, _plan2_category_method_labels(cat)) for cat in categories]

    all_records: List[dict] = []
    for _cat, labels in panel_specs:
        all_records.extend(collect_window_signed_errors(violin_results, labels))
    if not all_records:
        print("⚠️  Plan 2 分类小提琴图：无可用数据")
        return None

    segments = sorted({r["segment"] for r in all_records})
    gt_by_seg = {r["segment"]: r["bpm_gt"] for r in all_records}

    panel_h = 5.0
    fig, axes = plt.subplots(
        len(categories),
        1,
        figsize=(max(12, len(segments) * 2.2), panel_h * len(categories)),
        sharey=True,
    )
    axes_flat = np.atleast_1d(axes).flatten()

    for ax, (cat, labels) in zip(axes_flat, panel_specs):
        subset = [r for r in all_records if r["method"] in [m[0] for m in labels]]
        colors = {m[0]: m[2] for m in labels}
        _draw_grouped_violins_on_ax(
            ax,
            subset,
            segments=segments,
            group_ids=[m[0] for m in labels],
            group_field="method",
            colors=colors,
            gt_by_seg=gt_by_seg,
            title=f"{cat} baselines" if cat != "Modal" else "Modal fusion",
            show_ylabel=(ax is axes_flat[0]),
        )
        method_handles = [
            plt.Line2D(
                [0], [0],
                color=m[2],
                lw=6,
                alpha=0.65,
                label=m[0],
            )
            for m in labels
        ]
        ax.legend(
            handles=_violin_legend_with_stats(method_handles),
            loc="upper right",
            fontsize=6,
            framealpha=0.92,
        )

    fig.suptitle(
        "Plan 2: window-level signed BPM error by category (y=0 is GT)",
        y=0.995,
        fontsize=11,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.98])

    fig_path = Path(figures_dir) / filename if save and figures_dir is not None else None
    _finalize_chfusion_figure(fig, show=show, save_path=fig_path, bbox_inches="tight")
    if fig_path is not None:
        print(f"✓ Plan 2 分类小提琴图: {fig_path}")
    return fig


def build_plan2_cross_domain_aggregate_rows(
    results_by_tag: Dict[str, dict],
    *,
    domain_order: Optional[Sequence[str]] = None,
) -> Tuple[List[str], List[dict]]:
    """Per-method mean ± std of segment-mean rel. BPM error (%) across domains.

    Each domain contributes one scalar (that domain's overall mean for the method);
    ``mean_across_domains`` / ``std_across_domains`` summarize those scalars.
    """
    tags = list(domain_order) if domain_order is not None else sorted(results_by_tag.keys())
    rows: List[dict] = []
    for spec in _plan2_method_specs():
        domain_errs = np.full(len(tags), np.nan, dtype=float)
        for i, tag in enumerate(tags):
            lb = {r["label"]: r for r in build_plan2_leaderboard_rows(results_by_tag[tag])}
            val = lb.get(spec["label"], {}).get("mean_rel_err_pct", np.nan)
            if np.isfinite(val):
                domain_errs[i] = float(val)
        finite = domain_errs[np.isfinite(domain_errs)]
        if len(finite) == 0:
            continue
        rows.append(
            {
                **spec,
                "domain_errs": domain_errs,
                "mean_across_domains": float(np.mean(finite)),
                "std_across_domains": (
                    float(np.std(finite, ddof=1)) if len(finite) > 1 else 0.0
                ),
                "n_domains": int(len(finite)),
            }
        )
    rows.sort(key=lambda r: r["mean_across_domains"])
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return tags, rows


def print_plan2_cross_domain_aggregate_table(
    results_by_tag: Dict[str, dict],
    *,
    domain_order: Optional[Sequence[str]] = None,
) -> List[dict]:
    """Print per-method errors per domain plus cross-domain mean ± std."""
    tags, rows = build_plan2_cross_domain_aggregate_rows(
        results_by_tag, domain_order=domain_order
    )
    if not rows:
        print("⚠️  跨场景聚合：无可用数据")
        return rows

    col_w = 9
    header = f"{'方法':<32}" + "".join(f"{t:>{col_w}}" for t in tags) + f"{'mean':>8}{'±std':>7}"
    print(f"\n=== Plan 2 跨场景聚合（各域 segment-mean err% → mean±std）===")
    print(f"Domains ({len(tags)}): {' / '.join(tags)}")
    print(header)
    print("-" * (32 + col_w * len(tags) + 15))
    for row in rows:
        line = f"{row['label']:<32}"
        for val in row["domain_errs"]:
            line += f"{val:>{col_w}.2f}" if np.isfinite(val) else f"{'—':>{col_w}}"
        line += f"{row['mean_across_domains']:8.2f}{row['std_across_domains']:7.2f}"
        print(line)
    best = rows[0]
    print(
        f"\n★ 跨场景平均最优：{best['label']} → "
        f"{best['mean_across_domains']:.2f}% ± {best['std_across_domains']:.2f}% "
        f"(n={best['n_domains']} domains)\n"
    )
    return rows


def plot_plan2_cross_domain_aggregate_bars(
    results_by_tag: Dict[str, dict],
    *,
    domain_order: Optional[Sequence[str]] = None,
    figures_dir=None,
    filename: str = "",
    show: bool = True,
    save: bool = True,
):
    """Bar chart: cross-domain mean rel. BPM error with ±1 std across domains."""
    import matplotlib.pyplot as plt

    if not filename:
        filename = _chfusion_figure_name("plan2_cross_domain_aggregate_bars")

    tags, rows = build_plan2_cross_domain_aggregate_rows(
        results_by_tag, domain_order=domain_order
    )
    if not rows:
        print("⚠️  跨场景聚合柱状图：无可用数据")
        return None

    labels = [r["label"] for r in rows]
    means = np.asarray([r["mean_across_domains"] for r in rows], dtype=float)
    stds = np.asarray([r["std_across_domains"] for r in rows], dtype=float)
    colors = [PLAN2_CATEGORY_COLORS.get(r["category"], "gray") for r in rows]

    fig_h = max(5.0, 0.38 * len(rows) + 1.5)
    fig, ax = plt.subplots(figsize=(9.5, fig_h))
    y = np.arange(len(rows))
    ax.barh(
        y,
        means,
        xerr=stds,
        color=colors,
        edgecolor="black",
        alpha=0.85,
        height=0.72,
        capsize=3,
        error_kw={"elinewidth": 1.2, "ecolor": "black", "capthick": 1.2},
    )
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Mean relative BPM error across domains (%)")
    ax.set_title(
        f"Plan 2 cross-domain aggregate (mean ± std over {len(tags)} domains: "
        + " / ".join(tags)
        + ")",
        fontsize=10,
    )
    ax.grid(True, axis="x", alpha=0.25)

    for i, (m, s) in enumerate(zip(means, stds)):
        ax.text(m + s + 0.35, i, f"{m:.1f}±{s:.1f}%", va="center", fontsize=8)

    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, color=c, ec="black", alpha=0.85, label=cat)
        for cat, c in PLAN2_CATEGORY_COLORS.items()
    ]
    ax.legend(handles=legend_handles, loc="lower right", fontsize=8)
    plt.tight_layout()

    fig_path = Path(figures_dir) / filename if save and figures_dir is not None else None
    _finalize_chfusion_figure(fig, show=show, save_path=fig_path)
    if fig_path is not None:
        print(f"✓ Plan 2 跨场景聚合柱状图: {fig_path}")
    return fig


def plot_plan2_comparison_figures(
    plan2: dict,
    *,
    figures_dir=None,
    show: bool = True,
    save: bool = True,
) -> List[Path]:
    """Generate Plan 2 overview figures: leaderboard bars, heatmap, category violins."""
    saved: List[Path] = []
    specs = [
        ("plan2_leaderboard_bars.pdf", plot_plan2_leaderboard_bars),
        ("plan2_segment_method_heatmap.pdf", plot_plan2_segment_method_heatmap),
        ("plan2_violins_by_category.pdf", plot_plan2_violins_by_category),
    ]
    for fname, plot_fn in specs:
        plot_fn(plan2, figures_dir=figures_dir, filename=fname, show=show, save=save)
        if save and figures_dir is not None:
            saved.append(Path(figures_dir) / fname)
    return saved


def print_plan2_comparison_table(plan2: dict) -> None:
    """Print four-variable Single/Uniform baselines alongside modal fusion methods."""
    variable_baselines = plan2["variable_baselines"]
    modal_results = plan2["modal_benchmark"]["results"]

    print("\n=== Plan 2：四变量 Single / Uniform 基线（段均值相对误差）===")
    print(f"{'变量':<22} {'Single err%':>12} {'±std%':>8} {'Uniform err%':>12} {'±std%':>8}")
    print("-" * 68)
    baseline_rows: List[Tuple[str, float]] = []
    for var, lbl in CS_SIGNAL_VARIABLES:
        results = variable_baselines[var]
        stats_s = _overall_rel_error(results, "fft_single_max_energy")
        stats_u = _overall_rel_error(results, "fft_uniform_fusion")
        print(
            f"{lbl:<22} {stats_s['mean_rel_err_pct']:12.2f} "
            f"{stats_s['std_rel_err_pct']:8.2f} "
            f"{stats_u['mean_rel_err_pct']:12.2f} {stats_u['std_rel_err_pct']:8.2f}"
        )
        baseline_rows.append((f"Single {lbl}", stats_s["mean_rel_err_pct"]))
        baseline_rows.append((f"Uniform {lbl}", stats_u["mean_rel_err_pct"]))

    print_modal_fusion_table(
        plan2["modal_benchmark"],
        channel_metric=plan2.get("plan2_config", Plan2Config()).channel_metric,
    )

    print("=== Plan 2：总体 mean err% 排行（基线 + 模态融合）===")
    print(f"{'#':>3} {'方法':<28} {'err%':>8} {'±std%':>8}")
    print("-" * 52)
    ranked: List[Tuple[str, dict]] = []
    for name, err in baseline_rows:
        if np.isfinite(err):
            ranked.append((name, {"mean_rel_err_pct": err, "std_rel_err_pct": np.nan}))
    for label, key, _ in MODAL_FUSION_METHOD_LABELS:
        stats = _overall_rel_error(modal_results, key)
        if np.isfinite(stats["mean_rel_err_pct"]):
            ranked.append((label, stats))
    ranked.sort(key=lambda x: x[1]["mean_rel_err_pct"])
    for i, (name, stats) in enumerate(ranked, start=1):
        std = stats.get("std_rel_err_pct", np.nan)
        std_str = f"{std:8.2f}" if np.isfinite(std) else "     N/A"
        print(f"{i:3d} {name:<28} {stats['mean_rel_err_pct']:8.2f} {std_str}")
    if ranked:
        best = ranked[0]
        print(f"\n★ 当前最优：{best[0]} → mean err {best[1]['mean_rel_err_pct']:.2f}%\n")


def print_modal_fusion_table(modal_benchmark: dict, *, channel_metric: Plan2ChannelMetric = "peak") -> None:
    """Print per-segment BPM relative error for modal fusion methods."""
    results = modal_benchmark["results"]
    sym = _plan2_metric_symbol(channel_metric)
    print(f"\n=== 改进方案2：模态融合（各变量最佳信道，selector={channel_metric}）BPM 相对误差 ===")
    hdr = f"{'段':<5} {'GT':>6}"
    for label, _key, _ in MODAL_FUSION_METHOD_LABELS:
        hdr += f" | {label[:14]:>14} {'err%':>6}"
    print(hdr)
    print("-" * (14 + 24 * len(MODAL_FUSION_METHOD_LABELS)))

    for seg_name in sorted(results.keys()):
        row = results[seg_name]
        if row is None or row.get("bpm_gt") is None:
            continue
        line = f"{seg_name:<5} {row['bpm_gt']:6.2f}"
        for _label, key, _ in MODAL_FUSION_METHOD_LABELS:
            block = row.get(key)
            if block is None:
                line += f" | {'—':>14} {'—':>6}"
            else:
                err = block["bpm_rel_err"] * 100 if block.get("bpm_rel_err") is not None else np.nan
                line += f" | {block['bpm_mean']:14.2f} {err:6.2f}"
        print(line)

    print("-" * (14 + 24 * len(MODAL_FUSION_METHOD_LABELS)))
    line = f"{'All':<5} {'—':>6}"
    for label, key, _ in MODAL_FUSION_METHOD_LABELS:
        stats = _overall_rel_error(results, key)
        line += f" | {'—':>14} {stats['mean_rel_err_pct']:6.2f}"
    print(line)
    print(f"（总幅值未参与融合；信道选择={channel_metric} ({sym})；top2 策略按 {sym} 排序取前二变量）\n")


def run_plan2_validation(
    frames,
    segment_config: Dict[str, dict],
    *,
    filter_params: Optional[FilterParams] = None,
    metric_params: Optional[BreathMetricParams] = None,
    config: Optional[ChFusionConfig] = None,
    plan2_config: Optional[Plan2Config] = None,
    reference_variable: str = "phases",
    complementarity_variables: Optional[Sequence[str]] = None,
    verbose: bool = True,
) -> dict:
    """Plan 2 end-to-end: complementarity windows + modal fusion benchmark."""
    cfg = config or ChFusionConfig()
    fp = filter_params or FilterParams()
    mp = metric_params or BreathMetricParams()
    p2 = plan2_config or Plan2Config()
    variables = [v[0] for v in CS_SIGNAL_VARIABLES]
    comp_vars = list(complementarity_variables or COMPLEMENTARITY_REFERENCE_VARIABLES)

    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]] = {}
    fs = None
    for variable in variables:
        mc, fs = run_multichannel_segment_filtering(
            frames, segment_config, variable=variable, filter_params=fp, verbose=verbose
        )
        multichannel_by_var[variable] = mc

    complementarity_by_reference = collect_complementarity_by_reference(
        multichannel_by_var,
        reference_variables=comp_vars,
        config=cfg,
        metric_params=mp,
        plan2_config=p2,
    )

    primary = reference_variable
    if primary not in complementarity_by_reference and comp_vars:
        primary = comp_vars[0]
    primary_block = complementarity_by_reference.get(primary, {})
    window_records = primary_block.get("window_records", [])
    complementarity_windows = primary_block.get("complementarity_windows", {})

    variable_baselines: Dict[str, Dict[str, Optional[dict]]] = {}
    for variable in variables:
        variable_baselines[variable] = estimate_segment_bpm_methods(
            multichannel_by_var[variable],
            variable=variable,
            config=cfg,
            metric_params=mp,
            methods=("single", "uniform"),
            single_channel_metric=p2.channel_metric,
            verbose=False,
        )
        if verbose:
            stats_s = _overall_rel_error(variable_baselines[variable], "fft_single_max_energy")
            stats_u = _overall_rel_error(variable_baselines[variable], "fft_uniform_fusion")
            print(
                f"✓ [{_variable_display_name(variable)}] Single err {stats_s['mean_rel_err_pct']:.2f}% "
                f"| Uniform err {stats_u['mean_rel_err_pct']:.2f}% "
                f"(selector={p2.channel_metric})"
            )

    modal_benchmark = run_modal_fusion_benchmark(
        multichannel_by_var, config=cfg, metric_params=mp, plan2_config=p2, verbose=verbose
    )

    return {
        "multichannel_by_var": multichannel_by_var,
        "complementarity_by_reference": complementarity_by_reference,
        "complementarity_variables": comp_vars,
        "window_records": window_records,
        "complementarity_windows": complementarity_windows,
        "variable_baselines": variable_baselines,
        "modal_benchmark": modal_benchmark,
        "plan2_config": p2,
        "reference_variable": primary,
        "sampling_rate": fs,
        "segment_config": segment_config,
    }


def print_q_component_summary(method_results: Dict[str, Optional[dict]]) -> None:
    """Print per-segment mean q_valid / q_peak / q_phi / q_c (compact)."""
    print("\n=== 各段 q 子项均值（全信道×全滑窗）===")
    print(f"{'段':<6} {'q_valid':>8} {'q_peak':>8} {'q_phi':>8} {'q_c':>8} {'ρ_peak':>8}")
    print("-" * 50)
    for seg_name in sorted(method_results.keys()):
        row = method_results[seg_name]
        if row is None:
            continue
        qs = row.get("q_summary") or {}
        print(
            f"{seg_name:<6} "
            f"{qs.get('mean_q_valid', float('nan')):8.3f} "
            f"{qs.get('mean_q_peak', float('nan')):8.3f} "
            f"{qs.get('mean_q_phi', float('nan')):8.3f} "
            f"{qs.get('mean_q_c', float('nan')):8.3f} "
            f"{qs.get('mean_peak_snr', float('nan')):8.3f}"
        )
    print("（q_c 为 compact 几何平均；FFT+q_peak 消融仅使用 q_peak 列作为权重）\n")


# Table / plot method registry: (display label, result key, color)
METHOD_LABELS = (
    ("Single", "fft_single_max_energy", "steelblue"),
    ("Uniform", "fft_uniform_fusion", "seagreen"),
    ("FFT+q", "fft_q_fusion", "coral"),
    ("FFT+q_peak", "fft_q_peak_fusion", "mediumpurple"),
)

_METHOD_KEYS = [m[1] for m in METHOD_LABELS]


def summarize_bpm_comparison(
    method_results: Dict[str, Optional[dict]],
) -> Tuple[List[dict], dict]:
    """Build per-segment rows and overall mean relative error ± std for all methods."""
    rows: List[dict] = []
    errs_by_method = {k: [] for k in _METHOD_KEYS}

    for seg_name in sorted(method_results.keys()):
        row = method_results[seg_name]
        if row is None or row.get("bpm_gt") is None:
            continue

        entry: dict = {"segment": seg_name, "bpm_gt": row["bpm_gt"]}
        for label, key, _ in METHOD_LABELS:
            prefix = key.replace("fft_", "").replace("_fusion", "")
            s = row[key]
            entry[f"{prefix}_bpm"] = s["bpm_mean"]
            entry[f"{prefix}_rel_err_pct"] = s["bpm_rel_err"] * 100 if s["bpm_rel_err"] is not None else np.nan
            entry[f"{prefix}_rel_err_std_pct"] = s["bpm_rel_err_std"] * 100
            entry[f"{prefix}_n_windows"] = s["n_windows"]
            if np.isfinite(s["bpm_rel_err"]):
                errs_by_method[key].append(s["bpm_rel_err"])

        rows.append(entry)

    def _overall(errs: List[float]) -> dict:
        if not errs:
            return {"mean_rel_err_pct": np.nan, "std_rel_err_pct": np.nan}
        a = np.asarray(errs, dtype=float)
        return {
            "mean_rel_err_pct": float(np.mean(a) * 100),
            "std_rel_err_pct": float(np.std(a, ddof=1) * 100) if len(a) > 1 else 0.0,
        }

    overall = {k: _overall(errs_by_method[k]) for k in _METHOD_KEYS}
    overall["n_segments"] = len(rows)
    return rows, overall


def _fmt_std_pct(value: float, n_windows: int) -> str:
    if n_windows < 2:
        return "  N/A"
    return f"{value:7.2f}"


def print_bpm_comparison_table(rows: List[dict], overall: dict) -> None:
    """Print BPM relative error table for all registered methods."""
    print("\n=== BPM 相对误差对比（各金属板脚本段）===")
    hdr = f"{'段':<5} {'GT':>6}"
    for label, key, _ in METHOD_LABELS:
        short = label[:8]
        hdr += f" | {short:>8} {'err%':>6} {'±std':>6}"
    print(hdr)
    print("-" * (12 + 22 * len(METHOD_LABELS)))

    for r in rows:
        line = f"{r['segment']:<5} {r['bpm_gt']:6.2f}"
        for label, key, _ in METHOD_LABELS:
            prefix = key.replace("fft_", "").replace("_fusion", "")
            line += (
                f" | {r[f'{prefix}_bpm']:8.2f} "
                f"{r[f'{prefix}_rel_err_pct']:6.2f} "
                f"{_fmt_std_pct(r[f'{prefix}_rel_err_std_pct'], r[f'{prefix}_n_windows'])}"
            )
        print(line)

    print("-" * (12 + 22 * len(METHOD_LABELS)))
    line = f"{'All':<5} {'—':>6}"
    for _label, key, _ in METHOD_LABELS:
        o = overall[key]
        line += f" | {'—':>8} {o['mean_rel_err_pct']:6.2f} {o['std_rel_err_pct']:6.2f}"
    print(line)
    print(
        f"（{overall['n_segments']} 个 breath 段；"
        f"FFT+q={Q_WEIGHT_MODE_LABELS['compact']}；"
        f"FFT+q_peak={Q_WEIGHT_MODE_LABELS['peak_only']}；"
        f"±std=窗级相对误差标准差，1 窗时为 N/A）\n"
    )


def _overall_rel_error(method_results: Dict[str, Optional[dict]], method_key: str) -> dict:
    """Mean segment-level relative BPM error (%) for one method key."""
    errs = []
    for row in method_results.values():
        if row is None or row.get("bpm_gt") is None:
            continue
        block = row.get(method_key)
        if block is None:
            continue
        e = block.get("bpm_rel_err")
        if e is not None and np.isfinite(e):
            errs.append(float(e))
    if not errs:
        return {"mean_rel_err_pct": np.nan, "std_rel_err_pct": np.nan, "n_segments": 0}
    a = np.asarray(errs, dtype=float)
    return {
        "mean_rel_err_pct": float(np.mean(a) * 100),
        "std_rel_err_pct": float(np.std(a, ddof=1) * 100) if len(a) > 1 else 0.0,
        "n_segments": len(a),
    }


def run_chfusion_benchmark(
    frames,
    segment_config: Dict[str, dict],
    *,
    variables: Optional[Sequence[str]] = None,
    filter_params: Optional[FilterParams] = None,
    metric_params: Optional[BreathMetricParams] = None,
    config: Optional[ChFusionConfig] = None,
    verbose: bool = True,
) -> dict:
    """Benchmark 4 CS variables × 5 methods (Single / Uniform / FFT+q_*).

    See ``docs/chfusion_q_energy_peak.md``. Returns ``part2``, ``leaderboard``.
    """
    cfg = config or ChFusionConfig()
    mp = metric_params or BreathMetricParams()
    fp = filter_params or FilterParams()
    var_list = list(variables or [v[0] for v in CS_SIGNAL_VARIABLES])
    fusion_methods = ("single", "uniform", "q_energy", "q_peak", "q_energy_peak")

    part2: Dict[str, dict] = {}

    for variable in var_list:
        mc, fs = run_multichannel_segment_filtering(
            frames, segment_config, variable=variable, filter_params=fp, verbose=verbose
        )
        r2 = estimate_segment_bpm_methods(
            mc,
            variable=variable,
            config=cfg,
            metric_params=mp,
            methods=fusion_methods,
        )
        part2[variable] = {"results": r2, "sampling_rate": fs}

    leaderboard = build_benchmark_leaderboard(part2)
    return {
        "variables": var_list,
        "part2": part2,
        "leaderboard": leaderboard,
        "segment_config": segment_config,
        "methods": fusion_methods,
    }


def build_benchmark_leaderboard(part2: dict) -> List[dict]:
    """Rank all (variable × method) combos by mean relative BPM error."""
    rows: List[dict] = []

    for variable, block in part2.items():
        for label, key, _ in FUSION_METHOD_LABELS:
            stats = _overall_rel_error(block["results"], key)
            rows.append(
                {
                    "part": 2,
                    "variable": variable,
                    "variable_label": _variable_display_name(variable),
                    "method": label,
                    "method_key": key,
                    **stats,
                }
            )

    rows = [r for r in rows if np.isfinite(r["mean_rel_err_pct"])]
    rows.sort(key=lambda r: r["mean_rel_err_pct"])
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def print_part1_variable_table(part1: dict) -> None:
    """Part 1: compare four variables using Single (max-energy) FFT only."""
    print("\n=== Part 1：变量对比（Single / 最大能量比单信道 FFT）===")
    print(f"{'变量':<22} {'mean err%':>10} {'±std%':>8} {'n_seg':>6}")
    print("-" * 50)
    rows = []
    for variable, block in part1.items():
        stats = _overall_rel_error(block["results"], "fft_single_max_energy")
        rows.append((variable, stats))
    rows.sort(key=lambda x: x[1]["mean_rel_err_pct"])
    for variable, stats in rows:
        print(
            f"{_variable_display_name(variable):<22} "
            f"{stats['mean_rel_err_pct']:10.2f} "
            f"{stats['std_rel_err_pct']:8.2f} "
            f"{stats['n_segments']:6d}"
        )
    print("（误差为各 breath 段相对 BPM 误差的均值；phase 变量滤波前已 unwrap）\n")


def print_part2_method_tables(part2: dict) -> None:
    """Part 2: per variable, compare Single / Uniform / FFT+q_* fusion."""
    print("\n=== 方法对比（Single / Uniform / FFT+q_energy / FFT+q_peak / FFT+q_energy_peak）===")
    for variable, block in part2.items():
        print(f"\n--- {_variable_display_name(variable)} ({variable}) ---")
        print(f"{'方法':<12} {'mean err%':>10} {'±std%':>8} {'n_seg':>6}")
        print("-" * 40)
        for label, key, _ in FUSION_METHOD_LABELS:
            stats = _overall_rel_error(block["results"], key)
            print(
                f"{label:<12} {stats['mean_rel_err_pct']:10.2f} "
                f"{stats['std_rel_err_pct']:8.2f} {stats['n_segments']:6d}"
            )
    print()


def print_benchmark_leaderboard(leaderboard: List[dict], top_n: Optional[int] = None) -> None:
    """Print ranked table of all variable×method combinations (Part 2 matrix)."""
    ranked = sorted(leaderboard, key=lambda r: r.get("rank", 9999))
    if top_n is not None:
        ranked = ranked[:top_n]
    print("\n=== 总排行榜：变量 × 方法 BPM 估计性能（按 mean err% 升序）===")
    print(f"{'#':>3} {'变量':<18} {'方法':<12} {'err%':>8} {'±std%':>8}")
    print("-" * 54)
    for r in ranked:
        print(
            f"{r['rank']:3d} {r['variable_label']:<18} "
            f"{r['method']:<12} {r['mean_rel_err_pct']:8.2f} {r['std_rel_err_pct']:8.2f}"
        )
    if ranked:
        best = ranked[0]
        print(
            f"\n★ 当前最优：{best['variable_label']} + {best['method']} "
            f"→ mean err {best['mean_rel_err_pct']:.2f}%\n"
        )


def collect_window_signed_errors(
    method_results: Dict[str, Optional[dict]],
    method_labels: Sequence[Tuple[str, str, str]] = FUSION_METHOD_LABELS,
) -> List[dict]:
    """Collect per-window signed BPM errors (estimated − GT) for violin plots."""
    records: List[dict] = []
    for seg_name in sorted(method_results.keys()):
        row = method_results[seg_name]
        if row is None or row.get("bpm_gt") is None:
            continue
        bpm_gt = float(row["bpm_gt"])
        for label, key, _color in method_labels:
            if key not in row:
                continue
            block = row[key]
            signed = block.get("bpm_signed_err_per_window")
            if signed is None:
                bpm_wins = block["bpm_per_window"]
                signed = np.array(
                    [b - bpm_gt if np.isfinite(b) else np.nan for b in bpm_wins], dtype=float
                )
            signed = np.asarray(signed, dtype=float)
            signed = signed[np.isfinite(signed)]
            records.append(
                {"segment": seg_name, "method": label, "bpm_gt": bpm_gt, "signed_errors": signed}
            )
    return records


# ---------------------------------------------------------------------------
# Overview plotting: full 4 variables × N methods matrix (see docs/chfusion_q_energy_peak.md)
# ---------------------------------------------------------------------------
# Part 1 violins compare variables (Single only); Part 2 violins compare methods
# per variable (4 separate figures). The functions below add aggregate views:
#
#   collect_part2_variable_method_errors  → flat records for all 16 combos
#   _part2_matrix_stats                   → mean/std matrices for bars & heatmap
#   plot_overview_matrix_bars             → grouped bar chart (leaderboard view)
#   plot_overview_matrix_heatmap          → colour matrix of mean rel error
#   plot_overview_violins_by_method       → Part 1 extended to 4 methods (N×1 stack)
#   plot_overview_violins_by_variable     → Part 2 merged into one N×1 figure
#
# Called from plot_benchmark_violins() after Part 1/2 individual figures.
# All benchmark figures are saved as vector PDF (CHFUSION_FIGURE_FORMAT).

# Benchmark figure output format (vector PDF for publication / LaTeX)
CHFUSION_FIGURE_FORMAT = "pdf"
CHFUSION_FIGURE_EXT = ".pdf"


def _chfusion_figure_name(stem: str) -> str:
    """Return benchmark figure filename with the configured extension."""
    return f"{stem}{CHFUSION_FIGURE_EXT}"


def _save_chfusion_figure(fig, path: Path, *, bbox_inches: Optional[str] = None) -> Path:
    """Save a matplotlib figure as PDF (``CHFUSION_FIGURE_FORMAT``)."""
    kwargs: Dict[str, Any] = {"format": CHFUSION_FIGURE_FORMAT}
    if bbox_inches is not None:
        kwargs["bbox_inches"] = bbox_inches
    fig.savefig(path, **kwargs)
    return path


def _running_in_ipython() -> bool:
    try:
        from IPython import get_ipython

        return get_ipython() is not None
    except ImportError:
        return False


def _finalize_chfusion_figure(
    fig,
    *,
    show: bool,
    save_path: Optional[Path] = None,
    bbox_inches: Optional[str] = None,
) -> None:
    """Save and/or show once, then close (avoid duplicate display in Interactive)."""
    import matplotlib.pyplot as plt

    saved = False
    if save_path is not None:
        _save_chfusion_figure(fig, save_path, bbox_inches=bbox_inches)
        saved = True
    if show:
        # VS Code / Jupyter Interactive often embeds a preview on savefig; skip the
        # redundant plt.show() that makes the same figure appear twice.
        if not (saved and _running_in_ipython()):
            plt.show()
    plt.close(fig)


def _signed_errors_from_method_block(block: dict, bpm_gt: float) -> np.ndarray:
    """Window-level signed BPM errors (estimated − GT) from one method result block."""
    signed = block.get("bpm_signed_err_per_window")
    if signed is None:
        signed = np.array(
            [b - bpm_gt if np.isfinite(b) else np.nan for b in block["bpm_per_window"]],
            dtype=float,
        )
    signed = np.asarray(signed, dtype=float)
    return signed[np.isfinite(signed)]


def collect_part1_variable_errors(part1: dict) -> List[dict]:
    """Part-1: signed errors per segment × variable (Single method only)."""
    records: List[dict] = []
    for variable, block in part1.items():
        results = block["results"]
        var_label = _variable_display_name(variable)
        for seg_name in sorted(results.keys()):
            row = results[seg_name]
            if row is None or row.get("bpm_gt") is None:
                continue
            bpm_gt = float(row["bpm_gt"])
            single = row.get("fft_single_max_energy")
            if single is None:
                continue
            signed = _signed_errors_from_method_block(single, bpm_gt)
            records.append(
                {
                    "segment": seg_name,
                    "variable": variable,
                    "variable_label": var_label,
                    "bpm_gt": bpm_gt,
                    "signed_errors": signed,
                }
            )
    return records


def collect_part2_variable_method_errors(part2: dict) -> List[dict]:
    """Collect window-level signed errors for every segment × variable × method.

    Each record has keys: segment, variable, variable_label, method, method_key,
    bpm_gt, signed_errors. Used by overview violin plots (4×4 matrix).
    """
    records: List[dict] = []
    for variable, block in part2.items():
        results = block["results"]
        var_label = _variable_plot_label(variable)
        for seg_name in sorted(results.keys()):
            row = results[seg_name]
            if row is None or row.get("bpm_gt") is None:
                continue
            bpm_gt = float(row["bpm_gt"])
            for label, key, _color in FUSION_METHOD_LABELS:
                method_block = row.get(key)
                if method_block is None:
                    continue
                signed = _signed_errors_from_method_block(method_block, bpm_gt)
                records.append(
                    {
                        "segment": seg_name,
                        "variable": variable,
                        "variable_label": var_label,
                        "method": label,
                        "method_key": key,
                        "bpm_gt": bpm_gt,
                        "signed_errors": signed,
                    }
                )
    return records


def plot_bpm_error_violins(
    method_results: Dict[str, Optional[dict]],
    *,
    method_labels: Sequence[Tuple[str, str, str]] = FUSION_METHOD_LABELS,
    figures_dir=None,
    filename: str = "",
    title: Optional[str] = None,
    show: bool = True,
    save: bool = True,
):
    """Violin plot of signed window-level BPM error; y=0 is ground truth."""
    import matplotlib.pyplot as plt

    if not filename:
        filename = _chfusion_figure_name("chfusion_fft_q_bpm_error_violins")

    records = collect_window_signed_errors(method_results, method_labels)
    if not records:
        print("⚠️  无可用误差数据，跳过小提琴图")
        return None

    segments = sorted({r["segment"] for r in records})
    gt_by_seg = {r["segment"]: r["bpm_gt"] for r in records}
    methods = [m[0] for m in method_labels]
    colors = {m[0]: m[2] for m in method_labels}

    n_seg = len(segments)
    n_methods = len(methods)
    group_gap = 1.0
    group_width = 0.8
    violin_width = group_width / n_methods

    fig, ax = plt.subplots(figsize=(max(12, n_seg * 2.0), 5.5))

    for i, seg in enumerate(segments):
        group_center = i * group_gap
        for j, method in enumerate(methods):
            rec = next(
                (r for r in records if r["segment"] == seg and r["method"] == method),
                None,
            )
            if rec is None:
                continue
            errors = rec["signed_errors"]
            pos = group_center + (j - (n_methods - 1) / 2) * violin_width
            color = colors[method]

            if len(errors) >= 2:
                parts = ax.violinplot(
                    [errors],
                    positions=[pos],
                    widths=violin_width * 0.85,
                    showmeans=True,
                    showmedians=True,
                    showextrema=False,
                )
                for body in parts["bodies"]:
                    body.set_facecolor(color)
                    body.set_edgecolor("black")
                    body.set_alpha(0.65)
                parts["cmeans"].set_color("black")
                parts["cmeans"].set_linewidth(1.2)
                parts["cmedians"].set_color("white")
                parts["cmedians"].set_linewidth(1.5)
            elif len(errors) == 1:
                ax.scatter([pos], errors, color=color, edgecolors="black", s=40, zorder=4)

    ax.axhline(0.0, color="black", linestyle="--", linewidth=1.2, alpha=0.75)
    ax.set_xticks([i * group_gap for i in range(n_seg)])
    ax.set_xticklabels([f"{seg}\nGT={gt_by_seg[seg]:.2f}" for seg in segments])
    ax.set_ylabel("BPM error (estimated - GT)")
    ax.set_title(title or "Window-level BPM error by segment")
    ax.grid(True, axis="y", alpha=0.25)

    legend_handles = _violin_legend_with_stats([
        plt.Line2D([0], [0], color=colors[m], lw=6, alpha=0.65, label=m) for m in methods
    ])
    ax.legend(handles=legend_handles, loc="upper right", fontsize=7)
    plt.tight_layout()

    fig_path = None
    if save and figures_dir is not None:
        fig_path = Path(figures_dir) / filename
        _save_chfusion_figure(fig, fig_path)
        print(f"✓ 小提琴图已保存: {fig_path}")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig


# Variable colors for Part-1 violin (same order as CS_SIGNAL_VARIABLES)
PART1_VARIABLE_COLORS = {
    "amplitudes": "coral",
    "remote_amplitudes": "steelblue",
    "local_amplitudes": "seagreen",
    "phases": "mediumpurple",
}


def _violin_legend_with_stats(method_handles: List) -> List:
    """Append mean / median / GT reference entries to a violin plot legend."""
    import matplotlib.pyplot as plt

    stat_handles = [
        plt.Line2D([0], [0], color="black", lw=1.5, label="Mean (window BPM error)"),
        plt.Line2D(
            [0], [0], color="white", lw=2, markeredgecolor="black",
            markeredgewidth=0.8, label="Median (window BPM error)",
        ),
        plt.Line2D([0], [0], color="black", lw=1.2, ls="--", label="Ground truth (y=0)"),
    ]
    return list(method_handles) + stat_handles


def _draw_grouped_violins_on_ax(
    ax,
    records: List[dict],
    *,
    segments: Sequence[str],
    group_ids: Sequence[str],
    group_field: str,
    colors: Dict[str, str],
    gt_by_seg: Dict[str, float],
    title: Optional[str] = None,
    show_ylabel: bool = True,
) -> None:
    """Draw segment-grouped violins on an existing axes.

    Layout: one x-axis group per script segment; within each group, one violin
    per entry in ``group_ids`` (either 4 variables or 4 methods). Shared by
    Part 1/2 and overview multi-panel figures.
    """
    n_groups = len(group_ids)
    group_gap = 1.0
    group_width = 0.85
    violin_width = group_width / max(n_groups, 1)

    for i, seg in enumerate(segments):
        group_center = i * group_gap
        for j, gid in enumerate(group_ids):
            rec = next(
                (r for r in records if r["segment"] == seg and r[group_field] == gid),
                None,
            )
            if rec is None:
                continue
            errors = rec["signed_errors"]
            pos = group_center + (j - (n_groups - 1) / 2) * violin_width
            color = colors.get(gid, "gray")

            if len(errors) >= 2:
                parts = ax.violinplot(
                    [errors],
                    positions=[pos],
                    widths=violin_width * 0.85,
                    showmeans=True,
                    showmedians=True,
                    showextrema=False,
                )
                for body in parts["bodies"]:
                    body.set_facecolor(color)
                    body.set_edgecolor("black")
                    body.set_alpha(0.65)
                parts["cmeans"].set_color("black")
                parts["cmeans"].set_linewidth(1.2)
                parts["cmedians"].set_color("white")
                parts["cmedians"].set_linewidth(1.5)
            elif len(errors) == 1:
                ax.scatter([pos], errors, color=color, edgecolors="black", s=40, zorder=4)

    ax.axhline(0.0, color="black", linestyle="--", linewidth=1.2, alpha=0.75)
    ax.set_xticks([i * group_gap for i in range(len(segments))])
    ax.set_xticklabels([f"{seg}\nGT={gt_by_seg[seg]:.2f}" for seg in segments], fontsize=8)
    if show_ylabel:
        ax.set_ylabel("BPM error (estimated - GT)")
    if title:
        ax.set_title(title, fontsize=10)
    ax.grid(True, axis="y", alpha=0.25)


def _part2_matrix_stats(part2: dict) -> Tuple[List[str], np.ndarray, np.ndarray]:
    """Aggregate Part-2 results into 4×4 mean/std matrices (%).

    Rows follow ``CS_SIGNAL_VARIABLES`` order; columns follow ``FUSION_METHOD_LABELS``.
    Mean = average segment-level relative BPM error; std = std of those segment errors.
    """
    variables = [v[0] for v in CS_SIGNAL_VARIABLES if v[0] in part2]
    n_var, n_meth = len(variables), len(FUSION_METHOD_LABELS)
    means = np.full((n_var, n_meth), np.nan)
    stds = np.full((n_var, n_meth), np.nan)
    for i, variable in enumerate(variables):
        for j, (_label, key, _color) in enumerate(FUSION_METHOD_LABELS):
            stats = _overall_rel_error(part2[variable]["results"], key)
            means[i, j] = stats["mean_rel_err_pct"]
            stds[i, j] = stats["std_rel_err_pct"]
    return variables, means, stds


def plot_overview_matrix_bars(
    benchmark: dict,
    *,
    figures_dir=None,
    filename: str = "",
    show: bool = True,
    save: bool = True,
):
    """Grouped bar chart summarising all 16 variable×method combos.

    X-axis: four CS observables. Five bars = Single / Uniform / FFT+q_* fusion.
    Height = mean segment relative BPM error (%); error bars = ±std across segments.
    """
    import matplotlib.pyplot as plt

    if not filename:
        filename = _chfusion_figure_name("chfusion_overview_4x3_mean_error_bars")

    part2 = benchmark["part2"]
    variables, means, stds = _part2_matrix_stats(part2)
    if not variables:
        print("⚠️  无 Part-2 数据，跳过 4×3 柱状图")
        return None

    var_labels = [_variable_plot_label(v) for v in variables]
    n_var = len(variables)
    n_meth = len(FUSION_METHOD_LABELS)
    x = np.arange(n_var)
    bar_width = 0.15
    offsets = (np.arange(n_meth) - (n_meth - 1) / 2) * bar_width

    fig, ax = plt.subplots(figsize=(max(10, n_var * 2.5), 5.5))
    for j, (label, _key, color) in enumerate(FUSION_METHOD_LABELS):
        ax.bar(
            x + offsets[j],
            means[:, j],
            bar_width,
            yerr=stds[:, j],
            capsize=3,
            label=label,
            color=color,
            edgecolor="black",
            alpha=0.85,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(var_labels, rotation=15, ha="right")
    ax.set_ylabel("Mean relative BPM error (%)")
    ax.set_title("Overview: 4 variables × 5 methods (segment mean ± window std)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, axis="y", alpha=0.25)
    plt.tight_layout()

    if save and figures_dir is not None:
        fig_path = Path(figures_dir) / filename
        _save_chfusion_figure(fig, fig_path)
        print(f"✓ 4×3 柱状图已保存: {fig_path}")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig


def plot_overview_matrix_heatmap(
    benchmark: dict,
    *,
    figures_dir=None,
    filename: str = "",
    show: bool = True,
    save: bool = True,
):
    """Heatmap of mean relative BPM error (%) for the 4×4 benchmark matrix.

    Darker/warmer cells = higher error. Cell text shows numeric mean err%.
    Same underlying stats as ``plot_overview_matrix_bars``.
    """
    import matplotlib.pyplot as plt

    if not filename:
        filename = _chfusion_figure_name("chfusion_overview_4x3_heatmap")

    part2 = benchmark["part2"]
    variables, means, _stds = _part2_matrix_stats(part2)
    if not variables:
        print("⚠️  无 Part-2 数据，跳过 4×3 热力图")
        return None

    var_labels = [_variable_plot_label(v) for v in variables]
    meth_labels = [m[0] for m in FUSION_METHOD_LABELS]

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    im = ax.imshow(means, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(np.arange(len(meth_labels)))
    ax.set_yticks(np.arange(len(var_labels)))
    ax.set_xticklabels(meth_labels)
    ax.set_yticklabels(var_labels)
    ax.set_title("Mean relative BPM error (%) — 4 variables × 5 methods")

    for i in range(means.shape[0]):
        for j in range(means.shape[1]):
            val = means[i, j]
            if np.isfinite(val):
                ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=9, color="black")

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Mean rel. error (%)")
    plt.tight_layout()

    if save and figures_dir is not None:
        fig_path = Path(figures_dir) / filename
        _save_chfusion_figure(fig, fig_path)
        print(f"✓ 4×3 热力图已保存: {fig_path}")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig


def plot_overview_violins_by_method(
    benchmark: dict,
    *,
    figures_dir=None,
    filename: str = "",
    show: bool = True,
    save: bool = True,
):
    """N×1 violin panels: variable comparison under each fusion method (vertical stack).

    Extends Part 1 (which only shows Single) to Uniform, FFT+q_peak, FFT+q_energy_peak.
    Each panel layout matches ``plot_part1_variable_violins`` (4 colours per segment).
    """
    import matplotlib.pyplot as plt

    if not filename:
        filename = _chfusion_figure_name("chfusion_overview_4x3_violins_by_method")

    records = collect_part2_variable_method_errors(benchmark["part2"])
    if not records:
        print("⚠️  无 Part-2 误差数据，跳过按方法分组小提琴图")
        return None

    segments = sorted({r["segment"] for r in records})
    gt_by_seg = {r["segment"]: r["bpm_gt"] for r in records}
    variables = [v[0] for v in CS_SIGNAL_VARIABLES if any(r["variable"] == v[0] for r in records)]
    var_colors = {v: PART1_VARIABLE_COLORS.get(v, "gray") for v in variables}
    var_legend_labels = {v: _variable_plot_label(v) for v in variables}

    n_methods = len(FUSION_METHOD_LABELS)
    panel_h = 5.5
    fig, axes = plt.subplots(
        n_methods,
        1,
        figsize=(max(12, len(segments) * 2.2), panel_h * n_methods),
        sharey=True,
    )
    axes_flat = np.atleast_1d(axes).flatten()

    for ax, (method_label, _key, _color) in zip(axes_flat, FUSION_METHOD_LABELS):
        subset = [r for r in records if r["method"] == method_label]
        _draw_grouped_violins_on_ax(
            ax,
            subset,
            segments=segments,
            group_ids=variables,
            group_field="variable",
            colors=var_colors,
            gt_by_seg=gt_by_seg,
            title=f"Method: {method_label}",
            show_ylabel=(ax is axes_flat[0]),
        )

    legend_handles = _violin_legend_with_stats([
        plt.Line2D(
            [0], [0],
            color=var_colors[v],
            lw=6, alpha=0.65,
            label=var_legend_labels[v],
        )
        for v in variables
    ])
    fig.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.01),
        ncol=min(4, len(variables) + 3),
        fontsize=7,
    )
    fig.suptitle(
        "Overview: variable comparison per method (window-level signed BPM error)",
        y=0.995,
        fontsize=11,
    )
    plt.tight_layout(rect=[0, 0.04, 1, 0.98])

    if save and figures_dir is not None:
        fig_path = Path(figures_dir) / filename
        _save_chfusion_figure(fig, fig_path, bbox_inches="tight")
        print(f"✓ 按方法分组小提琴图已保存: {fig_path}")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig


def plot_overview_violins_by_variable(
    benchmark: dict,
    *,
    figures_dir=None,
    filename: str = "",
    show: bool = True,
    save: bool = True,
):
    """N×1 violin panels: method comparison for each CS observable (vertical stack).

    Merges the four Part-2 per-variable figures into one overview page.
    Each panel layout matches ``plot_bpm_error_violins`` (3 colours per segment).
    """
    import matplotlib.pyplot as plt

    if not filename:
        filename = _chfusion_figure_name("chfusion_overview_4x3_violins_by_variable")

    records = collect_part2_variable_method_errors(benchmark["part2"])
    if not records:
        print("⚠️  无 Part-2 误差数据，跳过按变量分组小提琴图")
        return None

    segments = sorted({r["segment"] for r in records})
    gt_by_seg = {r["segment"]: r["bpm_gt"] for r in records}
    variables = [v[0] for v in CS_SIGNAL_VARIABLES if any(r["variable"] == v[0] for r in records)]
    method_labels = [m[0] for m in FUSION_METHOD_LABELS]
    method_colors = {m[0]: m[2] for m in FUSION_METHOD_LABELS}

    n_var = len(variables)
    panel_h = 5.5
    fig, axes = plt.subplots(
        n_var,
        1,
        figsize=(max(12, len(segments) * 2.2), panel_h * n_var),
        sharey=True,
    )
    axes_flat = np.atleast_1d(axes).flatten()

    for ax, variable in zip(axes_flat, variables):
        subset = [r for r in records if r["variable"] == variable]
        _draw_grouped_violins_on_ax(
            ax,
            subset,
            segments=segments,
            group_ids=method_labels,
            group_field="method",
            colors=method_colors,
            gt_by_seg=gt_by_seg,
            title=_variable_plot_label(variable),
            show_ylabel=(ax is axes_flat[0]),
        )

    legend_handles = _violin_legend_with_stats([
        plt.Line2D([0], [0], color=method_colors[m], lw=6, alpha=0.65, label=m)
        for m in method_labels
    ])
    fig.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.01),
        ncol=len(method_labels) + 3,
        fontsize=7,
    )
    fig.suptitle(
        "Overview: method comparison per variable (window-level signed BPM error)",
        y=0.995,
        fontsize=11,
    )
    plt.tight_layout(rect=[0, 0.04, 1, 0.98])

    if save and figures_dir is not None:
        fig_path = Path(figures_dir) / filename
        _save_chfusion_figure(fig, fig_path, bbox_inches="tight")
        print(f"✓ 按变量分组小提琴图已保存: {fig_path}")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig


def plot_part1_variable_violins(
    part1: dict,
    *,
    figures_dir=None,
    filename: str = "",
    show: bool = True,
    save: bool = True,
):
    """Part-1 violin: per segment, compare four variables (Single method). y=0 is GT."""
    import matplotlib.pyplot as plt

    if not filename:
        filename = _chfusion_figure_name("chfusion_part1_variable_violins")

    records = collect_part1_variable_errors(part1)
    if not records:
        print("⚠️  Part-1 无可用误差数据，跳过小提琴图")
        return None

    segments = sorted({r["segment"] for r in records})
    gt_by_seg = {r["segment"]: r["bpm_gt"] for r in records}
    variables = [v[0] for v in CS_SIGNAL_VARIABLES if any(r["variable"] == v[0] for r in records)]

    n_seg = len(segments)
    n_var = len(variables)
    group_gap = 1.0
    group_width = 0.85
    violin_width = group_width / max(n_var, 1)

    fig, ax = plt.subplots(figsize=(max(12, n_seg * 2.0), 5.5))

    for i, seg in enumerate(segments):
        group_center = i * group_gap
        for j, variable in enumerate(variables):
            rec = next(
                (r for r in records if r["segment"] == seg and r["variable"] == variable),
                None,
            )
            if rec is None:
                continue
            errors = rec["signed_errors"]
            pos = group_center + (j - (n_var - 1) / 2) * violin_width
            color = PART1_VARIABLE_COLORS.get(variable, "gray")

            if len(errors) >= 2:
                parts = ax.violinplot(
                    [errors],
                    positions=[pos],
                    widths=violin_width * 0.85,
                    showmeans=True,
                    showmedians=True,
                    showextrema=False,
                )
                for body in parts["bodies"]:
                    body.set_facecolor(color)
                    body.set_edgecolor("black")
                    body.set_alpha(0.65)
                parts["cmeans"].set_color("black")
                parts["cmedians"].set_color("white")
            elif len(errors) == 1:
                ax.scatter([pos], errors, color=color, edgecolors="black", s=40, zorder=4)

    ax.axhline(0.0, color="black", linestyle="--", linewidth=1.2, alpha=0.75)
    ax.set_xticks([i * group_gap for i in range(n_seg)])
    ax.set_xticklabels([f"{seg}\nGT={gt_by_seg[seg]:.2f}" for seg in segments])
    ax.set_ylabel("BPM error (estimated - GT)")
    ax.set_title("Part 1: variable comparison (Single / max-energy channel)")
    ax.grid(True, axis="y", alpha=0.25)

    legend_handles = _violin_legend_with_stats([
        plt.Line2D(
            [0], [0],
            color=PART1_VARIABLE_COLORS.get(v, "gray"),
            lw=6, alpha=0.65,
            label=_variable_plot_label(v),
        )
        for v in variables
    ])
    ax.legend(handles=legend_handles, loc="upper right", fontsize=7)
    plt.tight_layout()

    fig_path = None
    if save and figures_dir is not None:
        fig_path = Path(figures_dir) / filename
        _save_chfusion_figure(fig, fig_path)
        print(f"✓ Part-1 小提琴图已保存: {fig_path}")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig


def plot_benchmark_violins(
    benchmark: dict,
    *,
    figures_dir=None,
    show: bool = True,
    save: bool = True,
) -> List[Path]:
    """Generate benchmark violin/overview figures (5 methods × 4 variables).

    Per-variable method violins + overview bars / heatmap / matrix violins.
    """
    saved: List[Path] = []

    for variable, block in benchmark["part2"].items():
        slug = variable.replace("_", "-")
        part2_name = _chfusion_figure_name(f"chfusion_part2_{slug}_violins")
        plot_bpm_error_violins(
            block["results"],
            method_labels=FUSION_METHOD_LABELS,
            figures_dir=figures_dir,
            filename=part2_name,
            title=f"{_variable_plot_label(variable)} — fusion methods",
            show=show,
            save=save,
        )
        if save and figures_dir is not None:
            saved.append(Path(figures_dir) / part2_name)

    overview_specs = [
        ("chfusion_overview_4x3_mean_error_bars", plot_overview_matrix_bars),
        ("chfusion_overview_4x3_heatmap", plot_overview_matrix_heatmap),
        ("chfusion_overview_4x3_violins_by_method", plot_overview_violins_by_method),
        ("chfusion_overview_4x3_violins_by_variable", plot_overview_violins_by_variable),
    ]
    for stem, plot_fn in overview_specs:
        fname = _chfusion_figure_name(stem)
        plot_fn(benchmark, figures_dir=figures_dir, filename=fname, show=show, save=save)
        if save and figures_dir is not None:
            saved.append(Path(figures_dir) / fname)

    if saved:
        print("\n=== 图表输出 ===")
        for path in saved:
            print(f"  {path}")
        if show:
            print("（窗口已弹出，关闭当前图后继续下一张）")

    return saved
