"""PCA / SVD 多信道呼吸波形提取。

从多个信道（72 道 BLE CS tone）的滤波信号中，利用 PCA 或 SVD
提取所有信道的共同变化模式（第一主成分 / 第一左奇异向量），作为呼吸波形。

参考
----
WiFi CSI 呼吸感知文献中 PCA/SVD 是标准的降噪+信号提取手段。
详见 ``docs/chFusion_pca_svd_plan.md``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# 类型定义
# ---------------------------------------------------------------------------

PcaSvdMethod = Literal["pca", "svd_real", "svd_complex"]
"""PCA: 实矩阵特征分解; SVD_real: 实矩阵 SVD; SVD_complex: 复矩阵 SVD"""

NormalizeMethod = Literal["none", "zscore", "minmax"]
ChannelWeightMode = Literal["uniform", "energy_ratio"]
"""信道间加权：uniform=仅 z-score；energy_ratio=按呼吸能量比 η 加权列。"""
SignalKey = Literal["highpass_filtered", "bandpass_filtered"]
ModalWeightMode = Literal["equal", "energy_ratio", "top2_equal"]
"""标准化策略:
- none:   不标准化（注意：幅值大的信道会主导结果）
- zscore: 按列 (x - μ) / σ（推荐，消除信道间幅值差异）
- minmax: 按列 (x - min) / (max - min)
"""

PcaSvdVariable = Literal[
    "amplitudes",
    "remote_amplitudes",
    "local_amplitudes",
    "phases",
    "complex",
    "stacked",
]
"""变量标识:
- amplitudes / remote_amplitudes / local_amplitudes: 对应 CS_SIGNAL_VARIABLES
- phases: 总相位
- complex: 总幅值 + j·总相位 复矩阵 SVD
- stacked: 三种幅值堆叠
"""


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class PcaSvdConfig:
    """PCA / SVD 波形提取配置。

    Parameters
    ----------
    method : PcaSvdMethod
        ``pca``: 实矩阵 PCA（协方差特征分解）。
        ``svd_real``: 实矩阵 SVD。
        ``svd_complex``: 复矩阵 SVD（仅对 complex 变量有效）。
    normalize : NormalizeMethod
        每列（信道）标准化策略，默认 ``zscore``。
    min_channels : int
        最小有效信道数，低于此数跳过。
    min_variance_ratio : float
        PC1 方差占比阈值，低于此值发出警告（呼吸可能不主导）。
    eps : float
        数值稳定小量。
    channel_weight : ChannelWeightMode
        信道维加权；``energy_ratio`` 时用 ``signal_key`` 切片算 η 后乘到列上。
    signal_key : SignalKey
        构造数据矩阵时使用的滤波键，默认 ``highpass_filtered``。
    breath_freq_low, breath_freq_high : float
        呼吸频带 [Hz]，用于 η 与 BPM 谱峰搜索。
    total_freq_low, total_freq_high : float
        η 分母频带 [Hz]。
    """

    method: PcaSvdMethod = "pca"
    normalize: NormalizeMethod = "zscore"
    min_channels: int = 4
    min_variance_ratio: float = 0.10
    eps: float = 1e-12
    channel_weight: ChannelWeightMode = "uniform"
    signal_key: SignalKey = "highpass_filtered"
    breath_freq_low: float = 0.1
    breath_freq_high: float = 0.35
    total_freq_low: float = 0.05
    total_freq_high: float = 0.8


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _normalize_matrix(
    X: np.ndarray,
    method: NormalizeMethod,
    eps: float = 1e-12,
) -> np.ndarray:
    """按列标准化 M×N 矩阵。

    Parameters
    ----------
    X : ndarray, shape (M, N)
    method : NormalizeMethod
    eps : float

    Returns
    -------
    ndarray, shape (M, N)
    """
    if method == "none":
        return X.astype(float)
    Xf = X.astype(float)
    if Xf.shape[1] == 0:
        return Xf
    if method == "zscore":
        mu = np.mean(Xf, axis=0, keepdims=True)
        sigma = np.std(Xf, axis=0, ddof=1, keepdims=True)
        sigma[sigma < eps] = 1.0
        return (Xf - mu) / sigma
    if method == "minmax":
        xmin = np.min(Xf, axis=0, keepdims=True)
        xmax = np.max(Xf, axis=0, keepdims=True)
        denom = xmax - xmin
        denom[denom < eps] = 1.0
        return (Xf - xmin) / denom
    return Xf


def _check_and_warn(
    X: np.ndarray,
    cfg: PcaSvdConfig,
    seg_name: str,
) -> bool:
    """检查数据矩阵的有效性，无效或信道不足返回 False 并打印警告。"""
    if X is None or X.size == 0 or X.shape[1] < cfg.min_channels:
        print(
            f"  ⚠ [{seg_name}] 信道数={X.shape[1] if X is not None else 0} < "
            f"{cfg.min_channels}，跳过 PCA/SVD"
        )
        return False
    if not np.all(np.isfinite(X)):
        print(f"  ⚠ [{seg_name}] 数据含 NaN/inf，跳过")
        return False
    return True


def _channel_energy_ratio(
    signal_seg: np.ndarray,
    fs: float,
    cfg: PcaSvdConfig,
) -> float:
    """单信道呼吸带能量 / 全频段能量（与 chfusion ``_energy_ratio`` 一致）。"""
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


def _apply_channel_weights(Z: np.ndarray, channel_weights: Optional[np.ndarray], eps: float) -> np.ndarray:
    """列加权：sqrt(w) 缩放，保持与均匀 PCA 可比的总尺度。"""
    if channel_weights is None or Z.shape[1] == 0:
        return Z
    w = np.maximum(np.asarray(channel_weights, dtype=float), 0.0)
    if w.shape[0] != Z.shape[1]:
        return Z
    s = float(np.sum(w))
    if s <= eps:
        return Z
    w = w / s * Z.shape[1]
    return Z * np.sqrt(w)[np.newaxis, :]


def build_channel_data_matrix(
    ch_map: Dict[Any, Dict[str, Any]],
    variable: str,
    channels: List[Any],
    st: int,
    end: int,
    signal_key: SignalKey = "highpass_filtered",
) -> Tuple[np.ndarray, List[Any]]:
    """构造单变量 M×N 矩阵（每列一道 ``signal_key`` 切片）。"""
    cols: List[np.ndarray] = []
    used: List[Any] = []
    m = end - st
    for ch in channels:
        proc = ch_map.get(ch)
        if proc is None:
            continue
        sig = proc[variable].get(signal_key)
        if sig is None or len(sig) < end:
            continue
        col = sig[st:end].astype(float)
        if len(col) == m:
            cols.append(col)
            used.append(ch)
    if not cols:
        return np.empty((m, 0)), []
    return np.column_stack(cols), used


def compute_channel_energy_weights(
    ch_map: Dict[Any, Dict[str, Any]],
    variable: str,
    channels: List[Any],
    st: int,
    end: int,
    fs: float,
    cfg: PcaSvdConfig,
) -> np.ndarray:
    """每信道 η；用于 PCA 列加权或模态级变量权重。"""
    weights = []
    for ch in channels:
        proc = ch_map.get(ch)
        if proc is None:
            weights.append(0.0)
            continue
        sig = proc[variable].get(cfg.signal_key)
        if sig is None or len(sig) < end:
            weights.append(0.0)
            continue
        weights.append(_channel_energy_ratio(sig[st:end], fs, cfg))
    return np.asarray(weights, dtype=float)


def select_top_k_channels(
    channels: List[Any],
    eta_weights: np.ndarray,
    top_k: int,
    *,
    min_channels: int = 4,
) -> Tuple[List[Any], np.ndarray]:
    """按 η 降序保留前 *top_k* 道；不足 ``min_channels`` 时退回全信道。"""
    if top_k <= 0 or len(channels) <= top_k:
        return list(channels), np.asarray(eta_weights, dtype=float)
    eta = np.asarray(eta_weights, dtype=float)
    order = np.argsort(-eta)[:top_k]
    sel_ch = [channels[i] for i in order]
    sel_eta = eta[order]
    if len(sel_ch) < min_channels:
        return list(channels), eta
    return sel_ch, sel_eta


def waveform_normalized_spectrum(
    waveform: np.ndarray,
    fs: float,
    nfft: int,
    band_mask: np.ndarray,
    hann: np.ndarray,
    eps: float = 1e-12,
) -> np.ndarray:
    """1D 波形 → 呼吸带归一化功率谱（用于模态融合）。"""
    if len(waveform) != len(hann) or not np.all(np.isfinite(waveform)):
        return np.zeros(int(np.sum(band_mask)), dtype=float)
    seg = waveform - np.mean(waveform)
    if np.std(seg) < eps:
        return np.zeros(int(np.sum(band_mask)), dtype=float)
    x = np.fft.rfft(seg * hann, n=nfft)
    p_band = (np.abs(x) ** 2)[band_mask]
    return p_band / (float(np.sum(p_band)) + eps)


def _fuse_modal_spectra(
    entries: List[Tuple[np.ndarray, float]],
    modal_weight: ModalWeightMode,
    band_freqs: np.ndarray,
    eps: float,
) -> float:
    """多模态归一化谱融合 → BPM（支持 equal / η / top2 equal）。"""
    if not entries:
        return np.nan
    if modal_weight == "top2_equal":
        ranked = sorted(entries, key=lambda e: e[1], reverse=True)
        use = ranked[: min(2, len(ranked))]
        w_arr = np.ones(len(use), dtype=float)
    else:
        use = entries
        if modal_weight == "energy_ratio":
            w_arr = np.asarray([max(e[1], eps) for e in use], dtype=float)
        else:
            w_arr = np.ones(len(use), dtype=float)
    if np.sum(w_arr) <= eps:
        return np.nan
    w_arr = w_arr / np.sum(w_arr)
    fused = np.sum(w_arr[:, None] * np.vstack([e[0] for e in use]), axis=0)
    return _bpm_from_spectrum(fused, band_freqs, eps)


def _bpm_from_spectrum(fused: np.ndarray, band_freqs: np.ndarray, eps: float) -> float:
    if fused.size == 0 or not np.any(np.isfinite(fused)):
        return np.nan
    k = int(np.argmax(fused))
    f_hat = float(band_freqs[k])
    if 0 < k < len(fused) - 1:
        y0, y1, y2 = fused[k - 1], fused[k], fused[k + 1]
        denom = y0 - 2.0 * y1 + y2
        if abs(denom) > eps:
            delta = 0.5 * (y0 - y2) / denom
            df = band_freqs[1] - band_freqs[0]
            f_hat = float(band_freqs[k] + delta * df)
    return 60.0 * f_hat


# ---------------------------------------------------------------------------
# 实矩阵 PCA
# ---------------------------------------------------------------------------


def extract_breath_waveform_pca(
    X: np.ndarray,
    cfg: Optional[PcaSvdConfig] = None,
    seg_name: str = "",
    channel_weights: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """从 M×N 实矩阵提取呼吸波形（PC1）。

    Parameters
    ----------
    X : ndarray, shape (M, N)
        每列是一个信道的带通滤波信号（M 帧, N 信道）。
    cfg : PcaSvdConfig, optional
    seg_name : str
        段名（用于警告信息）。

    Returns
    -------
    waveform : ndarray, shape (M,)
        PC1 时间序列（呼吸波形）。
    info : dict
        ``explained_variance_ratio``: 各主成分方差占比。
        ``pc1_variance_ratio``: PC1 方差占比。
        ``warn``: 警告信息列表。
    """
    cfg = cfg or PcaSvdConfig()
    info: Dict[str, Any] = {
        "explained_variance_ratio": [],
        "pc1_variance_ratio": np.nan,
        "warn": [],
    }
    if not _check_and_warn(X, cfg, seg_name):
        return np.full(X.shape[0], np.nan), info

    M, N = X.shape
    Z = _normalize_matrix(X, cfg.normalize, cfg.eps)
    Z = _apply_channel_weights(Z, channel_weights, cfg.eps)

    # 协方差矩阵 N×N（N=72 << M，特征分解高效）
    C = (Z.T @ Z) / max(M - 1, 1)
    eigenvalues, eigenvectors = np.linalg.eigh(C)  # 自动升序返回
    eigenvalues = eigenvalues[::-1]
    eigenvectors = eigenvectors[:, ::-1]  # 降序排列

    # 方差占比
    total_var = float(np.sum(eigenvalues))
    if total_var > cfg.eps:
        ratios = eigenvalues / total_var
    else:
        ratios = np.zeros_like(eigenvalues)
        ratios[0] = 1.0 if N > 0 else 0.0
    info["explained_variance_ratio"] = ratios.tolist()
    info["pc1_variance_ratio"] = float(ratios[0]) if len(ratios) > 0 else np.nan

    if info["pc1_variance_ratio"] < cfg.min_variance_ratio:
        w = (
            f"[{seg_name}] PC1 方差占比={info['pc1_variance_ratio']:.3f} < "
            f"{cfg.min_variance_ratio}，呼吸信号可能不占主导"
        )
        print(f"  ⚠ {w}")
        info["warn"].append(w)

    pc1 = Z @ eigenvectors[:, 0]  # shape (M,)
    return pc1, info


def pca_explained_variance(X: np.ndarray) -> np.ndarray:
    """返回 PCA 各主成分方差占比（不提取波形）。

    Parameters
    ----------
    X : ndarray, shape (M, N)

    Returns
    -------
    ratios : ndarray, shape (N,)
    """
    M, N = X.shape
    if N < 2:
        return np.array([1.0] if N == 1 else [])
    Z = _normalize_matrix(X, "zscore")
    C = (Z.T @ Z) / max(M - 1, 1)
    eigenvalues = np.linalg.eigvalsh(C)  # 升序
    total = float(np.sum(eigenvalues))
    if total <= 1e-12:
        return np.ones(N) / N
    return (eigenvalues[::-1] / total)  # 降序


# ---------------------------------------------------------------------------
# 实矩阵 SVD
# ---------------------------------------------------------------------------


def extract_breath_waveform_svd(
    X: np.ndarray,
    cfg: Optional[PcaSvdConfig] = None,
    seg_name: str = "",
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """从 M×N 实矩阵提取呼吸波形（第一左奇异向量）。

    Parameters
    ----------
    X : ndarray, shape (M, N)
    cfg : PcaSvdConfig, optional
    seg_name : str

    Returns
    -------
    waveform : ndarray, shape (M,)
    info : dict
    """
    cfg = cfg or PcaSvdConfig(method="svd_real")
    info: Dict[str, Any] = {
        "explained_variance_ratio": [],
        "pc1_variance_ratio": np.nan,
        "warn": [],
    }
    if not _check_and_warn(X, cfg, seg_name):
        return np.full(X.shape[0], np.nan), info

    Z = _normalize_matrix(X, cfg.normalize, cfg.eps)
    # 紧凑 SVD: Z = U @ diag(s) @ V^T
    U, s, Vt = np.linalg.svd(Z, full_matrices=False)
    s = np.asarray(s, dtype=float)

    # 奇异值平方 → 方差占比
    s2 = s**2
    total_s2 = float(np.sum(s2))
    if total_s2 > cfg.eps:
        ratios = s2 / total_s2
    else:
        ratios = np.ones(len(s)) / max(len(s), 1)
    info["explained_variance_ratio"] = ratios.tolist()
    info["pc1_variance_ratio"] = float(ratios[0]) if len(ratios) > 0 else np.nan

    if info["pc1_variance_ratio"] < cfg.min_variance_ratio:
        w = (
            f"[{seg_name}] SVD u_1 方差占比={info['pc1_variance_ratio']:.3f} < "
            f"{cfg.min_variance_ratio}"
        )
        print(f"  ⚠ {w}")
        info["warn"].append(w)

    u1 = U[:, 0]  # shape (M,)
    return u1, info


# ---------------------------------------------------------------------------
# 复矩阵 SVD
# ---------------------------------------------------------------------------


def extract_breath_waveform_complex_svd(
    X_complex: np.ndarray,
    cfg: Optional[PcaSvdConfig] = None,
    seg_name: str = "",
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """从 M×N 复矩阵提取呼吸波形（第一左奇异向量的幅值）。

    ``X_complex[i, j] = A_ij · exp(j · φ_ij)``，典型构造方式为
    每信道 j: ``amplitudes_j · exp(j · phases_j)``。

    Parameters
    ----------
    X_complex : ndarray, shape (M, N), dtype complex
    cfg : PcaSvdConfig, optional
        method 会被隐式覆写为 ``svd_complex``。
    seg_name : str

    Returns
    -------
    waveform : ndarray, shape (M,)
        |u1|，实数呼吸波形。
    info : dict
    """
    cfg = cfg or PcaSvdConfig(method="svd_complex")
    cfg.method = "svd_complex"
    info: Dict[str, Any] = {
        "explained_variance_ratio": [],
        "pc1_variance_ratio": np.nan,
        "warn": [],
    }
    if not _check_and_warn(np.abs(X_complex), cfg, seg_name):
        return np.full(X_complex.shape[0], np.nan), info

    # 复矩阵：每列中心化（去复均值），不做 zscore（幅值相位联合不宜过度缩放）
    Z = X_complex.astype(complex)
    Z = Z - np.mean(Z, axis=0, keepdims=True)

    # numpy 原生支持复 SVD: Z = U @ diag(s) @ V^H
    U, s, Vh = np.linalg.svd(Z, full_matrices=False)
    s = np.asarray(s, dtype=float)

    s2 = s**2
    total_s2 = float(np.sum(s2))
    if total_s2 > cfg.eps:
        ratios = s2 / total_s2
    else:
        ratios = np.ones(len(s)) / max(len(s), 1)
    info["explained_variance_ratio"] = ratios.tolist()
    info["pc1_variance_ratio"] = float(ratios[0]) if len(ratios) > 0 else np.nan

    if info["pc1_variance_ratio"] < cfg.min_variance_ratio:
        w = (
            f"[{seg_name}] 复SVD u_1 方差占比={info['pc1_variance_ratio']:.3f} < "
            f"{cfg.min_variance_ratio}"
        )
        print(f"  ⚠ {w}")
        info["warn"].append(w)

    u1 = U[:, 0]  # shape (M,), complex
    waveform = np.abs(u1)  # 取幅值，得到实值呼吸波形
    return waveform, info


def extract_breath_waveform_complex_pca(
    X_complex: np.ndarray,
    cfg: Optional[PcaSvdConfig] = None,
    seg_name: str = "",
    channel_weights: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """复矩阵 PCA：每列 ``A·e^(jφ)``，Hermitian 协方差第一特征向量，取 ``Re(PC1)``。"""
    cfg = cfg or PcaSvdConfig()
    info: Dict[str, Any] = {
        "explained_variance_ratio": [],
        "pc1_variance_ratio": np.nan,
        "warn": [],
    }
    if not _check_and_warn(np.abs(X_complex), cfg, seg_name):
        return np.full(X_complex.shape[0], np.nan), info

    m, n = X_complex.shape
    z = X_complex.astype(complex) - np.mean(X_complex.astype(complex), axis=0, keepdims=True)
    if channel_weights is not None and n > 0:
        w = np.maximum(np.asarray(channel_weights, dtype=float), 0.0)
        if w.shape[0] == n and np.sum(w) > cfg.eps:
            w = w / np.sum(w) * n
            z = z * np.sqrt(w)[np.newaxis, :]

    c = (z.conj().T @ z) / max(m - 1, 1)
    eigenvalues, eigenvectors = np.linalg.eigh(c)
    eigenvalues = eigenvalues[::-1].real
    eigenvectors = eigenvectors[:, ::-1]
    total_var = float(np.sum(eigenvalues))
    ratios = eigenvalues / total_var if total_var > cfg.eps else np.zeros_like(eigenvalues)
    info["explained_variance_ratio"] = ratios.tolist()
    info["pc1_variance_ratio"] = float(ratios[0]) if len(ratios) else np.nan

    pc1 = z @ eigenvectors[:, 0]
    return np.real(pc1), info


# ---------------------------------------------------------------------------
# 符号一致性
# ---------------------------------------------------------------------------


def align_waveform_sign(
    waveform: np.ndarray,
    prev_waveform: Optional[np.ndarray] = None,
    reference_channel: Optional[np.ndarray] = None,
) -> np.ndarray:
    """对齐呼吸波形符号，避免相邻窗口间因 SVD/PCA 符号任意性导致的翻转。

    优先级:
    1. 与上一窗口波形做相关，若负则翻转
    2. 首个窗口：若提供 reference_channel，与其做相关决定初始符号

    Parameters
    ----------
    waveform : ndarray, shape (M,)
        当前窗口的呼吸波形。
    prev_waveform : ndarray, optional
        上一窗口的波形（长度可能不同，取共同部分做相关）。
    reference_channel : ndarray, optional
        首个窗口的参考信号（如中位信道带通波形）。

    Returns
    -------
    ndarray
        符号对齐后的波形。
    """
    wf = waveform.copy()
    if prev_waveform is not None and len(prev_waveform) > 0 and len(wf) > 0:
        # 取较短长度做相关
        L = min(len(prev_waveform), len(wf))
        corr = np.dot(prev_waveform[:L], wf[:L])
        if corr < 0:
            wf = -wf
    elif reference_channel is not None and len(reference_channel) > 0 and len(wf) > 0:
        L = min(len(reference_channel), len(wf))
        corr = np.dot(reference_channel[:L], wf[:L])
        if corr < 0:
            wf = -wf
    return wf


# ---------------------------------------------------------------------------
# 多变量数据矩阵构造
# ---------------------------------------------------------------------------


def build_multivariable_data_matrix(
    ch_maps: Dict[str, Dict[Any, Dict[str, Any]]],
    var_names: List[str],
    channels: List[Any],
    st: int,
    end: int,
    signal_key: SignalKey = "highpass_filtered",
) -> np.ndarray:
    """将多种变量的多信道数据构造成一个 M×N 矩阵。

    每列是某个信道某个变量的 ``signal_key[st:end]`` 切片。
    列顺序: var_1 的所有信道, var_2 的所有信道, ...。

    Parameters
    ----------
    ch_maps : dict
        key=变量名, value = ``{ch: proc}``，其中 ``proc[varname][signal_key]`` 是 np.ndarray。
    var_names : list[str]
        要包含的变量名列表。
    channels : list
        信道标识列表。
    st : int
        窗口起始索引。
    end : int
        窗口结束索引。

    Returns
    -------
    ndarray, shape (M, N_total)
    """
    cols: List[np.ndarray] = []
    M = end - st
    for var in var_names:
        ch_map = ch_maps.get(var, {})
        for ch in channels:
            proc = ch_map.get(ch)
            if proc is None:
                continue
            sig = proc[var].get(signal_key)
            if sig is None or len(sig) < end:
                continue
            col = sig[st:end].copy()
            if len(col) == M:
                cols.append(col)
    if not cols:
        return np.empty((M, 0))
    return np.column_stack(cols).astype(float)


# ---------------------------------------------------------------------------
# PCA 模态融合（Plan2 结构，提取步换为 PCA）
# ---------------------------------------------------------------------------

MODAL_PCA_VARIABLES: Tuple[str, ...] = (
    "phases",
    "remote_amplitudes",
    "local_amplitudes",
)


def _next_pow2(n: int) -> int:
    return 1 if n <= 1 else 1 << (int(n) - 1).bit_length()


def run_pca_modal_fusion(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    modal_variables: Sequence[str] = MODAL_PCA_VARIABLES,
    channel_weight: ChannelWeightMode = "uniform",
    modal_weight: ModalWeightMode = "equal",
    top_k_channels: Optional[int] = None,
    metric_params: Optional[Any] = None,
    pca_svd_config: Optional[PcaSvdConfig] = None,
    verbose: bool = True,
) -> Dict[str, Optional[dict]]:
    """每变量滑窗 PCA 提取波形 → 归一化谱 → 模态加权融合 → BPM。

    与 Plan2 modal 相同融合框架，但将「每变量最佳单信道谱」替换为
    「该变量 72 道 PCA 主成分谱」。默认使用 ``highpass_filtered``。
    """
    from ble_analysis.segments import BreathMetricParams, _sliding_window_indices

    mp = metric_params or BreathMetricParams()
    cfg = pca_svd_config or PcaSvdConfig()
    cfg.channel_weight = channel_weight
    modal_vars = list(modal_variables)
    results: Dict[str, Optional[dict]] = {}

    ref_mc = multichannel_by_var.get(modal_vars[0], {})
    for seg_name in sorted(ref_mc.keys()):
        ref_seg = ref_mc.get(seg_name)
        if ref_seg is None:
            results[seg_name] = None
            continue
        metadata = ref_seg.get("metadata", {})
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
            if seg is None or not seg.get("channels"):
                ok = False
                break
            seg_maps[var] = seg["channels"]
            ref_len = max(
                ref_len,
                max(
                    len(c[var][cfg.signal_key])
                    for c in seg["channels"].values()
                    if c[var].get(cfg.signal_key) is not None
                ),
            )
        if not ok or ref_len == 0:
            results[seg_name] = None
            continue

        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            results[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        nfft = _next_pow2(4 * win_len)
        freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
        band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
        band_freqs = freqs[band_mask]
        hann = np.hanning(win_len)

        bpms: List[float] = []
        prev_wf: Dict[str, Optional[np.ndarray]] = {v: None for v in modal_vars}

        for st in starts:
            end = st + win_len
            modal_entries: List[Tuple[np.ndarray, float]] = []

            for var in modal_vars:
                ch_map = seg_maps[var]
                ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
                eta_all = compute_channel_energy_weights(
                    ch_map, var, ch_list, st, end, fs, cfg
                )
                use_ch, _ = select_top_k_channels(
                    ch_list, eta_all, top_k_channels or len(ch_list), min_channels=cfg.min_channels
                )
                x_mat, used_ch = build_channel_data_matrix(
                    ch_map, var, use_ch, st, end, cfg.signal_key
                )
                if x_mat.shape[1] < cfg.min_channels:
                    continue

                ch_w = None
                if channel_weight == "energy_ratio":
                    ch_w = compute_channel_energy_weights(
                        ch_map, var, used_ch, st, end, fs, cfg
                    )
                eta_sel = compute_channel_energy_weights(
                    ch_map, var, used_ch, st, end, fs, cfg
                )
                finite = eta_sel[np.isfinite(eta_sel) & (eta_sel > 0)]
                var_eta = float(np.mean(finite)) if finite.size else 0.0

                wf, _info = extract_breath_waveform_pca(
                    x_mat, cfg, seg_name, channel_weights=ch_w if channel_weight == "energy_ratio" else None
                )
                wf = align_waveform_sign(wf, prev_wf[var])
                prev_wf[var] = wf.copy()

                spec = waveform_normalized_spectrum(wf, fs, nfft, band_mask, hann, cfg.eps)
                modal_entries.append((spec, var_eta))

            bpms.append(
                _fuse_modal_spectra(modal_entries, modal_weight, band_freqs, cfg.eps)
            )

        top_suffix = f"_top{top_k_channels}" if top_k_channels else ""
        method_key = f"pca_modal_{modal_weight}_ch_{channel_weight}{top_suffix}"
        from ble_analysis.chfusion import _seg_bpm_stats

        results[seg_name] = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "metadata": metadata,
            method_key: _seg_bpm_stats(np.asarray(bpms, dtype=float), bpm_gt, len(starts)),
        }

    if verbose:
        n_ok = sum(1 for v in results.values() if v is not None)
        print(
            f"✓ PCA modal fusion ({len(modal_vars)} vars, ch={channel_weight}, "
            f"modal={modal_weight}) | {n_ok} segments"
        )
    return results


def run_pca_topk_bpm(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    variable: str,
    top_k: int,
    channel_weight: ChannelWeightMode = "energy_ratio",
    metric_params: Optional[Any] = None,
    pca_svd_config: Optional[PcaSvdConfig] = None,
    verbose: bool = True,
) -> Dict[str, Optional[dict]]:
    """单变量高通 PCA：每窗按 η 取 top-K 信道 → PC1 → 波形 FFT BPM。"""
    from ble_analysis.segments import BreathMetricParams, _estimate_breathing_freq_hz, _sliding_window_indices
    from ble_analysis.chfusion import _seg_bpm_stats

    mp = metric_params or BreathMetricParams()
    cfg = pca_svd_config or PcaSvdConfig()
    results: Dict[str, Optional[dict]] = {}
    mc = multichannel_by_var.get(variable, {})

    for seg_name in sorted(mc.keys()):
        seg = mc.get(seg_name)
        if seg is None or not seg.get("channels"):
            results[seg_name] = None
            continue
        metadata = seg.get("metadata", {})
        if metadata.get("segment_type") == "apnea":
            results[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]
        ch_map = seg["channels"]
        ch_list = sorted(ch_map.keys(), key=lambda c: (isinstance(c, str), str(c)))
        ref_len = max(
            len(ch_map[c][variable].get(cfg.signal_key, []))
            for c in ch_list
            if ch_map[c][variable].get(cfg.signal_key) is not None
        )
        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            results[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        bpms: List[float] = []
        prev_wf = None

        for st in starts:
            end = st + win_len
            eta_all = compute_channel_energy_weights(
                ch_map, variable, ch_list, st, end, fs, cfg
            )
            use_ch, _ = select_top_k_channels(
                ch_list, eta_all, top_k, min_channels=cfg.min_channels
            )
            x_mat, used_ch = build_channel_data_matrix(
                ch_map, variable, use_ch, st, end, cfg.signal_key
            )
            if x_mat.shape[1] < cfg.min_channels:
                bpms.append(np.nan)
                continue
            ch_w = None
            if channel_weight == "energy_ratio":
                ch_w = compute_channel_energy_weights(
                    ch_map, variable, used_ch, st, end, fs, cfg
                )
            wf, _info = extract_breath_waveform_pca(
                x_mat, cfg, seg_name, channel_weights=ch_w
            )
            wf = align_waveform_sign(wf, prev_wf)
            prev_wf = wf.copy()
            if len(wf) < 4 or not np.all(np.isfinite(wf)):
                bpms.append(np.nan)
                continue
            seg_wf = wf - np.mean(wf)
            f_hz = _estimate_breathing_freq_hz(
                seg_wf, fs, cfg.breath_freq_low, cfg.breath_freq_high
            )
            bpms.append(60.0 * f_hz if np.isfinite(f_hz) else np.nan)

        key = f"pca_topk_{variable}_k{top_k}_ch_{channel_weight}"
        results[seg_name] = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "metadata": metadata,
            key: _seg_bpm_stats(np.asarray(bpms, dtype=float), bpm_gt, len(starts)),
        }

    if verbose:
        print(f"✓ PCA top-{top_k} ({variable}, ch={channel_weight})")
    return results


def run_pca_complex_fusion(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    amp_var: str = "amplitudes",
    channel_weight: ChannelWeightMode = "uniform",
    top_k_channels: Optional[int] = None,
    metric_params: Optional[Any] = None,
    pca_svd_config: Optional[PcaSvdConfig] = None,
    verbose: bool = True,
) -> Dict[str, Optional[dict]]:
    """每窗构造 ``amp·e^(j·phase)`` 复矩阵 → 复 PCA → BPM（高通输入）。"""
    from ble_analysis.segments import BreathMetricParams, _sliding_window_indices
    from ble_analysis.chfusion import _seg_bpm_stats

    mp = metric_params or BreathMetricParams()
    cfg = pca_svd_config or PcaSvdConfig()
    results: Dict[str, Optional[dict]] = {}

    mc_amp = multichannel_by_var.get(amp_var, {})
    mc_pha = multichannel_by_var.get("phases", {})

    for seg_name in sorted(mc_pha.keys()):
        seg_amp = mc_amp.get(seg_name)
        seg_pha = mc_pha.get(seg_name)
        if seg_amp is None or seg_pha is None:
            results[seg_name] = None
            continue
        metadata = seg_pha.get("metadata", {})
        if metadata.get("segment_type") == "apnea":
            results[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]
        ch_map_a = seg_amp["channels"]
        ch_map_p = seg_pha["channels"]
        ch_list = sorted(
            set(ch_map_a.keys()) & set(ch_map_p.keys()),
            key=lambda c: (isinstance(c, str), str(c)),
        )
        ref_len = 0
        for ch in ch_list:
            a = ch_map_a[ch][amp_var].get(cfg.signal_key)
            p = ch_map_p[ch]["phases"].get(cfg.signal_key)
            if a is not None and p is not None:
                ref_len = max(ref_len, min(len(a), len(p)))
        if ref_len == 0:
            results[seg_name] = None
            continue

        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            results[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        nfft = _next_pow2(4 * win_len)
        freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
        band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
        band_freqs = freqs[band_mask]
        hann = np.hanning(win_len)
        bpms: List[float] = []
        prev_wf = None

        for st in starts:
            end = st + win_len
            eta_all = compute_channel_energy_weights(
                ch_map_a, amp_var, ch_list, st, end, fs, cfg
            )
            use_ch, _ = select_top_k_channels(
                ch_list, eta_all, top_k_channels or len(ch_list), min_channels=cfg.min_channels
            )
            cols_c = []
            used = []
            for ch in use_ch:
                pa = ch_map_a.get(ch)
                pp = ch_map_p.get(ch)
                if pa is None or pp is None:
                    continue
                ba = pa[amp_var].get(cfg.signal_key)
                bp = pp["phases"].get(cfg.signal_key)
                if ba is None or bp is None or len(ba) < end or len(bp) < end:
                    continue
                cols_c.append(ba[st:end] * np.exp(1j * bp[st:end]))
                used.append(ch)

            if len(cols_c) < cfg.min_channels:
                bpms.append(np.nan)
                continue

            x_c = np.column_stack(cols_c)
            ch_w = None
            if channel_weight == "energy_ratio":
                ch_w = compute_channel_energy_weights(
                    ch_map_a, amp_var, used, st, end, fs, cfg
                )
            wf, _info = extract_breath_waveform_complex_pca(
                x_c, cfg, seg_name, channel_weights=ch_w
            )
            wf = align_waveform_sign(wf, prev_wf)
            prev_wf = wf.copy()
            spec = waveform_normalized_spectrum(wf, fs, nfft, band_mask, hann, cfg.eps)
            bpms.append(_bpm_from_spectrum(spec, band_freqs, cfg.eps))

        top_suffix = f"_top{top_k_channels}" if top_k_channels else ""
        key = f"pca_complex_{amp_var}_ch_{channel_weight}{top_suffix}"
        results[seg_name] = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "metadata": metadata,
            key: _seg_bpm_stats(np.asarray(bpms, dtype=float), bpm_gt, len(starts)),
        }

    if verbose:
        print(f"✓ PCA complex ({amp_var}, ch={channel_weight})")
    return results


def _common_complex_segment_channels(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
) -> Tuple[Optional[dict], Optional[dict], Optional[dict], Optional[dict], List[Any], int]:
    """返回 remote/local/phase 段与共有信道列表、参考长度。"""
    seg_rem = multichannel_by_var.get("remote_amplitudes", {}).get(seg_name)
    seg_loc = multichannel_by_var.get("local_amplitudes", {}).get(seg_name)
    seg_pha = multichannel_by_var.get("phases", {}).get(seg_name)
    if seg_rem is None or seg_loc is None or seg_pha is None:
        return None, None, None, None, [], 0
    ch_map_r = seg_rem["channels"]
    ch_map_l = seg_loc["channels"]
    ch_map_p = seg_pha["channels"]
    ch_list = sorted(
        set(ch_map_r.keys()) & set(ch_map_l.keys()) & set(ch_map_p.keys()),
        key=lambda c: (isinstance(c, str), str(c)),
    )
    return seg_rem, seg_loc, seg_pha, seg_pha, ch_list, 0


def _ref_len_complex_triple(
    ch_map_r: Dict[Any, dict],
    ch_map_l: Dict[Any, dict],
    ch_map_p: Dict[Any, dict],
    ch_list: List[Any],
    signal_key: SignalKey,
) -> int:
    ref_len = 0
    for ch in ch_list:
        ar = ch_map_r[ch]["remote_amplitudes"].get(signal_key)
        al = ch_map_l[ch]["local_amplitudes"].get(signal_key)
        ph = ch_map_p[ch]["phases"].get(signal_key)
        if ar is not None and al is not None and ph is not None:
            ref_len = max(ref_len, min(len(ar), len(al), len(ph)))
    return ref_len


def _complex_pca_bpm_from_matrix(
    x_c: np.ndarray,
    cfg: PcaSvdConfig,
    seg_name: str,
    ch_weights: Optional[np.ndarray],
    prev_wf: Optional[np.ndarray],
    fs: float,
    nfft: int,
    band_mask: np.ndarray,
    band_freqs: np.ndarray,
    hann: np.ndarray,
) -> Tuple[float, np.ndarray]:
    wf, _info = extract_breath_waveform_complex_pca(
        x_c, cfg, seg_name, channel_weights=ch_weights
    )
    wf = align_waveform_sign(wf, prev_wf)
    spec = waveform_normalized_spectrum(wf, fs, nfft, band_mask, hann, cfg.eps)
    return _bpm_from_spectrum(spec, band_freqs, cfg.eps), wf


def build_complex_dual_amp_matrix(
    ch_map_r: Dict[Any, dict],
    ch_map_l: Dict[Any, dict],
    ch_map_p: Dict[Any, dict],
    ch_list: List[Any],
    st: int,
    end: int,
    signal_key: SignalKey,
) -> Tuple[np.ndarray, List[Tuple[str, Any]]]:
    """方案2：remote∥local 各 72 列 ``A·e^(jφ)``，共 2N 列。"""
    cols: List[np.ndarray] = []
    meta: List[Tuple[str, Any]] = []
    for ch in ch_list:
        ar = ch_map_r[ch]["remote_amplitudes"].get(signal_key)
        al = ch_map_l[ch]["local_amplitudes"].get(signal_key)
        ph = ch_map_p[ch]["phases"].get(signal_key)
        if ar is None or al is None or ph is None or len(ar) < end or len(al) < end or len(ph) < end:
            continue
        p = ph[st:end]
        cols.append(ar[st:end] * np.exp(1j * p))
        meta.append(("remote_amplitudes", ch))
        cols.append(al[st:end] * np.exp(1j * p))
        meta.append(("local_amplitudes", ch))
    if not cols:
        return np.empty((end - st, 0), dtype=complex), []
    return np.column_stack(cols), meta


def build_complex_eta_blend_matrix(
    ch_map_r: Dict[Any, dict],
    ch_map_l: Dict[Any, dict],
    ch_map_p: Dict[Any, dict],
    ch_list: List[Any],
    st: int,
    end: int,
    fs: float,
    cfg: PcaSvdConfig,
) -> Tuple[np.ndarray, List[Any]]:
    """方案3：每信道 ``Ã=(η_r A_r + η_l A_l)/(η_r+η_l)``，再 ``Ã·e^(jφ)``。"""
    cols: List[np.ndarray] = []
    used: List[Any] = []
    for ch in ch_list:
        ar = ch_map_r[ch]["remote_amplitudes"].get(cfg.signal_key)
        al = ch_map_l[ch]["local_amplitudes"].get(cfg.signal_key)
        ph = ch_map_p[ch]["phases"].get(cfg.signal_key)
        if ar is None or al is None or ph is None or len(ar) < end or len(al) < end or len(ph) < end:
            continue
        sl_r, sl_l, sl_p = ar[st:end], al[st:end], ph[st:end]
        eta_r = _channel_energy_ratio(sl_r, fs, cfg)
        eta_l = _channel_energy_ratio(sl_l, fs, cfg)
        denom = eta_r + eta_l + cfg.eps
        a_blend = (eta_r * sl_r + eta_l * sl_l) / denom
        cols.append(a_blend * np.exp(1j * sl_p))
        used.append(ch)
    if not cols:
        return np.empty((end - st, 0), dtype=complex), []
    return np.column_stack(cols), used


def _dual_amp_column_weights(
    meta: List[Tuple[str, Any]],
    ch_map_r: Dict[Any, dict],
    ch_map_l: Dict[Any, dict],
    st: int,
    end: int,
    fs: float,
    cfg: PcaSvdConfig,
) -> np.ndarray:
    weights = []
    for var, ch in meta:
        ch_map = ch_map_r if var == "remote_amplitudes" else ch_map_l
        w = compute_channel_energy_weights(ch_map, var, [ch], st, end, fs, cfg)
        weights.append(float(w[0]) if w.size else 0.0)
    return np.asarray(weights, dtype=float)


def run_pca_complex_dual_amp(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    channel_weight: ChannelWeightMode = "uniform",
    metric_params: Optional[Any] = None,
    pca_svd_config: Optional[PcaSvdConfig] = None,
    verbose: bool = True,
) -> Dict[str, Optional[dict]]:
    """方案2：remote/local 双复矩阵堆叠 (2×72 列) → 复 PCA → BPM。"""
    from ble_analysis.segments import BreathMetricParams, _sliding_window_indices
    from ble_analysis.chfusion import _seg_bpm_stats

    mp = metric_params or BreathMetricParams()
    cfg = pca_svd_config or PcaSvdConfig()
    results: Dict[str, Optional[dict]] = {}
    mc_pha = multichannel_by_var.get("phases", {})

    for seg_name in sorted(mc_pha.keys()):
        seg_rem, seg_loc, seg_pha, _, ch_list, _ = _common_complex_segment_channels(
            multichannel_by_var, seg_name
        )
        if seg_rem is None or not ch_list:
            results[seg_name] = None
            continue
        metadata = seg_pha["metadata"]
        if metadata.get("segment_type") == "apnea":
            results[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]
        ch_map_r = seg_rem["channels"]
        ch_map_l = seg_loc["channels"]
        ch_map_p = seg_pha["channels"]
        ref_len = _ref_len_complex_triple(ch_map_r, ch_map_l, ch_map_p, ch_list, cfg.signal_key)
        if ref_len == 0:
            results[seg_name] = None
            continue

        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            results[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        nfft = _next_pow2(4 * win_len)
        freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
        band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
        band_freqs = freqs[band_mask]
        hann = np.hanning(win_len)
        bpms: List[float] = []
        prev_wf = None

        for st in starts:
            end = st + win_len
            x_c, meta = build_complex_dual_amp_matrix(
                ch_map_r, ch_map_l, ch_map_p, ch_list, st, end, cfg.signal_key
            )
            if x_c.shape[1] < cfg.min_channels:
                bpms.append(np.nan)
                continue
            ch_w = (
                _dual_amp_column_weights(meta, ch_map_r, ch_map_l, st, end, fs, cfg)
                if channel_weight == "energy_ratio"
                else None
            )
            bpm, prev_wf = _complex_pca_bpm_from_matrix(
                x_c, cfg, seg_name, ch_w, prev_wf, fs, nfft, band_mask, band_freqs, hann
            )
            bpms.append(bpm)

        key = f"pca_complex_dual_amp_ch_{channel_weight}"
        results[seg_name] = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "metadata": metadata,
            key: _seg_bpm_stats(np.asarray(bpms, dtype=float), bpm_gt, len(starts)),
        }

    if verbose:
        print(f"✓ PCA complex dual-amp (ch={channel_weight})")
    return results


def run_pca_complex_eta_blend(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    channel_weight: ChannelWeightMode = "uniform",
    metric_params: Optional[Any] = None,
    pca_svd_config: Optional[PcaSvdConfig] = None,
    verbose: bool = True,
) -> Dict[str, Optional[dict]]:
    """方案3：每信道 η 混合 remote/local 幅值后 ``Ã·e^(jφ)`` → 复 PCA。"""
    from ble_analysis.segments import BreathMetricParams, _sliding_window_indices
    from ble_analysis.chfusion import _seg_bpm_stats

    mp = metric_params or BreathMetricParams()
    cfg = pca_svd_config or PcaSvdConfig()
    results: Dict[str, Optional[dict]] = {}
    mc_pha = multichannel_by_var.get("phases", {})

    for seg_name in sorted(mc_pha.keys()):
        seg_rem, seg_loc, seg_pha, _, ch_list, _ = _common_complex_segment_channels(
            multichannel_by_var, seg_name
        )
        if seg_rem is None or not ch_list:
            results[seg_name] = None
            continue
        metadata = seg_pha["metadata"]
        if metadata.get("segment_type") == "apnea":
            results[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]
        ch_map_r = seg_rem["channels"]
        ch_map_l = seg_loc["channels"]
        ch_map_p = seg_pha["channels"]
        ref_len = _ref_len_complex_triple(ch_map_r, ch_map_l, ch_map_p, ch_list, cfg.signal_key)
        if ref_len == 0:
            results[seg_name] = None
            continue

        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            results[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        nfft = _next_pow2(4 * win_len)
        freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
        band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
        band_freqs = freqs[band_mask]
        hann = np.hanning(win_len)
        bpms: List[float] = []
        prev_wf = None

        for st in starts:
            end = st + win_len
            x_c, used = build_complex_eta_blend_matrix(
                ch_map_r, ch_map_l, ch_map_p, ch_list, st, end, fs, cfg
            )
            if x_c.shape[1] < cfg.min_channels:
                bpms.append(np.nan)
                continue
            ch_w = None
            if channel_weight == "energy_ratio":
                eta_r = compute_channel_energy_weights(
                    ch_map_r, "remote_amplitudes", used, st, end, fs, cfg
                )
                eta_l = compute_channel_energy_weights(
                    ch_map_l, "local_amplitudes", used, st, end, fs, cfg
                )
                ch_w = (eta_r + eta_l) * 0.5
            bpm, prev_wf = _complex_pca_bpm_from_matrix(
                x_c, cfg, seg_name, ch_w, prev_wf, fs, nfft, band_mask, band_freqs, hann
            )
            bpms.append(bpm)

        key = f"pca_complex_eta_blend_ch_{channel_weight}"
        results[seg_name] = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "metadata": metadata,
            key: _seg_bpm_stats(np.asarray(bpms, dtype=float), bpm_gt, len(starts)),
        }

    if verbose:
        print(f"✓ PCA complex η-blend (ch={channel_weight})")
    return results


def build_complex_amp_phase_matrix(
    ch_map_amp: Dict[Any, dict],
    ch_map_pha: Dict[Any, dict],
    amp_var: str,
    ch_list: List[Any],
    st: int,
    end: int,
    signal_key: SignalKey,
) -> Tuple[np.ndarray, List[Any]]:
    cols: List[np.ndarray] = []
    used: List[Any] = []
    for ch in ch_list:
        pa = ch_map_amp.get(ch)
        pp = ch_map_pha.get(ch)
        if pa is None or pp is None:
            continue
        ba = pa[amp_var].get(signal_key)
        bp = pp["phases"].get(signal_key)
        if ba is None or bp is None or len(ba) < end or len(bp) < end:
            continue
        cols.append(ba[st:end] * np.exp(1j * bp[st:end]))
        used.append(ch)
    if not cols:
        return np.empty((end - st, 0), dtype=complex), []
    return np.column_stack(cols), used


def run_pca_complex_modal_fusion(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    amp_variables: Sequence[str] = ("remote_amplitudes", "local_amplitudes"),
    channel_weight: ChannelWeightMode = "uniform",
    modal_weight: ModalWeightMode = "equal",
    metric_params: Optional[Any] = None,
    pca_svd_config: Optional[PcaSvdConfig] = None,
    verbose: bool = True,
) -> Dict[str, Optional[dict]]:
    """方案4：每幅值变量独立 ``A·e^(jφ)`` 复 PCA → 模态谱融合 → BPM。"""
    from ble_analysis.segments import BreathMetricParams, _sliding_window_indices
    from ble_analysis.chfusion import _seg_bpm_stats

    mp = metric_params or BreathMetricParams()
    cfg = pca_svd_config or PcaSvdConfig()
    amp_vars = list(amp_variables)
    results: Dict[str, Optional[dict]] = {}
    mc_pha = multichannel_by_var.get("phases", {})

    for seg_name in sorted(mc_pha.keys()):
        seg_rem, seg_loc, seg_pha, _, ch_list, _ = _common_complex_segment_channels(
            multichannel_by_var, seg_name
        )
        if seg_rem is None or not ch_list:
            results[seg_name] = None
            continue
        metadata = seg_pha["metadata"]
        if metadata.get("segment_type") == "apnea":
            results[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]
        ch_map_p = seg_pha["channels"]
        amp_maps = {
            "remote_amplitudes": seg_rem["channels"],
            "local_amplitudes": seg_loc["channels"],
            "amplitudes": multichannel_by_var.get("amplitudes", {}).get(seg_name, {}).get(
                "channels", {}
            ),
        }
        ref_len = _ref_len_complex_triple(
            amp_maps["remote_amplitudes"],
            amp_maps["local_amplitudes"],
            ch_map_p,
            ch_list,
            cfg.signal_key,
        )
        if ref_len == 0:
            results[seg_name] = None
            continue

        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            results[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        nfft = _next_pow2(4 * win_len)
        freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
        band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
        band_freqs = freqs[band_mask]
        hann = np.hanning(win_len)
        bpms: List[float] = []
        prev_wf: Dict[str, Optional[np.ndarray]] = {v: None for v in amp_vars}

        for st in starts:
            end = st + win_len
            modal_entries: List[Tuple[np.ndarray, float]] = []

            for amp_var in amp_vars:
                ch_map_a = amp_maps.get(amp_var, {})
                if not ch_map_a:
                    continue
                x_c, used = build_complex_amp_phase_matrix(
                    ch_map_a, ch_map_p, amp_var, ch_list, st, end, cfg.signal_key
                )
                if x_c.shape[1] < cfg.min_channels:
                    continue
                ch_w = None
                eta_all = compute_channel_energy_weights(
                    ch_map_a, amp_var, used, st, end, fs, cfg
                )
                finite = eta_all[np.isfinite(eta_all) & (eta_all > 0)]
                var_eta = float(np.mean(finite)) if finite.size else 0.0
                if channel_weight == "energy_ratio":
                    ch_w = eta_all
                wf, _ = extract_breath_waveform_complex_pca(
                    x_c, cfg, seg_name, channel_weights=ch_w
                )
                wf = align_waveform_sign(wf, prev_wf[amp_var])
                prev_wf[amp_var] = wf.copy()
                spec = waveform_normalized_spectrum(
                    wf, fs, nfft, band_mask, hann, cfg.eps
                )
                modal_entries.append((spec, var_eta))

            bpms.append(
                _fuse_modal_spectra(modal_entries, modal_weight, band_freqs, cfg.eps)
            )

        key = f"pca_complex_modal_{modal_weight}_ch_{channel_weight}"
        results[seg_name] = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "metadata": metadata,
            key: _seg_bpm_stats(np.asarray(bpms, dtype=float), bpm_gt, len(starts)),
        }

    if verbose:
        amps = "+".join(a.replace("_amplitudes", "") for a in amp_vars)
        print(
            f"✓ PCA complex modal ({amps}, ch={channel_weight}, modal={modal_weight})"
        )
    return results


def extract_integration_pc1_spectrum(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    seg_name: str,
    *,
    integration: Literal["eta_blend", "dual_amp", "total_complex"],
    window_index: int = 0,
    channel_weight: ChannelWeightMode = "energy_ratio",
    metric_params: Optional[Any] = None,
    pca_svd_config: Optional[PcaSvdConfig] = None,
) -> Optional[dict]:
    """提取指定段/窗的 PC1 呼吸带归一化谱（用于与 GT 频率对照图）。"""
    from ble_analysis.segments import BreathMetricParams, _sliding_window_indices

    mp = metric_params or BreathMetricParams()
    cfg = pca_svd_config or PcaSvdConfig()
    mc_pha = multichannel_by_var.get("phases", {})
    seg_pha = mc_pha.get(seg_name)
    if seg_pha is None:
        return None
    metadata = seg_pha.get("metadata", {})
    if metadata.get("segment_type") == "apnea":
        return None

    bpm_gt = metadata.get("bpm_gt")
    fs = metadata["sampling_rate"]
    seg_rem, seg_loc, _, _, ch_list, _ = _common_complex_segment_channels(
        multichannel_by_var, seg_name
    )
    if seg_rem is None or not ch_list:
        return None

    ch_map_r = seg_rem["channels"]
    ch_map_l = seg_loc["channels"]
    ch_map_p = seg_pha["channels"]
    ch_map_a = multichannel_by_var.get("amplitudes", {}).get(seg_name, {}).get("channels", {})
    ref_len = _ref_len_complex_triple(ch_map_r, ch_map_l, ch_map_p, ch_list, cfg.signal_key)
    if ref_len == 0:
        return None

    win_len = int(round(mp.window_length_sec * fs))
    step_len = int(round(mp.step_length_sec * fs))
    if ref_len < win_len:
        return None

    starts = _sliding_window_indices(ref_len, win_len, step_len)
    if not starts:
        return None
    wi = int(np.clip(window_index, 0, len(starts) - 1))
    st = starts[wi]
    end = st + win_len
    nfft = _next_pow2(4 * win_len)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
    band_freqs = freqs[band_mask]
    hann = np.hanning(win_len)

    if integration == "total_complex":
        eta_all = compute_channel_energy_weights(
            ch_map_a, "amplitudes", ch_list, st, end, fs, cfg
        )
        use_ch, _ = select_top_k_channels(
            ch_list, eta_all, len(ch_list), min_channels=cfg.min_channels
        )
        cols_c, used = [], []
        for ch in use_ch:
            pa = ch_map_a.get(ch)
            pp = ch_map_p.get(ch)
            if pa is None or pp is None:
                continue
            ba = pa["amplitudes"].get(cfg.signal_key)
            bp = pp["phases"].get(cfg.signal_key)
            if ba is None or bp is None or len(ba) < end or len(bp) < end:
                continue
            cols_c.append(ba[st:end] * np.exp(1j * bp[st:end]))
            used.append(ch)
        if len(cols_c) < cfg.min_channels:
            return None
        x_c = np.column_stack(cols_c)
        ch_w = (
            compute_channel_energy_weights(ch_map_a, "amplitudes", used, st, end, fs, cfg)
            if channel_weight == "energy_ratio"
            else None
        )
    elif integration == "dual_amp":
        x_c, meta = build_complex_dual_amp_matrix(
            ch_map_r, ch_map_l, ch_map_p, ch_list, st, end, cfg.signal_key
        )
        ch_w = (
            _dual_amp_column_weights(meta, ch_map_r, ch_map_l, st, end, fs, cfg)
            if channel_weight == "energy_ratio"
            else None
        )
    else:
        x_c, used = build_complex_eta_blend_matrix(
            ch_map_r, ch_map_l, ch_map_p, ch_list, st, end, fs, cfg
        )
        ch_w = None
        if channel_weight == "energy_ratio" and used:
            ch_w = compute_channel_energy_weights(
                ch_map_r, "remote_amplitudes", used, st, end, fs, cfg
            )

    if x_c.shape[1] < cfg.min_channels:
        return None

    wf, _info = extract_breath_waveform_complex_pca(
        x_c, cfg, seg_name, channel_weights=ch_w
    )
    spec = waveform_normalized_spectrum(wf, fs, nfft, band_mask, hann, cfg.eps)
    peak_hz = np.nan
    if spec.size and np.any(np.isfinite(spec)):
        peak_hz = float(band_freqs[int(np.argmax(spec))])
    gt_hz = float(bpm_gt) / 60.0 if bpm_gt else np.nan
    return {
        "segment": seg_name,
        "window_index": wi,
        "bpm_gt": bpm_gt,
        "gt_hz": gt_hz,
        "peak_hz": peak_hz,
        "band_freqs": band_freqs,
        "spectrum": spec,
        "pc1_variance_ratio": _info.get("pc1_variance_ratio", np.nan),
    }


def _classify_bpm_harmonic_ratio(bpm_est: float, bpm_gt: float) -> str:
    """窗级 BPM 与 GT 比值 → fundamental / double / half / other。"""
    if not np.isfinite(bpm_est) or not np.isfinite(bpm_gt) or bpm_gt <= 0:
        return "other"
    ratio = float(bpm_est) / float(bpm_gt)
    if 0.85 <= ratio <= 1.15:
        return "fundamental"
    if 1.75 <= ratio <= 2.25:
        return "double"
    if 0.4 <= ratio <= 0.6:
        return "half"
    return "other"


def diagnose_complex_integration_harmonics(
    multichannel_by_var: Dict[str, Dict[str, Optional[dict]]],
    *,
    integration: Literal["eta_blend", "dual_amp"],
    channel_weight: ChannelWeightMode = "energy_ratio",
    metric_params: Optional[Any] = None,
    pca_svd_config: Optional[PcaSvdConfig] = None,
) -> Dict[str, Optional[dict]]:
    """091339 等场景：统计 η-blend / Dual-Amp PC1 窗级 BPM 倍频/半频占比。"""
    from ble_analysis.segments import BreathMetricParams, _sliding_window_indices

    mp = metric_params or BreathMetricParams()
    cfg = pca_svd_config or PcaSvdConfig()
    results: Dict[str, Optional[dict]] = {}
    mc_pha = multichannel_by_var.get("phases", {})

    for seg_name in sorted(mc_pha.keys()):
        seg_rem, seg_loc, seg_pha, _, ch_list, _ = _common_complex_segment_channels(
            multichannel_by_var, seg_name
        )
        if seg_rem is None or not ch_list:
            results[seg_name] = None
            continue
        metadata = seg_pha["metadata"]
        if metadata.get("segment_type") == "apnea":
            results[seg_name] = None
            continue

        bpm_gt = metadata.get("bpm_gt")
        fs = metadata["sampling_rate"]
        ch_map_r = seg_rem["channels"]
        ch_map_l = seg_loc["channels"]
        ch_map_p = seg_pha["channels"]
        ref_len = _ref_len_complex_triple(ch_map_r, ch_map_l, ch_map_p, ch_list, cfg.signal_key)
        if ref_len == 0:
            results[seg_name] = None
            continue

        win_len = int(round(mp.window_length_sec * fs))
        step_len = int(round(mp.step_length_sec * fs))
        if ref_len < win_len:
            results[seg_name] = None
            continue

        starts = _sliding_window_indices(ref_len, win_len, step_len)
        nfft = _next_pow2(4 * win_len)
        freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
        band_mask = (freqs >= cfg.breath_freq_low) & (freqs <= cfg.breath_freq_high)
        band_freqs = freqs[band_mask]
        hann = np.hanning(win_len)
        buckets = {"fundamental": 0, "double": 0, "half": 0, "other": 0}
        rel_errs: List[float] = []
        prev_wf = None

        for st in starts:
            end = st + win_len
            if integration == "dual_amp":
                x_c, meta = build_complex_dual_amp_matrix(
                    ch_map_r, ch_map_l, ch_map_p, ch_list, st, end, cfg.signal_key
                )
                ch_w = (
                    _dual_amp_column_weights(meta, ch_map_r, ch_map_l, st, end, fs, cfg)
                    if channel_weight == "energy_ratio"
                    else None
                )
            else:
                x_c, used = build_complex_eta_blend_matrix(
                    ch_map_r, ch_map_l, ch_map_p, ch_list, st, end, fs, cfg
                )
                ch_w = None
                if channel_weight == "energy_ratio" and used:
                    ch_w = compute_channel_energy_weights(
                        ch_map_r, "remote_amplitudes", used, st, end, fs, cfg
                    )
            if x_c.shape[1] < cfg.min_channels:
                buckets["other"] += 1
                continue
            bpm, prev_wf = _complex_pca_bpm_from_matrix(
                x_c, cfg, seg_name, ch_w, prev_wf, fs, nfft, band_mask, band_freqs, hann
            )
            if np.isfinite(bpm) and np.isfinite(bpm_gt) and bpm_gt > 0:
                rel_errs.append(abs(bpm - bpm_gt) / bpm_gt)
            buckets[_classify_bpm_harmonic_ratio(bpm, bpm_gt)] += 1

        n_win = len(starts)
        fracs = {k: buckets[k] / n_win for k in buckets}
        mean_rel = float(np.mean(rel_errs)) * 100.0 if rel_errs else np.nan
        results[seg_name] = {
            "segment": seg_name,
            "bpm_gt": bpm_gt,
            "n_windows": n_win,
            "mean_rel_err_pct": mean_rel,
            "harmonic_fracs": fracs,
            "harmonic_counts": buckets,
        }
    return results
