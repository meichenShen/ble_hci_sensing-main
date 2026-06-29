#!/usr/bin/env python3
"""
BLE CS PCA 呼吸波形提取 — 独立演示
=====================================

两种 PCA 方案从 BLE CS 多信道数据（已滤波）中提取呼吸信号：

1. **实矩阵 PCA**: 72 tone 幅值 → z-score → 协方差特征分解 → PC1 = 呼吸波形
2. **复矩阵 PCA**: A·e^(jφ) → 列中心化 → Hermitian 特征分解 → Re(PC1) = 呼吸波形

前提: 输入数据已经过高通滤波 (0.05 Hz) 去除直流和低频漂移。

依赖: numpy, scipy (仅 median filter), matplotlib
用法: python pca_demo.py [CS_frames_*.jsonl]
"""

from __future__ import annotations

import json, sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import median_filter as _medfilt


# ═══════════════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════════════

def _ch_sort(ch: object) -> tuple:
    s = str(ch)
    return (0, int(s)) if s.lstrip("-").isdigit() else (1, s)


def _find_ch(channels: dict, target: object) -> object | None:
    for key in (target, str(target)):
        if key in channels:
            return key
    if isinstance(target, str) and target.lstrip("-").isdigit():
        k = int(target)
        if k in channels:
            return k
    return None


def load_data(filepath: str) -> tuple[np.ndarray, np.ndarray, float]:
    """加载 JSONL，返回 (amp_matrix, phase_matrix, fs)。

    amp_matrix: (T, 72) — 假设已高通滤波的幅值
    phase_matrix: (T, 72) — 假设已 unwrap+高通滤波的相位
    """
    with open(filepath, encoding="utf-8") as fh:
        frames = [json.loads(line) for line in fh if line.strip()]

    all_ch = sorted({c for f in frames for c in f.get("channels", {})}, key=_ch_sort)
    T = len(frames)
    N = len(all_ch)

    amp = np.full((T, N), np.nan)
    phs = np.full((T, N), np.nan)
    ts = np.full(T, np.nan)

    for i, f in enumerate(frames):
        ts[i] = f.get("timestamp_ms", np.nan)
        cd = f.get("channels", {})
        for j, ch in enumerate(all_ch):
            m = _find_ch(cd, ch)
            if m is not None:
                amp[i, j] = cd[m].get("amplitude", np.nan)
                phs[i, j] = cd[m].get("phase", np.nan)

    vt = ts[~np.isnan(ts)]
    fs = 1000.0 / float(np.mean(np.diff(vt))) if len(vt) >= 2 else 2.0
    print(f"✓ {Path(filepath).name}: {T} 帧 × {N} 信道, fs≈{fs:.1f} Hz")
    return amp, phs, fs


def _prep_col_phase(col: np.ndarray) -> np.ndarray:
    v = ~np.isnan(col)
    if v.sum() < 2:
        return np.zeros(len(col))
    x = np.arange(len(col))
    return np.interp(x, x[v], col[v])


