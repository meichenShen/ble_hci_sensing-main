# 文章 Method 主线

你可以把方法写成下面这个结构。

------

## 1.1 BLE CS respiratory signal extraction

假设 BLE CS 在每个时间点 $n$ 和信道 $c$ 上给出复数观测：

$z_c[n] = A_c[n]e^{j\phi_c[n]}.$

呼吸导致胸腔周期性微位移，因此会引起相位或等效距离观测的周期性变化。对每个信道提取相位：

$\phi_c[n] = \operatorname{unwrap}\left(\angle z_c[n]\right).$

然后做去趋势和呼吸频带滤波。呼吸频带可以设为：

$\mathcal{B} = [0.1, 0.55]\ \mathrm{Hz},$

也就是大约 $6\sim33$ BPM。

------

## 1.2 Per-channel respiratory spectrum

对每个滑动窗口内的每个信道做 FFT，得到功率谱：

$P_c(f) = \left|\operatorname{FFT}\{x_c[n]\}\right|^2,\quad f\in\mathcal{B}.$

为了避免某个信道仅仅因为幅度大而主导融合，对每个信道频谱做归一化：

$\bar{P}_c(f) = \frac{P_c(f)} {\sum_{f\in\mathcal{B}}P_c(f)+\epsilon}.$

------

## 1.3 Compact channel quality score

不要设计太多 $q$ 子项。初版建议只保留三个：

$q_c = \left( q_{\mathrm{valid},c} q_{\mathrm{peak},c} q_{\phi,c} \right)^{1/3}.$

其中：

| 子项                   | 含义                               | 是否必要 |
| ---------------------- | ---------------------------------- | -------- |
| $q_{\mathrm{valid},c}$ | 当前窗口内有效采样比例             | 必要     |
| $q_{\mathrm{peak},c}$  | 呼吸频带内峰值是否突出             | 必要     |
| $q_{\phi,c}$           | 相位是否存在大量突变或 unwrap 异常 | 建议保留 |

其中 $q_{\mathrm{peak},c}$ 可以定义为峰值与频带内噪声地板的比值：

$\rho_c = \frac{ \max_{f\in\mathcal{B}}P_c(f) }{ \operatorname{median}_{f\in\mathcal{B}}P_c(f)+\epsilon }.$

然后把 $\rho_c$ 映射到 $[0,1]$：

$q_{\mathrm{peak},c} = \operatorname{clip} \left( \frac{\log \rho_c-\log \rho_{\min}} {\log \rho_{\mathrm{good}}-\log \rho_{\min}}, 0,1 \right).$

这个就够了。不要再额外加 shape、residual、artifact 等等，除非实验真的需要。

------

## 1.4 Quality-weighted frequency fusion

最终融合频谱为：

$S(f) = \sum_c w_c \bar{P}_c(f),$

其中：

$w_c = \frac{q_c+\epsilon} {\sum_j q_j + C\epsilon}.$

呼吸频率估计为：

$\hat{f} = \arg\max_{f\in\mathcal{B}}S(f),$

$\hat{R}=60\hat{f}.$

这里 $\hat{R}$ 的单位是 BPM。

------

## 1.5 Optional: spectral consensus refinement

如果你想保留 SC-CFF，可以把它写成可选的轻量 refinement，而不是一个很大的独立模块。

每个信道先有自己的峰值：

$f_c^\star = \arg\max_{f\in\mathcal{B}}\bar{P}_c(f).$

然后用 $q_c$ 加权中位数或加权平均得到一个 consensus frequency：

$\tilde{f} = \operatorname{WeightedMedian}\left(f_c^\star; q_c\right).$

然后定义一个 soft consensus gate：

$g_c = \exp \left( -\frac{(f_c^\star-\tilde{f})^2}{2\sigma_f^2} \right).$

最终融合变成：

$S(f) = \sum_c w_c g_c \bar{P}_c(f).$

如果你不想用 SC-CFF，就令：

$g_c=1.$

**这就是最简洁的设计。**