def quick_filter(amp: np.ndarray, phs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """最简预处理：逐列 unwrap(相位) + 中值去脉冲 + 去均值高通等效。

    注意：这是教学简化版。实际项目使用 Butterworth highpass filtfilt。
    对于演示目的，去均值 + 中值滤波已足够展示 PCA 流程。
    """
    T, N = amp.shape

    def _prep_col(col: np.ndarray) -> np.ndarray:
        v = ~np.isnan(col)
        if v.sum() < 2:
            return np.zeros(T)
        x = np.arange(T)
        c = np.interp(x, x[v], col[v])
        c = _medfilt(c, size=3)
        return c - np.mean(c)

    amp_out = np.column_stack([_prep_col(amp[:, j]) for j in range(N)])
    phs_out = np.column_stack([_prep_col(np.unwrap(_prep_col_phase(phs[:, j]))) for j in range(N)])
    return amp_out, phs_out


# ═══════════════════════════════════════════════════════════════════
# PCA 核心
# ═══════════════════════════════════════════════════════════════════

def _zscore(X: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """按列 z-score: (x - μ) / σ"""
    mu = np.mean(X, axis=0, keepdims=True)
    sigma = np.std(X, axis=0, ddof=1, keepdims=True)
    sigma[sigma < eps] = 1.0
    return (X - mu) / sigma


def pca_real(X: np.ndarray, min_ch: int = 4) -> tuple[np.ndarray, dict]:
    """
    实矩阵 PCA — 从多信道幅值提取 PC1 呼吸波形。

    X: (M, N), M=帧, N=信道 (已滤波)
    算法: z-score → C = ZᵀZ/(M−1) → eigh(C) → PC1 = Z·v₁

    Returns (pc1, info) — info 含 pc1_variance_ratio, explained_variance_ratio
    """
    eps = 1e-12
    info = {"pc1_variance_ratio": np.nan, "explained_variance_ratio": [], "warn": []}

    if X is None or X.size == 0 or X.shape[1] < min_ch:
        return np.full(X.shape[0], np.nan), info
    if not np.all(np.isfinite(X)):
        return np.full(X.shape[0], np.nan), info

    M, N = X.shape
    Z = _zscore(X, eps)          # z-score 消除信道间幅值差异

    C = (Z.T @ Z) / max(M - 1, 1)                # N×N 协方差矩阵
    eigvals, eigvecs = np.linalg.eigh(C)          # 特征分解 (升序)
    eigvals = eigvals[::-1]
    eigvecs = eigvecs[:, ::-1]                    # 降序

    total = float(np.sum(eigvals))
    ratios = eigvals / total if total > eps else np.ones(N) / max(N, 1)
    info["explained_variance_ratio"] = ratios.tolist()
    info["pc1_variance_ratio"] = float(ratios[0]) if N > 0 else np.nan

    if info["pc1_variance_ratio"] < 0.10:
        info["warn"].append(f"PC1 方差占比={info['pc1_variance_ratio']:.3f} < 0.10")

    pc1 = Z @ eigvecs[:, 0]    # 投影到第一主成分
    return pc1, info


def pca_complex(X_c: np.ndarray, min_ch: int = 4) -> tuple[np.ndarray, dict]:
    """
    复矩阵 PCA — A·e^(jφ) 联合幅相信息。

    X_c: (M, N), dtype complex, X_c[i,j] = Aᵢⱼ · exp(j·φᵢⱼ)
    算法: 列中心化 → Hermitian C = ZᴴZ/(M−1) → eigh(C) → Re(Z·v₁)

    ⚠ 取 Re(PC1), 非 |PC1| — 后者产生倍频。
    """
    eps = 1e-12
    info = {"pc1_variance_ratio": np.nan, "explained_variance_ratio": [], "warn": []}

    if X_c is None or X_c.size == 0 or X_c.shape[1] < min_ch:
        return np.full(X_c.shape[0], np.nan), info

    M, N = X_c.shape
    Z = X_c.astype(complex) - np.mean(X_c.astype(complex), axis=0, keepdims=True)

    C = (Z.conj().T @ Z) / max(M - 1, 1)           # Hermitian 协方差
    eigvals, eigvecs = np.linalg.eigh(C)
    eigvals = eigvals[::-1].real
    eigvecs = eigvecs[:, ::-1]

    total = float(np.sum(eigvals))
    ratios = eigvals / total if total > eps else np.ones(N) / max(N, 1)
    info["explained_variance_ratio"] = ratios.tolist()
    info["pc1_variance_ratio"] = float(ratios[0]) if N > 0 else np.nan

    if info["pc1_variance_ratio"] < 0.10:
        info["warn"].append(f"复 PC1 方差占比={info['pc1_variance_ratio']:.3f} < 0.10")

    pc1 = Z @ eigvecs[:, 0]
    return np.real(pc1), info


# ═══════════════════════════════════════════════════════════════════
# BPM 估计
# ═══════════════════════════════════════════════════════════════════

def estimate_bpm(wf: np.ndarray, fs: float,
                 lo: float = 0.1, hi: float = 0.35) -> tuple[float, np.ndarray, np.ndarray]:
    """Hanning FFT → 呼吸带 (0.1–0.35 Hz) 峰频 → BPM (parabolic 插值)。"""
    if len(wf) < 4 or not np.all(np.isfinite(wf)):
        return np.nan, np.array([]), np.array([])

    nfft = 2 ** int(np.ceil(np.log2(4 * len(wf))))
    seg = wf - np.mean(wf)
    if np.std(seg) < 1e-12:
        return np.nan, np.array([]), np.array([])

    power = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n=nfft)) ** 2
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)

    mask = (freqs >= lo) & (freqs <= hi)
    if not np.any(mask):
        return np.nan, freqs, power

    bp, bf = power[mask], freqs[mask]
    k = int(np.argmax(bp))
    f = float(bf[k])

    if 0 < k < len(bp) - 1:                    # parabolic 精化
        y0, y1, y2 = bp[k-1], bp[k], bp[k+1]
        denom = y0 - 2*y1 + y2
        if abs(denom) > 1e-12:
            f = float(bf[k] + 0.5 * (y0 - y2) / denom * (bf[1] - bf[0]))

    return 60.0 * f, freqs, power


# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════

def run(data_path: str):
    print("═" * 60)
    print("  BLE CS PCA 呼吸波形提取")
    print("═" * 60)

    # ── 加载 + 最简预处理 ──
    amp, phs, fs = load_data(data_path)
    amp_hp, phs_hp = quick_filter(amp, phs)
    T, N = amp.shape

    # ── 选窗 (20 s) ──
    win = int(round(20.0 * fs))
    if T < win:
        win = T
    st = (T - win) // 2
    end = st + win
    t = np.arange(win) / fs
    print(f"  窗口: {win} 帧 ≈ {win/fs:.0f} s")

    # ── 实 PCA 矩阵 ──
    Xr = amp_hp[st:end, :]
    ok_r = [j for j in range(N) if np.all(np.isfinite(Xr[:, j]))]
    Xr = Xr[:, ok_r]

    # ── 复 PCA 矩阵 ──
    ok_c = [j for j in range(N)
            if np.all(np.isfinite(amp_hp[st:end, j]))
            and np.all(np.isfinite(phs_hp[st:end, j]))]
    Xc = np.column_stack([
        amp_hp[st:end, j] * np.exp(1j * phs_hp[st:end, j]) for j in ok_c
    ])

    # ── PCA ──
    print("\n── 实 PCA ──")
    wf_r, ir = pca_real(Xr)
    bpm_r, fr, pr = estimate_bpm(wf_r, fs)
    print(f"  PC1 方差占比: {ir['pc1_variance_ratio']:.3f}  |  "
          f"前3: {[f'{v:.3f}' for v in ir['explained_variance_ratio'][:3]]}")

    print("\n── 复 PCA ──")
    wf_c, ic = pca_complex(Xc)
    bpm_c, fc, pc = estimate_bpm(wf_c, fs)
    print(f"  PC1 方差占比: {ic['pc1_variance_ratio']:.3f}  |  "
          f"前3: {[f'{v:.3f}' for v in ic['explained_variance_ratio'][:3]]}")

    corr = np.corrcoef(wf_r, wf_c)[0, 1] if len(wf_r) > 1 else np.nan

    # ── 可视化 (2×2) ──
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"BLE CS PCA 呼吸波形提取  |  {Path(data_path).name}  |  "
                 f"{win/fs:.0f}s 窗  |  {len(ok_c)} 信道  |  fs={fs:.1f} Hz",
                 fontsize=12, fontweight="bold")

    # [0,0] 幅值热力图
    ax = axes[0, 0]
    v = np.std(Xr) * 3
    im = ax.imshow(Xr.T, aspect="auto", cmap="RdBu_r", interpolation="none",
                   vmin=-v, vmax=v)
    ax.set_title(f"高通幅值矩阵 ({Xr.shape[0]} 帧 × {Xr.shape[1]} 信道)")
    ax.set_xlabel("时间帧"); ax.set_ylabel("Tone 序号")
    plt.colorbar(im, ax=ax, shrink=0.8)

    # [0,1] 方差占比
    ax = axes[0, 1]
    kk = min(20, len(ir["explained_variance_ratio"]))
    xx = np.arange(1, kk+1)
    w = 0.35
    ax.bar(xx - w/2, ir["explained_variance_ratio"][:kk], w,
           color="#5A9BD5", alpha=0.85, label="实 PCA (幅值)")
    ax.bar(xx + w/2, ic["explained_variance_ratio"][:kk], w,
           color="#ED7D31", alpha=0.85, label="复 PCA (幅值+相位)")
    ax.set_title(f"PCA 方差占比 (前 {kk})")
    ax.set_xlabel("主成分"); ax.set_ylabel("方差占比")
    ax.legend(fontsize=8); ax.grid(True, alpha=0.25, axis="y")
    ax.set_xticks(xx[::2])

    # [1,0] 频谱
    ax = axes[1, 0]
    a, b = int(np.searchsorted(fr, 0.04)), int(np.searchsorted(fr, 0.55))
    ax.plot(fr[a:b] * 60, pr[a:b] / (pr[a:b].max() + 1e-12),
            color="#5A9BD5", lw=1.5, label="实 PCA")
    ax.plot(fc[a:b] * 60, pc[a:b] / (pc[a:b].max() + 1e-12),
            color="#ED7D31", lw=1.5, label="复 PCA")
    for bpm_v, clr, lbl in [
        (bpm_r, "#2E6F9E", f"实: {bpm_r:.1f} BPM"),
        (bpm_c, "#C44E52", f"复: {bpm_c:.1f} BPM"),
    ]:
        if np.isfinite(bpm_v):
            ax.axvline(bpm_v, color=clr, ls="--", lw=1.3, label=lbl)
    ax.axvspan(6, 21, color="green", alpha=0.05)
    ax.set_xlabel("BPM"); ax.set_ylabel("归一化功率")
    ax.set_title("PC1 频谱对比"); ax.legend(fontsize=7)
    ax.grid(True, alpha=0.25); ax.set_xlim(0, 45)

    # [1,1] 波形
    ax = axes[1, 1]
    ax.plot(t, wf_r / np.std(wf_r), color="#5A9BD5", lw=1.5, label=f"实 PCA PC1")
    ax.plot(t, wf_c / np.std(wf_c), color="#ED7D31", lw=1.5, label=f"复 PCA PC1")
    ax.set_xlabel("时间 (s)"); ax.set_ylabel("标准化波形")
    ax.set_title(f"PC1 波形对比  (r={corr:.3f})")
    ax.legend(fontsize=8); ax.grid(True, alpha=0.25)

    plt.tight_layout()

    # 保存
    sd = Path(__file__).resolve()
    proj = sd
    for p in [sd, *sd.parents]:
        if (p / "outputs").is_dir():
            proj = p; break
    out = proj / "outputs" / "figures" / "pca_demo.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\n✓ 图表: {out}")

    print(f"\n{'═' * 60}")
    print(f"  实 PCA: PC1占比={ir['pc1_variance_ratio']:.3f}  BPM={bpm_r:.1f}")
    print(f"  复 PCA: PC1占比={ic['pc1_variance_ratio']:.3f}  BPM={bpm_c:.1f}")
    print(f"  相关系数: r={corr:.3f}")
    print(f"{'═' * 60}")
    plt.show()


if __name__ == "__main__":
    sd = Path(__file__).resolve().parent
    proj = sd
    for p in [sd, *sd.parents]:
        if (p / "sampleData").is_dir():
            proj = p; break

    default = proj / "sampleData" / "CS_frames_all_20260113_091339.jsonl"

    if len(sys.argv) > 1:
        dp = sys.argv[1]
    elif default.exists():
        dp = str(default)
        print(f"▸ {Path(dp).name}\n")
    else:
        print("用法: python pca_demo.py [CS_frames_*.jsonl]")
        sys.exit(1)

    run(dp)