------

# 2. 初版推荐的算法版本

我建议你初版正文只放这几个版本：

| 方法              | 说明                              |
| ----------------- | --------------------------------- |
| FFT-single        | 单信道 FFT                        |
| FFT-uniform       | 多信道 FFT 频谱平均               |
| FFT+$q$           | 多信道 FFT + compact $q$ 加权融合 |
| FFT+$q$+consensus | 可选，如果确实有明显提升          |

所以不是完全不用 SC-CFF，而是：

> **先把 FFT+$q$ 做成主方法。如果 SC-CFF 有明显额外收益，再作为 enhanced version；否则别放主文。**

------

# 3. 一段可直接改的 Python 代码

下面这段代码实现的是：

```text
BLE CS phase/complex signal
→ unwrap
→ bandpass
→ sliding-window FFT
→ compact q score
→ q-weighted fusion
→ optional consensus
→ 输出每个窗口的 BPM
import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any

try:
    from scipy.signal import butter, sosfiltfilt
    SCIPY_AVAILABLE = True
except Exception:
    SCIPY_AVAILABLE = False


@dataclass
class RRConfig:
    band_bpm: Tuple[float, float] = (6.0, 33.0)
    window_sec: float = 30.0
    hop_sec: float = 5.0
    nfft: Optional[int] = None

    # Quality score settings
    min_valid_frac: float = 0.70
    peak_snr_min: float = 1.5
    peak_snr_good: float = 6.0
    phase_jump_rad: float = 1.2
    jump_rate_good: float = 0.05

    # Optional consensus
    enable_consensus: bool = False
    consensus_sigma_bpm: float = 2.0

    # Numerical stability
    eps: float = 1e-12


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
    snr = max(float(snr), eps)
    numerator = np.log(snr) - np.log(snr_min)
    denominator = np.log(snr_good) - np.log(snr_min) + eps
    return float(np.clip(numerator / denominator, 0.0, 1.0))


def _fallback_fft_bandpass(x: np.ndarray, fs: float, low_hz: float, high_hz: float) -> np.ndarray:
    """Fallback bandpass when scipy is unavailable."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    x0 = x - np.mean(x)

    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    X = np.fft.rfft(x0)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    X_filtered = X * mask
    return np.fft.irfft(X_filtered, n=n)


def _bandpass_1d(x: np.ndarray, fs: float, low_hz: float, high_hz: float) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    x = x - np.mean(x)

    if len(x) < max(16, int(3 * fs)):
        return x

    if SCIPY_AVAILABLE:
        try:
            sos = butter(
                N=4,
                Wn=[low_hz, high_hz],
                btype="bandpass",
                fs=fs,
                output="sos",
            )
            return sosfiltfilt(sos, x)
        except Exception:
            return _fallback_fft_bandpass(x, fs, low_hz, high_hz)

    return _fallback_fft_bandpass(x, fs, low_hz, high_hz)


def _prepare_phase_or_signal(
    data: np.ndarray,
    valid_mask: Optional[np.ndarray],
    unwrap_phase: bool,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Returns:
        raw_unwrapped_or_signal: shape [N, C]
        valid: shape [N, C]
    """
    z = np.asarray(data)

    if z.ndim == 1:
        z = z[:, None]

    n, c = z.shape

    if valid_mask is None:
        if np.iscomplexobj(z):
            valid = np.isfinite(z.real) & np.isfinite(z.imag)
        else:
            valid = np.isfinite(z)
    else:
        valid = np.asarray(valid_mask).astype(bool)
        if valid.ndim == 1:
            valid = valid[:, None]
        if valid.shape != (n, c):
            raise ValueError("valid_mask must have the same shape as data.")

    if np.iscomplexobj(z):
        base = np.angle(z)
        do_unwrap = True
    else:
        base = z.astype(float)
        do_unwrap = unwrap_phase

    raw = np.full((n, c), np.nan, dtype=float)
    idx = np.arange(n)

    for ch in range(c):
        good = valid[:, ch] & np.isfinite(base[:, ch])

        if np.sum(good) < 2:
            continue

        values = base[good, ch]

        if do_unwrap:
            values = np.unwrap(values)

        raw[:, ch] = np.interp(idx, idx[good], values)

    return raw, valid


def estimate_respiration_rate(
    data: np.ndarray,
    fs: float,
    valid_mask: Optional[np.ndarray] = None,
    config: Optional[RRConfig] = None,
    unwrap_phase: bool = True,
) -> List[Dict[str, Any]]:
    """
    Estimate respiration rate from BLE CS phase or complex observations.

    Args:
        data:
            Shape [N, C].
            Can be complex BLE CS observations or real-valued phase/displacement.
        fs:
            Sampling rate in Hz.
        valid_mask:
            Optional boolean mask with shape [N, C].
        config:
            RRConfig object.
        unwrap_phase:
            If data is real-valued phase, set True.
            If data is already displacement/range-like signal, set False.

    Returns:
        A list of dictionaries. Each dictionary is one sliding-window estimate.
    """
    cfg = config or RRConfig()

    if fs <= 0:
        raise ValueError("fs must be positive.")

    low_hz = cfg.band_bpm[0] / 60.0
    high_hz = cfg.band_bpm[1] / 60.0

    raw, valid = _prepare_phase_or_signal(data, valid_mask, unwrap_phase=unwrap_phase)

    n, num_channels = raw.shape

    # Bandpass each channel.
    x = np.full_like(raw, np.nan, dtype=float)
    for ch in range(num_channels):
        if np.sum(np.isfinite(raw[:, ch])) < 2:
            continue
        x[:, ch] = _bandpass_1d(raw[:, ch], fs, low_hz, high_hz)

    win_len = int(round(cfg.window_sec * fs))
    hop_len = int(round(cfg.hop_sec * fs))

    if win_len <= 4:
        raise ValueError("window_sec is too short for the given fs.")
    if hop_len <= 0:
        raise ValueError("hop_sec is too short for the given fs.")
    if n < win_len:
        raise ValueError("data length is shorter than one analysis window.")

    nfft = cfg.nfft or _next_pow2(4 * win_len)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    band_mask = (freqs >= low_hz) & (freqs <= high_hz)
    band_freqs = freqs[band_mask]

    if np.sum(band_mask) < 3:
        raise ValueError("Too few FFT bins in respiration band. Increase window_sec or nfft.")

    hann = np.hanning(win_len)
    results: List[Dict[str, Any]] = []

    for start in range(0, n - win_len + 1, hop_len):
        end = start + win_len
        mid = (start + end) / 2.0 / fs

        spectra = []
        qualities = []
        peak_freqs = []
        details = []

        for ch in range(num_channels):
            seg = x[start:end, ch]
            raw_seg = raw[start:end, ch]
            valid_seg = valid[start:end, ch]

            if not np.all(np.isfinite(seg)):
                spectra.append(np.zeros_like(band_freqs))
                qualities.append(0.0)
                peak_freqs.append(np.nan)
                details.append({
                    "q_valid": 0.0,
                    "q_peak": 0.0,
                    "q_phi": 0.0,
                    "peak_snr": 0.0,
                })
                continue

            valid_frac = float(np.mean(valid_seg))
            q_valid = np.clip(
                (valid_frac - cfg.min_valid_frac) / (1.0 - cfg.min_valid_frac + cfg.eps),
                0.0,
                1.0,
            )

            seg = seg - np.mean(seg)
            if np.std(seg) < cfg.eps:
                P_band = np.zeros_like(band_freqs)
                peak_snr = 0.0
                q_peak = 0.0
                f_peak = np.nan
            else:
                X = np.fft.rfft(seg * hann, n=nfft)
                P = np.abs(X) ** 2
                P_band = P[band_mask]

                peak_power = float(np.max(P_band))
                noise_floor = float(np.median(P_band) + cfg.eps)
                peak_snr = peak_power / noise_floor
                q_peak = _quality_from_snr(
                    peak_snr,
                    cfg.peak_snr_min,
                    cfg.peak_snr_good,
                    cfg.eps,
                )
                f_peak = float(band_freqs[int(np.argmax(P_band))])

            # Phase consistency.
            # If input is displacement-like and unwrap_phase=False, this term is less meaningful.
            if unwrap_phase or np.iscomplexobj(data):
                dphi = np.diff(raw_seg)
                dphi = dphi[np.isfinite(dphi)]
                if len(dphi) == 0:
                    q_phi = 0.0
                    jump_rate = 1.0
                else:
                    jump_rate = float(np.mean(np.abs(dphi) > cfg.phase_jump_rad))
                    q_phi = float(np.exp(-jump_rate / (cfg.jump_rate_good + cfg.eps)))
            else:
                jump_rate = 0.0
                q_phi = 1.0

            q = float((q_valid * q_peak * q_phi + cfg.eps) ** (1.0 / 3.0))

            P_norm = P_band / (np.sum(P_band) + cfg.eps)

            spectra.append(P_norm)
            qualities.append(q)
            peak_freqs.append(f_peak)
            details.append({
                "q_valid": q_valid,
                "q_peak": q_peak,
                "q_phi": q_phi,
                "peak_snr": peak_snr,
                "jump_rate": jump_rate,
                "valid_frac": valid_frac,
            })

        spectra_arr = np.vstack(spectra)
        q_arr = np.asarray(qualities, dtype=float)
        peak_freqs_arr = np.asarray(peak_freqs, dtype=float)

        if np.sum(q_arr) <= cfg.eps:
            # Fallback: uniform weights if all quality scores collapse.
            weights = np.ones(num_channels) / num_channels
            consensus_bpm = np.nan
        else:
            q_eff = q_arr.copy()
            consensus_bpm = np.nan

            if cfg.enable_consensus:
                consensus_hz = _weighted_median(peak_freqs_arr, q_arr)
                consensus_bpm = 60.0 * consensus_hz

                sigma_hz = cfg.consensus_sigma_bpm / 60.0
                gate = np.exp(-0.5 * ((peak_freqs_arr - consensus_hz) / (sigma_hz + cfg.eps)) ** 2)
                gate[~np.isfinite(gate)] = 0.0

                q_eff = q_arr * gate

                # If consensus is too aggressive, fall back to q only.
                if np.sum(q_eff) <= cfg.eps:
                    q_eff = q_arr.copy()

            weights = q_eff / (np.sum(q_eff) + cfg.eps)

        fused = np.sum(weights[:, None] * spectra_arr, axis=0)

        k = int(np.argmax(fused))
        f_hat = float(band_freqs[k])

        # Parabolic peak interpolation for smoother BPM estimates.
        if 0 < k < len(fused) - 1:
            y0, y1, y2 = fused[k - 1], fused[k], fused[k + 1]
            denom = y0 - 2.0 * y1 + y2
            if abs(denom) > cfg.eps:
                delta = 0.5 * (y0 - y2) / denom
                df = band_freqs[1] - band_freqs[0]
                f_hat = float(band_freqs[k] + delta * df)

        bpm = 60.0 * f_hat
        confidence = float(np.max(fused) / (np.median(fused) + cfg.eps))

        results.append({
            "t_start_sec": start / fs,
            "t_end_sec": end / fs,
            "t_mid_sec": mid,
            "bpm": bpm,
            "freq_hz": f_hat,
            "confidence": confidence,
            "mean_q": float(np.mean(q_arr)),
            "max_q": float(np.max(q_arr)),
            "best_channel": int(np.argmax(q_arr)),
            "weights": weights,
            "channel_quality": q_arr,
            "channel_peak_bpm": 60.0 * peak_freqs_arr,
            "consensus_bpm": consensus_bpm,
            "details": details,
        })

    return results


def evaluate_paced_trials(
    estimates: List[Dict[str, Any]],
    trials: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Evaluate against paced breathing targets.

    Args:
        estimates:
            Output of estimate_respiration_rate().
        trials:
            Example:
            [
                {"name": "S01_12bpm", "start_sec": 0, "end_sec": 120, "target_bpm": 12},
                {"name": "S01_16bpm", "start_sec": 140, "end_sec": 260, "target_bpm": 16},
            ]

    Returns:
        per_trial_summary, overall_summary
    """
    mids = np.asarray([e["t_mid_sec"] for e in estimates], dtype=float)
    bpms = np.asarray([e["bpm"] for e in estimates], dtype=float)

    per_trial = []
    all_errors = []

    for tr in trials:
        name = tr.get("name", "trial")
        start = float(tr["start_sec"])
        end = float(tr["end_sec"])
        target = float(tr["target_bpm"])

        mask = (mids >= start) & (mids <= end) & np.isfinite(bpms)
        y = bpms[mask]

        if len(y) == 0:
            per_trial.append({
                "name": name,
                "target_bpm": target,
                "n_windows": 0,
                "mean_bpm": np.nan,
                "std_bpm": np.nan,
                "bias_bpm": np.nan,
                "mae_bpm": np.nan,
                "rmse_bpm": np.nan,
                "acc_2bpm": np.nan,
                "outlier_5bpm": np.nan,
            })
            continue

        err = y - target
        all_errors.extend(err.tolist())

        per_trial.append({
            "name": name,
            "target_bpm": target,
            "n_windows": int(len(y)),
            "mean_bpm": float(np.mean(y)),
            "std_bpm": float(np.std(y, ddof=1)) if len(y) > 1 else 0.0,
            "bias_bpm": float(np.mean(err)),
            "mae_bpm": float(np.mean(np.abs(err))),
            "rmse_bpm": float(np.sqrt(np.mean(err ** 2))),
            "acc_2bpm": float(np.mean(np.abs(err) <= 2.0)),
            "outlier_5bpm": float(np.mean(np.abs(err) > 5.0)),
        })

    all_errors = np.asarray(all_errors, dtype=float)

    if len(all_errors) == 0:
        overall = {
            "n_windows": 0,
            "bias_bpm": np.nan,
            "mae_bpm": np.nan,
            "rmse_bpm": np.nan,
            "acc_2bpm": np.nan,
            "outlier_5bpm": np.nan,
        }
    else:
        overall = {
            "n_windows": int(len(all_errors)),
            "bias_bpm": float(np.mean(all_errors)),
            "mae_bpm": float(np.mean(np.abs(all_errors))),
            "rmse_bpm": float(np.sqrt(np.mean(all_errors ** 2))),
            "acc_2bpm": float(np.mean(np.abs(all_errors) <= 2.0)),
            "outlier_5bpm": float(np.mean(np.abs(all_errors) > 5.0)),
        }

    return per_trial, overall


# ---------------- Example usage ----------------
if __name__ == "__main__":
    # data shape: [N, C]
    # It can be complex BLE CS observations or real-valued phase.
    # Here we create fake data only for API demonstration.
    fs = 10.0
    duration = 180.0
    t = np.arange(int(duration * fs)) / fs
    target_bpm = 15.0
    f0 = target_bpm / 60.0

    num_channels = 8
    phase = np.zeros((len(t), num_channels))
    rng = np.random.default_rng(0)

    for c in range(num_channels):
        amp = 0.5 + 0.2 * rng.random()
        noise = 0.2 * rng.standard_normal(len(t))
        phase[:, c] = amp * np.sin(2 * np.pi * f0 * t + 0.2 * c) + noise

    cfg = RRConfig(
        window_sec=30.0,
        hop_sec=5.0,
        enable_consensus=False,  # Start with False for the simpler method.
    )

    estimates = estimate_respiration_rate(
        data=phase,
        fs=fs,
        valid_mask=None,
        config=cfg,
        unwrap_phase=True,
    )

    trials = [
        {
            "name": "demo_15bpm",
            "start_sec": 0,
            "end_sec": 180,
            "target_bpm": 15.0,
        }
    ]

    per_trial, overall = evaluate_paced_trials(estimates, trials)

    print("First five estimates:")
    for e in estimates[:5]:
        print({k: e[k] for k in ["t_mid_sec", "bpm", "confidence", "mean_q", "best_channel"]})

    print("\nPer-trial summary:")
    for row in per_trial:
        print(row)

    print("\nOverall summary:")
    print(overall)
```

------

# 4. 你这篇文章的实验预期结论应该是什么？

你不需要让每个实验都证明一个复杂模块。你的实验结论应该围绕下面几件事。

------

## 4.1 金属板实验预期结论

金属板实验主要证明系统和算法的基本可行性。

预期结论：

1. BLE CS 相位/信道观测中确实存在与周期微位移一致的频谱峰；
2. 估计频率与电机/平台设定频率基本线性一致；
3. 多信道融合比单信道 FFT 更稳定；
4. $q$-weighted fusion 可以降低坏信道造成的频率跳变；
5. 金属板实验中的标准差应明显低于真人实验。

这个实验不需要太复杂。建议：

```text
8, 12, 16, 20, 24 BPM
每个频率 2 min
每个频率重复 2 次
```

主要展示：

```text
target BPM vs estimated BPM
mean error
STD
```

------

## 4.2 真人 paced breathing 预期结论

真人实验才是核心。

预期结论：

1. 单信道 FFT 在部分受试者、部分姿态或低 SNR 条件下容易失败；
2. uniform fusion 有一定提升，但坏信道仍然会污染融合频谱；
3. compact $q$ weighted fusion 可以降低 MAE/RMSE 和 outlier rate；
4. 如果使用 consensus，它主要应该减少 $2\times$ harmonic 或 $0.5\times$ subharmonic 错误；
5. 方法在 $12\sim20$ BPM 中间频段通常最好，在 8 BPM 或 24 BPM 这种边缘频率可能稍差。

你最后可以得出这样的结论：

> Compared with single-channel FFT and uniform spectral fusion, the proposed compact quality-weighted fusion improves the robustness of BLE CS respiration-rate estimation, especially by suppressing unreliable channels and reducing large outliers.

------

## 4.3 消融实验预期结论

建议消融别太多。主表可以是：

| Method             | MAE            | RMSE           | Acc@2 BPM | Outlier@5 BPM |
| ------------------ | -------------- | -------------- | --------- | ------------- |
| Single-channel FFT | 高             | 高             | 低        | 高            |
| Uniform fusion FFT | 中             | 中             | 中        | 中            |
| FFT+$q$            | 低             | 低             | 高        | 低            |
| FFT+$q$+consensus  | 最低或接近最低 | 最低或接近最低 | 最高      | 最低          |

如果 consensus 没有明显提升，就不要强行放主文。可以在文中写：

> The compact quality-weighted fusion was selected as the final method because it achieved comparable accuracy with lower algorithmic complexity.

这个说法是合理的。

------

# 5. 关于呼吸节拍器和 MAE/RMSE

你这个担心其实可以分开看。

## 5.1 不需要原始呼吸波形也可以算 MAE/RMSE

如果受试者按照节拍器进行 paced breathing，比如：

```text
12 BPM
16 BPM
20 BPM
```

那么你每个窗口都有一个 target rate。比如当前 trial 是 16 BPM，那么每个窗口的误差就是：

$e_i = \hat{R}_i - 16.$

所以可以计算：

$\mathrm{MAE} = \frac{1}{N} \sum_i |\hat{R}_i - R_{\mathrm{target}}|,$

$\mathrm{RMSE} = \sqrt{ \frac{1}{N} \sum_i (\hat{R}_i - R_{\mathrm{target}})^2 }.$

这不需要原始呼吸波形。

但要注意：这个应该叫：

```text
target-referenced MAE
target-referenced RMSE
paced-rate error
```

而不要说成严格的 physiological ground-truth error。

因为受试者可能没有完全跟上节拍器。

------

## 5.2 用“呼吸率 + 标准差”可以，但不能只用这个

你可以报告：

```text
estimated rate mean ± STD
```

比如：

```text
Target 16 BPM: estimated 15.7 ± 0.8 BPM
```

这很有用，但是**不够**。

因为 STD 只说明稳定性，不说明准确性。一个方法如果一直输出 20 BPM，它的 STD 也可以很小，但它是错的。

所以建议每个 paced trial 报：

| 指标                        | 是否建议 |
| --------------------------- | -------- |
| Mean estimated BPM          | 必须     |
| STD of estimated BPM        | 必须     |
| Absolute error to target    | 必须     |
| Window-level MAE to target  | 建议     |
| Window-level RMSE to target | 建议     |
| Acc@2 BPM                   | 建议     |
| Outlier@5 BPM               | 建议     |

例如：

| Target | Mean ± STD | AE   | MAE  | RMSE | Acc@2 |
| ------ | ---------- | ---- | ---- | ---- | ----- |
| 12 BPM | 12.4 ± 0.7 | 0.4  | 0.8  | 1.0  | 95%   |
| 16 BPM | 15.7 ± 0.9 | 0.3  | 0.9  | 1.2  | 92%   |
| 20 BPM | 20.8 ± 1.1 | 0.8  | 1.2  | 1.5  | 88%   |

这样比只报 STD 更完整。

------

## 5.3 如果没有 reference waveform，spontaneous breathing 怎么办？

如果是 spontaneous breathing，并且没有呼吸带、胸带、相机标注、人工计数，那么你不能严格计算 MAE/RMSE。

这时你只能说：

```text
The method produces physiologically plausible and temporally stable respiration-rate estimates.
```

但不能说：

```text
The method is accurate.
```

所以我建议至少加一个很简单的参考：

1. 呼吸带；
2. 手机视频，人工数胸腹起伏；
3. 实验人员人工计数每分钟呼吸次数；
4. 低成本 respiration belt；
5. 让受试者继续 paced breathing，用节拍器作为 target。

对于 Sensors / IEEE Sensors Journal，paced breathing + 金属板可以支撑 proof-of-concept。
 但对于 TIM / Measurement，我会更建议加 reference sensor，否则测量严谨性会弱。

------

# 6. 我给你的最终建议

我建议你初版这样做：

```text
主方法：多信道 FFT + compact q weighted fusion
可选增强：consensus gate
不要主打复杂 SC-CFF
不要做大量 q 子项消融
```

实验这样安排：

```text
1. 金属板：验证频率可测性和稳定性
2. 真人 paced breathing：验证 target-rate accuracy
3. baseline comparison：single FFT, uniform FFT, FFT+q
4. optional ablation：FFT+q+consensus
```

指标这样安排：

```text
paced breathing:
    mean ± STD
    target-referenced MAE
    target-referenced RMSE
    Acc@2 BPM
    Outlier@5 BPM

metal plate:
    mean ± STD
    absolute error to driving frequency

spontaneous breathing:
    如果无 reference，只报趋势和稳定性
    如果有人工计数或呼吸带，可以报 MAE/RMSE
```

最关键的一句话是：

> **初版不要把算法做复杂，而要把“BLE CS 可以做呼吸感知”这件事证明扎实。**

如果 FFT+$q$ 已经明显优于 single FFT 和 uniform FFT，那这篇文章的主线就已经成立了。

# 其他验证

> **q_energy + q_peak 融合**（含 Top-K 变体）已实现，详见 [`chfusion_q_energy_peak.md`](chfusion_q_energy_peak.md)。

1. ~~top-K 验证~~（已实验，未纳入当前 3 方法 benchmark；见 git 历史 `chfusion_q_energy_peak.md` 旧版）
2. 怎么融合幅值和相位？1）同一信道的 a,p 取 q 高的那个 2）幅值相位分别算，整体出来后再选边融合。