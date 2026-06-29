



# WiFi-Sleep 呼吸估计算法复现报告

本文档聚焦 **WiFi-Sleep** 中与呼吸估计相关的信号处理流程，主要包括：

1. Wi-Fi CSI 与 CSI ratio；
2. 呼吸候选通道构造；
3. 呼吸频带滤波；
4. 基于 PSD 的 SNR 估计；
5. MRC 加权；
6. PCA 正反相校正；
7. MRC-PCA 融合得到高 SNR 呼吸波形；
8. ACF 自相关法估计呼吸率；
9. 呼吸深度、吸呼比、FIT 等呼吸形态特征提取；
10. 可直接改造用于复现的 Python 示例代码。

------

## 1. 方法目标

WiFi-Sleep 中呼吸估计算法的目标不是简单地从某一个 CSI 子载波中取频率峰值，而是：

> 从多天线、多子载波 Wi-Fi CSI ratio 信号中融合出一个高信噪比的呼吸波形，并从该波形中提取呼吸率及呼吸形态特征。

最终得到的呼吸相关输出包括：

| 输出                       | 含义                                                    |
| -------------------------- | ------------------------------------------------------- |
| respiration waveform       | 增强后的呼吸波形                                        |
| respiration rate           | 呼吸率，单位 bpm                                        |
| respiration rate variance  | 呼吸率变化程度                                          |
| respiration depth variance | 相对呼吸深度变化                                        |
| FIT                        | fractional inspiratory time，吸气时间占整个呼吸周期比例 |
| I/E ratio                  | inspiration-to-expiration ratio，吸气时间与呼气时间之比 |

核心处理链如下：

```text
Raw CSI
  ↓
Resampling
  ↓
CSI Ratio
  ↓
Amplitude / Phase Candidate Channels
  ↓
Bandpass Filtering
  ↓
SNR Estimation
  ↓
MRC Gain Calculation
  ↓
PCA Sign Correction
  ↓
MRC-PCA Fusion
  ↓
Respiration Waveform
  ↓
ACF Respiration Rate Estimation
  ↓
Respiration Feature Extraction
```

------

# 2. 输入数据形式

假设你已经通过 Intel 5300 CSI Tool 或类似工具采集到了 CSI。

常见 CSI 数据形式可以表示为：

```python
CSI.shape = [T, N_rx, N_sub]
```

其中：

| 维度    | 含义                             |
| ------- | -------------------------------- |
| `T`     | 时间采样点数                     |
| `N_rx`  | 接收天线数量，WiFi-Sleep 中为 3  |
| `N_sub` | 子载波数量，Intel 5300 通常为 30 |

每个 CSI 元素是复数：

```python
CSI[t, rx, sub] = amplitude * exp(1j * phase)
```

WiFi-Sleep 的典型硬件参数为：

| 参数       | 数值                |
| ---------- | ------------------- |
| Wi-Fi 频段 | 5 GHz               |
| 带宽       | 20 MHz              |
| 发包率     | 200 Hz              |
| 接收天线数 | 3                   |
| 发射天线数 | 1                   |
| 子载波数   | 30                  |
| CSI 工具   | Intel 5300 CSI Tool |

------

# 3. 预处理：重采样

## 3.1 为什么要重采样？

CSI 包的到达时间通常不均匀，原因包括：

1. 网络传输延迟；
2. 丢包；
3. 操作系统调度抖动；
4. 网卡采样时间不稳定。

而后续滤波、PSD、ACF 都要求相对均匀的采样间隔，因此需要把 CSI 重采样到固定采样率。

WiFi-Sleep 发包率为 200 Hz。复现时可以设：

```python
fs = 200.0
```

如果实际包到达时间不稳定，则应根据时间戳插值重采样。

------

## 3.2 重采样示例代码

```python
import numpy as np
from scipy.interpolate import interp1d

def resample_csi(csi, timestamps, fs=200.0):
    """
    将非均匀采样的 CSI 重采样到固定采样率。

    Parameters
    ----------
    csi : np.ndarray
        shape = [T, N_rx, N_sub]，复数 CSI。
    timestamps : np.ndarray
        shape = [T]，每个 CSI 包的时间戳，单位秒。
    fs : float
        目标采样率，默认 200 Hz。

    Returns
    -------
    csi_resampled : np.ndarray
        shape = [T_new, N_rx, N_sub]
    t_new : np.ndarray
        重采样后的时间轴。
    """
    t_start = timestamps[0]
    t_end = timestamps[-1]
    t_new = np.arange(t_start, t_end, 1.0 / fs)

    T, N_rx, N_sub = csi.shape
    csi_resampled = np.zeros((len(t_new), N_rx, N_sub), dtype=np.complex128)

    for rx in range(N_rx):
        for sub in range(N_sub):
            real_interp = interp1d(
                timestamps,
                np.real(csi[:, rx, sub]),
                kind="linear",
                bounds_error=False,
                fill_value="extrapolate"
            )
            imag_interp = interp1d(
                timestamps,
                np.imag(csi[:, rx, sub]),
                kind="linear",
                bounds_error=False,
                fill_value="extrapolate"
            )
            csi_resampled[:, rx, sub] = real_interp(t_new) + 1j * imag_interp(t_new)

    return csi_resampled, t_new
```

------

# 4. CSI Ratio

## 4.1 背景

原始 CSI 可以写成：

$H(f,t)=e^{-j\phi(t)} \left( H_s + A e^{-j2\pi d(t)/\lambda} \right)$

其中：

| 符号                        | 含义                                        |
| --------------------------- | ------------------------------------------- |
| $H_s$                       | 静态路径分量                                |
| $A e^{-j2\pi d(t)/\lambda}$ | 人体胸腔呼吸导致的动态路径分量              |
| $\phi(t)$                   | 由于 SFO、CFO、PBD 等引起的随机时变相位偏移 |

因为 $\phi(t)$ 的存在，原始 CSI phase 通常不可直接用于感知。

WiFi-Sleep 采用 **CSI ratio**：

$H_{\text{ratio}}(f,t) = \frac{H_1(f,t)}{H_2(f,t)}$

其中 $H_1$ 和 $H_2$ 是两个相邻接收天线在同一子载波上的 CSI。

如果两个天线共享类似的随机相位偏移，那么相除后共同相位项会被抵消。这样可以：

1. 抑制原始 CSI 中的共同相位误差；
2. 使 ratio phase 变得相对稳定；
3. 让 amplitude 和 phase 都可用于呼吸感知；
4. 降低只用 CSI amplitude 带来的 blind spot 问题。

------

## 4.2 天线对选择

如果有 3 根接收天线，可以构造：

```text
Rx0 / Rx1
Rx0 / Rx2
Rx1 / Rx2
```

或者只用相邻天线：

```text
Rx0 / Rx1
Rx1 / Rx2
```

论文中说使用一个发射天线和三个接收天线，Intel 5300 有 30 个子载波。实验部分提到使用 90 个子载波/通道，说明其最终融合规模约为：

```text
3 个接收通道 × 30 个子载波 = 90 个通道
```

在复现时，推荐做法是：

> 先构造所有天线 pair 的 CSI ratio，再根据 SNR 筛选或直接全部送入 MRC-PCA。

------

## 4.3 CSI ratio 示例代码

```python
import numpy as np

def compute_csi_ratio(csi, pairs=None, eps=1e-8):
    """
    计算 CSI ratio。

    Parameters
    ----------
    csi : np.ndarray
        shape = [T, N_rx, N_sub]，复数 CSI。
    pairs : list of tuple
        天线对，例如 [(0,1), (0,2), (1,2)]。
        若为 None，默认使用所有 rx_i / rx_j, i < j。
    eps : float
        防止除零的小常数。

    Returns
    -------
    ratio : np.ndarray
        shape = [T, N_pairs, N_sub]，复数 CSI ratio。
    pairs : list of tuple
        使用的天线对。
    """
    T, N_rx, N_sub = csi.shape

    if pairs is None:
        pairs = []
        for i in range(N_rx):
            for j in range(i + 1, N_rx):
                pairs.append((i, j))

    ratio = np.zeros((T, len(pairs), N_sub), dtype=np.complex128)

    for k, (i, j) in enumerate(pairs):
        ratio[:, k, :] = csi[:, i, :] / (csi[:, j, :] + eps)

    return ratio, pairs
```

------

# 5. 构造呼吸候选通道

## 5.1 Amplitude 与 Phase

CSI ratio 仍然是复数：

$H_{\text{ratio}}(f,t) = A_{\text{ratio}}(f,t)e^{j\theta_{\text{ratio}}(f,t)}$

因此可以得到：

```python
ratio_amp = np.abs(H_ratio)
ratio_phase = np.unwrap(np.angle(H_ratio))
```

其中：

| 信号            | 含义           |
| --------------- | -------------- |
| ratio amplitude | CSI ratio 幅度 |
| ratio phase     | CSI ratio 相位 |

论文认为 CSI ratio 的 amplitude 和 phase 对呼吸具有互补性。

这意味着：

```text
某些位置 amplitude 呼吸敏感，phase 不敏感；
某些位置 phase 呼吸敏感，amplitude 不敏感。
```

------

## 5.2 推荐的复现策略

由于论文没有给出非常明确的 amplitude-phase 拼接公式，复现时可以采用以下策略。

### 策略 A：幅度和相位全部作为候选通道

```text
候选通道 = 所有 ratio amplitude 通道 + 所有 ratio phase 通道
```

如果有：

```text
N_pairs 个天线对
N_sub 个子载波
```

则候选通道数为：

```text
2 × N_pairs × N_sub
```

其中 2 来自 amplitude 和 phase。

这是最充分利用幅相互补性的实现。

------

### 策略 B：分别处理幅度和相位，最后选择 SNR 更高者

```text
对 ratio amplitude 做 MRC-PCA，得到 waveform_amp
对 ratio phase 做 MRC-PCA，得到 waveform_phase
比较二者呼吸频带 SNR
选择 SNR 更高的 waveform
```

这种方式更稳健，便于调试。

------

### 策略 C：只用 ratio amplitude

如果暂时想简化复现，可以先只用 ratio amplitude：

```text
候选通道 = 所有 ratio amplitude
```

但这样无法充分体现论文中 amplitude-phase complementarity 的优势。

------

## 5.3 候选通道构造代码

```python
def build_candidate_channels(
    csi_ratio,
    use_amplitude=True,
    use_phase=True,
    detrend_mean=True
):
    """
    从 CSI ratio 构造呼吸候选通道。

    Parameters
    ----------
    csi_ratio : np.ndarray
        shape = [T, N_pairs, N_sub]，复数 CSI ratio。
    use_amplitude : bool
        是否使用 ratio amplitude。
    use_phase : bool
        是否使用 ratio phase。
    detrend_mean : bool
        是否对每个通道减均值。

    Returns
    -------
    X : np.ndarray
        shape = [T, N_channels]，实数候选通道矩阵。
    channel_info : list
        每个通道的信息，例如 ("amp", pair_idx, sub_idx)。
    """
    T, N_pairs, N_sub = csi_ratio.shape

    channels = []
    channel_info = []

    if use_amplitude:
        amp = np.abs(csi_ratio)
        for p in range(N_pairs):
            for s in range(N_sub):
                x = amp[:, p, s].astype(float)
                channels.append(x)
                channel_info.append(("amp", p, s))

    if use_phase:
        phase = np.unwrap(np.angle(csi_ratio), axis=0)
        for p in range(N_pairs):
            for s in range(N_sub):
                x = phase[:, p, s].astype(float)
                channels.append(x)
                channel_info.append(("phase", p, s))

    X = np.stack(channels, axis=1)

    if detrend_mean:
        X = X - np.mean(X, axis=0, keepdims=True)

    return X, channel_info
```

------

# 6. 呼吸频带滤波

## 6.1 为什么需要带通滤波？

MRC-PCA 前需要滤波，原因有三点：

1. 去除低频漂移；
2. 去除高频噪声；
3. 确保 PCA 主要对呼吸成分进行方向判断，而不是对噪声最大化。

------

## 6.2 呼吸频率范围

成人睡眠呼吸率通常大致在：

```text
10 bpm 到 30 bpm
```

换算成 Hz：

$10 \text{ bpm} = \frac{10}{60} \approx 0.167 \text{ Hz}$

$30 \text{ bpm} = \frac{30}{60} = 0.5 \text{ Hz}$

因此可设置：

```python
resp_low = 0.1    # Hz，对应 6 bpm
resp_high = 0.6   # Hz，对应 36 bpm
```

或者更保守：

```python
resp_low = 0.15   # Hz，对应 9 bpm
resp_high = 0.5   # Hz，对应 30 bpm
```

推荐复现参数：

```python
resp_band = (0.1, 0.6)
```

这样可以覆盖较宽的睡眠呼吸范围。

------

## 6.3 滤波器选择

推荐使用 Butterworth bandpass filter：

| 参数     | 推荐值                             |
| -------- | ---------------------------------- |
| 类型     | Butterworth                        |
| 阶数     | 3 或 4                             |
| 频带     | 0.1–0.6 Hz                         |
| 滤波方式 | `scipy.signal.filtfilt` 零相位滤波 |

使用 `filtfilt` 可以避免相位延迟。

------

## 6.4 滤波代码

```python
from scipy.signal import butter, filtfilt

def bandpass_filter(X, fs, low=0.1, high=0.6, order=4):
    """
    对多通道信号进行带通滤波。

    Parameters
    ----------
    X : np.ndarray
        shape = [T, N_channels]
    fs : float
        采样率。
    low : float
        低截止频率，Hz。
    high : float
        高截止频率，Hz。
    order : int
        Butterworth 滤波器阶数。

    Returns
    -------
    X_filt : np.ndarray
        滤波后的信号，shape = [T, N_channels]。
    """
    nyq = 0.5 * fs
    b, a = butter(order, [low / nyq, high / nyq], btype="bandpass")
    X_filt = filtfilt(b, a, X, axis=0)
    return X_filt
```

------

# 7. 基于 PSD 的 SNR 估计

## 7.1 背景

MRC 需要知道每个通道的 SNR。

但实际中无法直接分离：

```text
观测信号 = 呼吸信号 + 噪声
```

因此论文使用功率谱密度 PSD 来估计 SNR。

基本思想：

```text
呼吸频带内能量 ≈ 有效呼吸信号能量
呼吸频带外高频能量 ≈ 噪声能量
```

------

## 7.2 SNR 估计公式

对于第 $i$ 个通道 $x_i(t)$，其 PSD 为 $P_i(f)$。

可以定义：

$E_{\text{sig},i} = \int_{f_l}^{f_h} P_i(f)\,df$

$E_{\text{noise},i} = \int_{f_h}^{f_{\max}} P_i(f)\,df$

则：

$\text{SNR}_i = \frac{E_{\text{sig},i}}{E_{\text{noise},i}+\epsilon}$

其中：

| 符号       | 含义                      |
| ---------- | ------------------------- |
| $f_l$      | 呼吸频带低截止，如 0.1 Hz |
| $f_h$      | 呼吸频带高截止，如 0.6 Hz |
| $f_{\max}$ | 可用于噪声估计的最高频率  |
| $\epsilon$ | 防止除零的小常数          |

------

## 7.3 频段参数推荐

| 参数         | 推荐值     |
| ------------ | ---------- |
| signal band  | 0.1–0.6 Hz |
| noise band   | 0.8–3.0 Hz |
| PSD 方法     | Welch      |
| Welch window | 30–60 s    |
| overlap      | 50%        |

注意：如果采样率为 200 Hz，而呼吸只在低频 0.1–0.6 Hz，直接在 200 Hz 下做 PSD 分辨率浪费较大。可以先对滤波后信号降采样到 10 Hz 或 20 Hz。

推荐：

```python
fs_raw = 200
fs_proc = 20
```

即先低通/带通后降采样再进行后续呼吸处理。

------

## 7.4 PSD-SNR 代码

```python
from scipy.signal import welch
import numpy as np

def estimate_snr_psd(
    X,
    fs,
    signal_band=(0.1, 0.6),
    noise_band=(0.8, 3.0),
    nperseg=None,
    eps=1e-10
):
    """
    基于 PSD 估计每个通道的 SNR。

    Parameters
    ----------
    X : np.ndarray
        shape = [T, N_channels]
    fs : float
        采样率。
    signal_band : tuple
        呼吸信号频带，Hz。
    noise_band : tuple
        噪声估计频带，Hz。
    nperseg : int or None
        Welch 每段长度。
    eps : float
        防止除零。

    Returns
    -------
    snr : np.ndarray
        shape = [N_channels]
    snr_db : np.ndarray
        shape = [N_channels]
    """
    T, N_channels = X.shape

    if nperseg is None:
        nperseg = min(T, int(30 * fs))

    snr = np.zeros(N_channels)

    for ch in range(N_channels):
        f, pxx = welch(
            X[:, ch],
            fs=fs,
            nperseg=nperseg,
            noverlap=nperseg // 2
        )

        sig_mask = (f >= signal_band[0]) & (f <= signal_band[1])
        noise_mask = (f >= noise_band[0]) & (f <= noise_band[1])

        e_sig = np.trapz(pxx[sig_mask], f[sig_mask])
        e_noise = np.trapz(pxx[noise_mask], f[noise_mask])

        snr[ch] = e_sig / (e_noise + eps)

    snr_db = 10 * np.log10(snr + eps)

    return snr, snr_db
```

------

# 8. MRC：Maximal-Ratio Combining

## 8.1 MRC 的作用

MRC 的目标是：

> 多个含噪观测通道中，高 SNR 通道给大权重，低 SNR 通道给小权重，从而最大化融合信号 SNR。

假设每个通道为：

$x_i(t)=a_i s(t)+n_i(t)$

其中：

| 符号     | 含义                          |
| -------- | ----------------------------- |
| $s(t)$   | 真实呼吸波形                  |
| $a_i$    | 第 $i$ 个通道对呼吸的响应系数 |
| $n_i(t)$ | 噪声                          |

如果噪声近似独立，MRC 是一种经典的最优融合策略。

------

## 8.2 直接 MRC 的问题

传统 MRC 权重通常是非负的。

但 Wi-Fi 呼吸信号中，不同子载波可能正反相：

```text
通道 1：吸气 → CSI 上升
通道 2：吸气 → CSI 下降
```

如果只用正权重加权：

```text
x1 + x2
```

可能会相互抵消。

因此需要 PCA 提供符号校正。

------

## 8.3 MRC 权重构造

可采用：

$g_i = \frac{\text{SNR}_i}{\sum_j \text{SNR}_j}$

或者：

$g_i = \frac{\sqrt{\text{SNR}_i}}{\sum_j \sqrt{\text{SNR}_j}}$

论文描述是：

> gain proportional to RMS signal energy and inversely proportional to RMS noise energy.

这更接近：

$g_i \propto \frac{\sqrt{E_{\text{sig},i}}} {\sqrt{E_{\text{noise},i}}} = \sqrt{\text{SNR}_i}$

因此推荐复现时使用：

$g_i = \frac{\sqrt{\text{SNR}_i}}{\sum_j \sqrt{\text{SNR}_j}}$

同时为了避免低质量通道污染，可以做通道筛选：

```python
只保留 SNR_db 大于某阈值的通道
或者保留 top-K SNR 通道
```

推荐：

| 策略     | 参数                                    |
| -------- | --------------------------------------- |
| top-K    | 20–60                                   |
| SNR 阈值 | 可设为高于中位数，或 $SNR_{dB} > -5$ dB |

------

## 8.4 MRC 权重代码

```python
def compute_mrc_gains(snr, mode="sqrt", eps=1e-10):
    """
    根据 SNR 计算 MRC 正权重。

    Parameters
    ----------
    snr : np.ndarray
        shape = [N_channels]，线性 SNR。
    mode : str
        "sqrt" 或 "linear"。
    eps : float
        防止除零。

    Returns
    -------
    gains : np.ndarray
        shape = [N_channels]，非负归一化权重。
    """
    snr = np.maximum(snr, eps)

    if mode == "sqrt":
        w = np.sqrt(snr)
    elif mode == "linear":
        w = snr
    else:
        raise ValueError("mode must be 'sqrt' or 'linear'")

    gains = w / (np.sum(w) + eps)
    return gains
```

------

# 9. PCA 正反相校正

## 9.1 PCA 的作用

PCA 在这里不是为了降维输出，而是为了：

> 判断每个子载波/通道的呼吸波形方向，即正相还是反相。

经过呼吸带通滤波后，如果所有通道都含有共同呼吸成分，那么第一主成分对应主要呼吸变化方向。

第 $i$ 个通道在第一主成分上的 loading 符号表示：

| loading 符号 | 含义             |
| ------------ | ---------------- |
| 正           | 与主呼吸方向一致 |
| 负           | 与主呼吸方向相反 |

最终将该符号乘到 MRC gain 上。

------

## 9.2 数学表示

设候选通道矩阵为：

$X \in \mathbb{R}^{T \times C}$

其中：

| 符号 | 含义       |
| ---- | ---------- |
| $T$  | 时间点数   |
| $C$  | 候选通道数 |

先对每个通道去均值并标准化：

$\tilde{x}_i(t) = \frac{x_i(t)-\mu_i}{\sigma_i+\epsilon}$

PCA 第一主成分为：

$\mathbf{v}_1 \in \mathbb{R}^{C}$

则符号为：

$s_i = \operatorname{sign}(v_{1,i})$

最终带符号权重为：

$w_i = s_i g_i$

------

## 9.3 符号不确定性问题

PCA 本身存在整体符号不确定性：

$\mathbf{v}_1$

和

$-\mathbf{v}_1$

都是合法的第一主成分。

这不会影响呼吸率估计，因为波形整体反相不改变频率。

但如果你要定义“峰是吸气还是呼气”，则需要额外参考，例如胸腹带 ground truth 或者呼吸形态假设。

对于 WiFi-Sleep 的睡眠分期而言，整体正负不重要，因为它主要使用呼吸率、波动、深度方差和吸呼时间比例。

不过提取 FIT/I-E ratio 时，整体正负可能影响“吸气段”和“呼气段”的定义。复现时可以统一约定：

```text
上升段为 inhale，下降段为 exhale
```

但这只是相对定义，不一定对应真实生理吸气方向。

------

## 9.4 PCA 符号代码

```python
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import numpy as np

def estimate_pca_signs(X_for_pca):
    """
    使用 PCA 第一主成分估计每个通道的正反相符号。

    Parameters
    ----------
    X_for_pca : np.ndarray
        shape = [T, N_channels]，通常是带通滤波且乘过 MRC gain 的信号。

    Returns
    -------
    signs : np.ndarray
        shape = [N_channels]，每个通道的符号，取 +1 或 -1。
    pc1 : np.ndarray
        第一主成分 loading。
    """
    scaler = StandardScaler(with_mean=True, with_std=True)
    X_std = scaler.fit_transform(X_for_pca)

    pca = PCA(n_components=1)
    pca.fit(X_std)

    pc1 = pca.components_[0]
    signs = np.sign(pc1)

    # 避免出现 0
    signs[signs == 0] = 1.0

    return signs, pc1
```

------

# 10. MRC-PCA 融合

## 10.1 论文中的融合逻辑

WiFi-Sleep 的 MRC-PCA 可以概括为：

```text
Step 1: 估计每个通道 SNR
Step 2: 用 SNR 计算 MRC gain
Step 3: 每个通道先乘 MRC gain
Step 4: 对加权后信号做呼吸带通滤波
Step 5: 用 PCA 判断每个通道的正反相
Step 6: 将 PCA 符号乘到 MRC gain 上
Step 7: 对原始或滤波后的通道做带符号加权平均
Step 8: 得到最终呼吸波形
```

------

## 10.2 推荐实现流程

实践中可以这样实现：

```text
输入：候选通道 X

1. X 去均值
2. 对 X 进行带通滤波，得到 X_bp
3. 用 X_bp 或原 X 的 PSD 估计 SNR
4. 根据 SNR 计算 MRC gain
5. 构造 X_weighted = X_bp * gain
6. PCA(X_weighted) 得到 signs
7. final_weights = signs * gain
8. waveform = X_bp @ final_weights
9. waveform 标准化
```

注意：最终融合用 `X_bp` 比用原始 `X` 更稳，因为睡眠呼吸估计主要关心呼吸频带。

如果后续还要分析呼吸形态，建议最终波形也保持呼吸带通后的平滑信号。

------

## 10.3 完整 MRC-PCA 代码

```python
import numpy as np

def mrc_pca_fusion(
    X,
    fs,
    resp_band=(0.1, 0.6),
    noise_band=(0.8, 3.0),
    filter_order=4,
    mrc_mode="sqrt",
    top_k=None,
    snr_db_threshold=None
):
    """
    MRC-PCA 多通道呼吸融合。

    Parameters
    ----------
    X : np.ndarray
        shape = [T, N_channels]，候选呼吸通道。
    fs : float
        采样率。
    resp_band : tuple
        呼吸频带。
    noise_band : tuple
        噪声频带。
    filter_order : int
        带通滤波器阶数。
    mrc_mode : str
        "sqrt" 或 "linear"。
    top_k : int or None
        若不为 None，只保留 SNR 最高的 top_k 个通道。
    snr_db_threshold : float or None
        若不为 None，只保留 SNR_dB 大于该阈值的通道。

    Returns
    -------
    waveform : np.ndarray
        shape = [T]，融合后的呼吸波形。
    info : dict
        中间信息，包括 SNR、权重、通道选择等。
    """
    eps = 1e-10

    # 1. 去均值
    X0 = X - np.mean(X, axis=0, keepdims=True)

    # 2. 带通滤波
    X_bp = bandpass_filter(
        X0,
        fs=fs,
        low=resp_band[0],
        high=resp_band[1],
        order=filter_order
    )

    # 3. 估计 SNR
    snr, snr_db = estimate_snr_psd(
        X_bp,
        fs=fs,
        signal_band=resp_band,
        noise_band=noise_band
    )

    selected = np.ones(X.shape[1], dtype=bool)

    # 4. SNR threshold 筛选
    if snr_db_threshold is not None:
        selected &= (snr_db >= snr_db_threshold)

    # 5. top-K 筛选
    if top_k is not None and top_k < X.shape[1]:
        idx_sorted = np.argsort(snr)[::-1]
        top_mask = np.zeros(X.shape[1], dtype=bool)
        top_mask[idx_sorted[:top_k]] = True
        selected &= top_mask

    # 防止筛选为空
    if np.sum(selected) == 0:
        idx_best = np.argmax(snr)
        selected[idx_best] = True

    X_sel = X_bp[:, selected]
    snr_sel = snr[selected]
    snr_db_sel = snr_db[selected]

    # 6. MRC gain
    gains = compute_mrc_gains(snr_sel, mode=mrc_mode)

    # 7. 用 MRC gain 加权后送入 PCA 判断符号
    X_for_pca = X_sel * gains.reshape(1, -1)
    signs, pc1 = estimate_pca_signs(X_for_pca)

    # 8. 带符号权重
    final_weights = gains * signs

    # 9. 融合
    waveform = X_sel @ final_weights

    # 10. 标准化
    waveform = waveform - np.mean(waveform)
    waveform = waveform / (np.std(waveform) + eps)

    info = {
        "snr": snr,
        "snr_db": snr_db,
        "selected": selected,
        "snr_selected": snr_sel,
        "snr_db_selected": snr_db_sel,
        "gains": gains,
        "signs": signs,
        "pc1": pc1,
        "final_weights": final_weights,
    }

    return waveform, info
```

------

# 11. ACF 呼吸率估计

## 11.1 为什么不用 STFT？

传统呼吸率估计常用 STFT：

```text
在时间窗内做频谱分析，取最大峰作为呼吸频率。
```

但 STFT 有窗口长度问题：

| 窗口   | 问题                                   |
| ------ | -------------------------------------- |
| 短窗口 | 频率分辨率差                           |
| 长窗口 | 对运动干扰、呼吸缺失段更敏感，延迟更大 |

WiFi-Sleep 使用 ACF，自相关函数：

$R_{yy}(\tau) = \sum_n y(n)y(n-\tau)$

周期信号的自相关也具有同样周期。

如果呼吸周期为 $T$，则 ACF 在 $\tau=T$ 附近出现峰值。

呼吸率：

$rr = \frac{60}{T}$

单位为 bpm。

------

## 11.2 ACF 搜索范围

根据呼吸率范围：

```text
6 bpm 到 36 bpm
```

对应周期：

$T_{\max} = \frac{60}{6}=10s$

$T_{\min} = \frac{60}{36}\approx1.67s$

因此 ACF 峰值搜索 lag 范围为：

```python
lag_min = int(fs * 60 / max_bpm)
lag_max = int(fs * 60 / min_bpm)
```

推荐参数：

| 参数                        | 推荐值  |
| --------------------------- | ------- |
| min_bpm                     | 6       |
| max_bpm                     | 36      |
| 分析窗长                    | 20–60 s |
| 步长                        | 1–5 s   |
| WiFi-Sleep 睡眠分期输出间隔 | 30 s    |

如果为了每 30 秒输出一个呼吸率，可以设：

```python
window_sec = 30
step_sec = 1 或 5 或 30
```

若后续睡眠分期每 30 s 一个 epoch，则最终可把呼吸率聚合到 30 s。

------

## 11.3 ACF 单窗口呼吸率估计代码

```python
from scipy.signal import find_peaks
import numpy as np

def estimate_rr_acf_single_window(
    y,
    fs,
    min_bpm=6,
    max_bpm=36,
    normalize=True
):
    """
    使用 ACF 在单个窗口内估计呼吸率。

    Parameters
    ----------
    y : np.ndarray
        shape = [T]，单窗口呼吸波形。
    fs : float
        采样率。
    min_bpm : float
        最小呼吸率。
    max_bpm : float
        最大呼吸率。
    normalize : bool
        是否归一化 ACF。

    Returns
    -------
    rr_bpm : float
        呼吸率，单位 bpm。
    result : dict
        中间结果，包括 acf、lags、peak_lag 等。
    """
    eps = 1e-10

    y = np.asarray(y)
    y = y - np.mean(y)
    y = y / (np.std(y) + eps)

    # 完整自相关
    acf_full = np.correlate(y, y, mode="full")
    acf = acf_full[len(y) - 1:]

    if normalize:
        acf = acf / (acf[0] + eps)

    lags = np.arange(len(acf))

    lag_min = int(fs * 60.0 / max_bpm)
    lag_max = int(fs * 60.0 / min_bpm)
    lag_max = min(lag_max, len(acf) - 1)

    search_acf = acf[lag_min:lag_max + 1]

    peaks, properties = find_peaks(search_acf)

    if len(peaks) == 0:
        return np.nan, {
            "acf": acf,
            "lags": lags,
            "peak_lag": None,
            "peak_value": None
        }

    # 选择 ACF 值最高的峰
    best_peak_local = peaks[np.argmax(search_acf[peaks])]
    peak_lag = lag_min + best_peak_local
    peak_value = acf[peak_lag]

    period_sec = peak_lag / fs
    rr_bpm = 60.0 / period_sec

    return rr_bpm, {
        "acf": acf,
        "lags": lags,
        "peak_lag": peak_lag,
        "peak_value": peak_value
    }
```

------

## 11.4 滑动窗口呼吸率估计

```python
def estimate_rr_acf_sliding(
    waveform,
    fs,
    window_sec=30,
    step_sec=1,
    min_bpm=6,
    max_bpm=36
):
    """
    滑动窗口 ACF 呼吸率估计。

    Parameters
    ----------
    waveform : np.ndarray
        shape = [T]，融合后的呼吸波形。
    fs : float
        采样率。
    window_sec : float
        窗口长度。
    step_sec : float
        步长。
    min_bpm : float
        最小呼吸率。
    max_bpm : float
        最大呼吸率。

    Returns
    -------
    times : np.ndarray
        每个呼吸率估计对应的中心时间，秒。
    rr : np.ndarray
        呼吸率序列，bpm。
    """
    win = int(window_sec * fs)
    step = int(step_sec * fs)

    rr_list = []
    time_list = []

    for start in range(0, len(waveform) - win + 1, step):
        end = start + win
        y_win = waveform[start:end]

        rr_bpm, _ = estimate_rr_acf_single_window(
            y_win,
            fs=fs,
            min_bpm=min_bpm,
            max_bpm=max_bpm
        )

        rr_list.append(rr_bpm)
        time_list.append((start + end) / 2.0 / fs)

    return np.array(time_list), np.array(rr_list)
```

------

# 12. 呼吸波形质量评估

为了判断融合波形是否可靠，可以计算：

1. 呼吸频带 SNR；
2. ACF 峰值强度；
3. 频谱主峰占比；
4. 呼吸率连续性。

------

## 12.1 ACF 峰值置信度

ACF 第一个呼吸峰越高，说明周期性越强。

```python
def acf_confidence(y, fs, min_bpm=6, max_bpm=36):
    rr, result = estimate_rr_acf_single_window(
        y,
        fs=fs,
        min_bpm=min_bpm,
        max_bpm=max_bpm
    )
    peak_value = result["peak_value"]

    if peak_value is None:
        return np.nan

    return peak_value
```

可设经验阈值：

```text
ACF peak < 0.2：低置信度
ACF peak 0.2–0.4：中等
ACF peak > 0.4：较可靠
```

------

# 13. 呼吸深度方差提取

## 13.1 背景

Wi-Fi CSI 无法直接转换为真实呼吸深度，因为 CSI 幅值变化与胸腔位移之间的比例依赖：

1. 人的位置；
2. 姿态；
3. 发射机/接收机布局；
4. 多径环境；
5. Fresnel zone。

所以 WiFi-Sleep 不直接估计绝对呼吸深度，而是估计：

> 短窗口内相对呼吸深度变化。

做法：

1. 在短窗口内假设人和设备位置稳定；
2. MRC-PCA 参数固定；
3. 呼吸波形归一化；
4. 检测每个呼吸周期的峰谷；
5. 每个周期深度 = peak - valley；
6. 计算深度方差。

------

## 13.2 峰谷检测

对于标准化呼吸波形：

```text
peak：局部最大值
valley：局部最小值
depth = peak - previous_valley 或 peak - next_valley
```

需要设置最小峰间距。

如果最大呼吸率为 36 bpm，则最短周期约 1.67 s。

可设：

```python
min_peak_distance = fs * 60 / max_bpm
```

------

## 13.3 呼吸深度方差代码

```python
from scipy.signal import find_peaks
import numpy as np

def extract_resp_depth_variance(
    y,
    fs,
    min_bpm=6,
    max_bpm=36
):
    """
    提取相对呼吸深度方差。

    Parameters
    ----------
    y : np.ndarray
        单窗口呼吸波形。
    fs : float
        采样率。
    min_bpm : float
        最小呼吸率。
    max_bpm : float
        最大呼吸率。

    Returns
    -------
    depth_var : float
        呼吸深度方差。
    depths : np.ndarray
        每个周期的相对深度。
    peaks : np.ndarray
        峰位置。
    valleys : np.ndarray
        谷位置。
    """
    eps = 1e-10

    y = y - np.mean(y)
    y = y / (np.std(y) + eps)

    min_distance = int(fs * 60.0 / max_bpm)

    peaks, _ = find_peaks(y, distance=min_distance)
    valleys, _ = find_peaks(-y, distance=min_distance)

    depths = []

    for p in peaks:
        # 找 p 左右最近的谷
        left_valleys = valleys[valleys < p]
        right_valleys = valleys[valleys > p]

        if len(left_valleys) == 0 or len(right_valleys) == 0:
            continue

        v_left = left_valleys[-1]
        v_right = right_valleys[0]

        local_valley_value = min(y[v_left], y[v_right])
        depth = y[p] - local_valley_value

        if depth > 0:
            depths.append(depth)

    depths = np.array(depths)

    if len(depths) < 2:
        depth_var = np.nan
    else:
        depth_var = np.var(depths)

    return depth_var, depths, peaks, valleys
```

------

# 14. FIT 和 I/E Ratio 提取

## 14.1 定义

FIT，即 fractional inspiratory time：

$FIT = \frac{T_I}{T_I + T_E}$

I/E ratio：

$I/E = \frac{T_I}{T_E}$

其中：

| 符号        | 含义             |
| ----------- | ---------------- |
| $T_I$       | 吸气时间         |
| $T_E$       | 呼气时间         |
| $T_I + T_E$ | 一个完整呼吸周期 |

------

## 14.2 在 Wi-Fi 波形中的近似

如果假设：

```text
波形上升段 = inhale
波形下降段 = exhale
```

那么：

```text
valley → next peak：吸气时间 TI
peak → next valley：呼气时间 TE
```

但需要注意：

> Wi-Fi 融合波形整体可能反相，因此上升段不一定真实对应吸气。
>  如果没有胸腹带参考，FIT 和 I/E ratio 更准确地说是“相对上升/下降时间比例”。

不过对睡眠分期而言，模型可能只需要这种呼吸形态周期差异，不一定需要严格生理吸气方向。

------

## 14.3 FIT 和 I/E 代码

```python
def extract_fit_ie_ratio(
    y,
    fs,
    min_bpm=6,
    max_bpm=36
):
    """
    从呼吸波形中提取 FIT 和 I/E ratio。

    默认约定：valley -> peak 为 inspiration，peak -> valley 为 expiration。

    Parameters
    ----------
    y : np.ndarray
        单窗口呼吸波形。
    fs : float
        采样率。
    min_bpm : float
        最小呼吸率。
    max_bpm : float
        最大呼吸率。

    Returns
    -------
    features : dict
        包括 FIT mean/var, IER mean/var 等。
    """
    eps = 1e-10

    y = y - np.mean(y)
    y = y / (np.std(y) + eps)

    min_distance = int(fs * 60.0 / max_bpm)

    peaks, _ = find_peaks(y, distance=min_distance)
    valleys, _ = find_peaks(-y, distance=min_distance)

    fits = []
    ie_ratios = []

    # 对每个 peak，寻找左谷和右谷
    for p in peaks:
        left_valleys = valleys[valleys < p]
        right_valleys = valleys[valleys > p]

        if len(left_valleys) == 0 or len(right_valleys) == 0:
            continue

        v_left = left_valleys[-1]
        v_right = right_valleys[0]

        ti = (p - v_left) / fs
        te = (v_right - p) / fs

        if ti <= 0 or te <= 0:
            continue

        fit = ti / (ti + te)
        ie = ti / (te + eps)

        fits.append(fit)
        ie_ratios.append(ie)

    fits = np.array(fits)
    ie_ratios = np.array(ie_ratios)

    features = {
        "fit_mean": np.nan if len(fits) == 0 else np.mean(fits),
        "fit_var": np.nan if len(fits) < 2 else np.var(fits),
        "ie_mean": np.nan if len(ie_ratios) == 0 else np.mean(ie_ratios),
        "ie_var": np.nan if len(ie_ratios) < 2 else np.var(ie_ratios),
        "fits": fits,
        "ie_ratios": ie_ratios,
        "peaks": peaks,
        "valleys": valleys,
    }

    return features
```

------

# 15. 呼吸率特征

论文还使用呼吸率相关统计特征。

给定滑动窗口得到的呼吸率序列：

```python
rr[t]
```

可以提取：

| 特征          | 说明         |
| ------------- | ------------ |
| mean RR       | 平均呼吸率   |
| var RR        | 呼吸率方差   |
| std RR        | 呼吸率标准差 |
| IQR RR        | 四分位距     |
| smoothed RR   | 平滑呼吸率   |
| derivative RR | 呼吸率一阶导 |
| deviation     | 偏离程度     |

------

## 15.1 代码

```python
def extract_rr_features(rr):
    """
    从呼吸率序列提取统计特征。

    Parameters
    ----------
    rr : np.ndarray
        呼吸率序列，单位 bpm。

    Returns
    -------
    features : dict
        呼吸率统计特征。
    """
    rr = np.asarray(rr)
    rr_valid = rr[~np.isnan(rr)]

    if len(rr_valid) == 0:
        return {
            "rr_mean": np.nan,
            "rr_std": np.nan,
            "rr_var": np.nan,
            "rr_iqr": np.nan,
            "rr_median": np.nan,
            "rr_derivative_mean": np.nan,
            "rr_derivative_std": np.nan,
        }

    q75, q25 = np.percentile(rr_valid, [75, 25])
    derivative = np.diff(rr_valid)

    features = {
        "rr_mean": np.mean(rr_valid),
        "rr_std": np.std(rr_valid),
        "rr_var": np.var(rr_valid),
        "rr_iqr": q75 - q25,
        "rr_median": np.median(rr_valid),
        "rr_derivative_mean": np.nan if len(derivative) == 0 else np.mean(derivative),
        "rr_derivative_std": np.nan if len(derivative) == 0 else np.std(derivative),
    }

    return features
```

------

# 16. 完整呼吸估计 Pipeline 示例

下面给出一个从 CSI 到呼吸率的完整示例框架。

------

## 16.1 完整代码

```python
def wifi_sleep_respiration_pipeline(
    csi,
    timestamps=None,
    fs=200.0,
    target_fs=20.0,
    antenna_pairs=None,
    use_amplitude=True,
    use_phase=True,
    resp_band=(0.1, 0.6),
    noise_band=(0.8, 3.0),
    mrc_top_k=60,
    rr_window_sec=30,
    rr_step_sec=1
):
    """
    WiFi-Sleep 风格呼吸估计 Pipeline。

    Parameters
    ----------
    csi : np.ndarray
        shape = [T, N_rx, N_sub]，复数 CSI。
    timestamps : np.ndarray or None
        若不为 None，则用于重采样。
    fs : float
        原始采样率。
    target_fs : float
        降采样后的处理采样率。
    antenna_pairs : list or None
        CSI ratio 天线对。
    use_amplitude : bool
        是否使用 CSI ratio amplitude。
    use_phase : bool
        是否使用 CSI ratio phase。
    resp_band : tuple
        呼吸频带，Hz。
    noise_band : tuple
        噪声频带，Hz。
    mrc_top_k : int
        保留 SNR 最高的通道数。
    rr_window_sec : float
        ACF 呼吸率估计窗口长度。
    rr_step_sec : float
        ACF 呼吸率估计步长。

    Returns
    -------
    result : dict
        包含 waveform, rr, features, 中间信息等。
    """
    from scipy.signal import resample_poly
    import math

    # 1. 根据时间戳重采样到 fs
    if timestamps is not None:
        csi_uniform, t_uniform = resample_csi(csi, timestamps, fs=fs)
    else:
        csi_uniform = csi
        t_uniform = np.arange(csi.shape[0]) / fs

    # 2. CSI ratio
    csi_ratio, pairs = compute_csi_ratio(
        csi_uniform,
        pairs=antenna_pairs
    )

    # 3. 构造 amplitude / phase 候选通道
    X, channel_info = build_candidate_channels(
        csi_ratio,
        use_amplitude=use_amplitude,
        use_phase=use_phase
    )

    # 4. 降采样到 target_fs
    # 需要整数近似 up/down
    if target_fs is not None and target_fs < fs:
        gcd = math.gcd(int(fs), int(target_fs))
        up = int(target_fs // gcd)
        down = int(fs // gcd)
        X_proc = resample_poly(X, up, down, axis=0)
        fs_proc = target_fs
    else:
        X_proc = X
        fs_proc = fs

    # 5. MRC-PCA 融合
    waveform, fusion_info = mrc_pca_fusion(
        X_proc,
        fs=fs_proc,
        resp_band=resp_band,
        noise_band=noise_band,
        top_k=mrc_top_k
    )

    # 6. ACF 呼吸率估计
    rr_times, rr = estimate_rr_acf_sliding(
        waveform,
        fs=fs_proc,
        window_sec=rr_window_sec,
        step_sec=rr_step_sec,
        min_bpm=6,
        max_bpm=36
    )

    # 7. 呼吸率特征
    rr_features = extract_rr_features(rr)

    # 8. 形态特征，可以对整段或每个 epoch 计算
    depth_var, depths, peaks, valleys = extract_resp_depth_variance(
        waveform,
        fs=fs_proc
    )

    fit_ie_features = extract_fit_ie_ratio(
        waveform,
        fs=fs_proc
    )

    result = {
        "fs_proc": fs_proc,
        "pairs": pairs,
        "channel_info": channel_info,
        "waveform": waveform,
        "fusion_info": fusion_info,
        "rr_times": rr_times,
        "rr_bpm": rr,
        "rr_features": rr_features,
        "depth_var": depth_var,
        "depths": depths,
        "peaks": peaks,
        "valleys": valleys,
        "fit_ie_features": fit_ie_features,
    }

    return result
```

------

# 17. 分 epoch 特征提取

WiFi-Sleep 睡眠分期采用医学 PSG 常用的 30 秒 epoch。

因此呼吸特征也应最终整理为：

```python
features.shape = [N_epoch, N_feature]
```

每个 epoch 对应 30 秒。

------

## 17.1 Epoch 特征提取代码

```python
def extract_epoch_resp_features(
    waveform,
    rr_times,
    rr_bpm,
    fs,
    epoch_sec=30
):
    """
    按 30 秒 epoch 提取呼吸特征。

    Parameters
    ----------
    waveform : np.ndarray
        融合后的呼吸波形。
    rr_times : np.ndarray
        呼吸率时间点。
    rr_bpm : np.ndarray
        呼吸率序列。
    fs : float
        采样率。
    epoch_sec : float
        epoch 长度。

    Returns
    -------
    epoch_features : list of dict
        每个 epoch 的呼吸特征。
    """
    total_sec = len(waveform) / fs
    n_epoch = int(total_sec // epoch_sec)

    epoch_features = []

    for e in range(n_epoch):
        start_sec = e * epoch_sec
        end_sec = (e + 1) * epoch_sec

        start_idx = int(start_sec * fs)
        end_idx = int(end_sec * fs)

        y_epoch = waveform[start_idx:end_idx]

        rr_mask = (rr_times >= start_sec) & (rr_times < end_sec)
        rr_epoch = rr_bpm[rr_mask]

        rr_feat = extract_rr_features(rr_epoch)

        depth_var, depths, peaks, valleys = extract_resp_depth_variance(
            y_epoch,
            fs=fs
        )

        fit_ie = extract_fit_ie_ratio(
            y_epoch,
            fs=fs
        )

        feat = {}
        feat.update(rr_feat)
        feat["depth_var"] = depth_var
        feat["n_breath_cycles"] = len(depths)
        feat["fit_mean"] = fit_ie["fit_mean"]
        feat["fit_var"] = fit_ie["fit_var"]
        feat["ie_mean"] = fit_ie["ie_mean"]
        feat["ie_var"] = fit_ie["ie_var"]

        epoch_features.append(feat)

    return epoch_features
```

------

# 18. 推荐参数汇总

## 18.1 采集参数

| 参数         | 推荐值      |
| ------------ | ----------- |
| Wi-Fi 频段   | 5 GHz       |
| 带宽         | 20 MHz      |
| 发包率       | 200 Hz      |
| 接收天线数   | 3           |
| 子载波数     | 30          |
| CSI 数据类型 | complex CSI |

------

## 18.2 预处理参数

| 参数       | 推荐值               |
| ---------- | -------------------- |
| 原始采样率 | 200 Hz               |
| 处理采样率 | 20 Hz                |
| 重采样方法 | 线性插值 / polyphase |
| 去均值     | 每通道去均值         |
| 相位处理   | unwrap               |

------

## 18.3 呼吸滤波参数

| 参数     | 推荐值      |
| -------- | ----------- |
| 呼吸频带 | 0.1–0.6 Hz  |
| 对应 bpm | 6–36 bpm    |
| 滤波器   | Butterworth |
| 阶数     | 4           |
| 滤波方式 | filtfilt    |

------

## 18.4 SNR 估计参数

| 参数        | 推荐值     |
| ----------- | ---------- |
| PSD 方法    | Welch      |
| signal band | 0.1–0.6 Hz |
| noise band  | 0.8–3.0 Hz |
| nperseg     | 30 s       |
| overlap     | 50%        |

------

## 18.5 MRC-PCA 参数

| 参数       | 推荐值                            |
| ---------- | --------------------------------- |
| MRC gain   | $\sqrt{SNR}$ 归一化               |
| PCA 输入   | 带通滤波且 MRC 加权后的多通道信号 |
| PCA 分量数 | 1                                 |
| sign       | 第一主成分 loading 的符号         |
| 通道筛选   | top-K = 30–60 或 SNR 阈值         |
| 最终融合   | 带符号 MRC 加权平均               |

------

## 18.6 ACF 参数

| 参数           | 推荐值                  |
| -------------- | ----------------------- |
| ACF 窗口       | 30 s                    |
| ACF 步长       | 1–5 s，或 30 s          |
| min bpm        | 6                       |
| max bpm        | 36                      |
| peak selection | 搜索范围内最高 ACF peak |
| 置信度         | ACF peak value          |

------

# 19. 复现时的关键注意事项

## 19.1 PCA 不是替代 MRC

PCA 负责：

```text
判断正反相符号
```

MRC 负责：

```text
根据 SNR 决定权重大小
```

不要简单地用 PCA 第一主成分直接代替 MRC-PCA，除非你只是做 baseline。

------

## 19.2 原始 CSI phase 不应直接使用

应先做 CSI ratio，再取 phase。

否则原始 phase 中的随机相位偏移可能远大于呼吸引起的相位变化。

------

## 19.3 整体波形正负号不影响呼吸率

MRC-PCA 输出的呼吸波形可能整体反相。

对呼吸率估计无影响。

但对 FIT 和 I/E ratio 的生理解释有影响。

如果没有 ground truth，不建议强行说：

```text
上升段一定是吸气
下降段一定是呼气
```

更严谨说法是：

```text
waveform rising duration / falling duration ratio
```

------

## 19.4 呼吸深度是相对深度

Wi-Fi CSI 不能直接给出真实潮气量或胸腔位移。

因此本文复现代码中的 `depth_var` 是：

```text
融合呼吸波形的相对振幅变化方差
```

不是医学意义上的绝对呼吸深度。

------

## 19.5 运动期间呼吸估计应剔除或插值

WiFi-Sleep 中身体运动会干扰呼吸检测。

如果你只复现呼吸算法，可以先忽略运动检测。但如果数据中有翻身、起身等动作，建议：

1. 检测异常高能量片段；
2. 删除这些片段的呼吸率；
3. 用线性插值补全。

简化版本可以用波形能量阈值检测运动：

```python
def simple_motion_mask_from_waveform(waveform, fs, window_sec=1, threshold_z=4.0):
    """
    简单运动检测：基于短时能量 z-score。
    仅用于呼吸估计中的异常片段剔除，不等价于论文 Doppler-MUSIC。
    """
    win = int(window_sec * fs)
    energy = []

    for start in range(0, len(waveform) - win + 1):
        seg = waveform[start:start + win]
        energy.append(np.mean(seg ** 2))

    energy = np.array(energy)
    z = (energy - np.mean(energy)) / (np.std(energy) + 1e-10)

    mask_short = z > threshold_z

    mask = np.zeros(len(waveform), dtype=bool)
    for i, m in enumerate(mask_short):
        if m:
            mask[i:i + win] = True

    return mask
```

------

# 20. 建议做的 baseline 对比

为了验证你的复现是否合理，建议做以下对比。

------

## 20.1 单子载波 CSI amplitude

```text
从原始 CSI amplitude 中选一个子载波
带通滤波
ACF 估计呼吸率
```

预期效果：容易有盲区，SNR 低。

------

## 20.2 最佳子载波

```text
计算所有子载波 SNR
选择 SNR 最高的单通道
ACF 估计呼吸率
```

预期效果：比随机单子载波好，但不如 MRC-PCA 稳。

------

## 20.3 直接 MRC

```text
用 SNR 作为正权重
不做 PCA 符号校正
```

预期效果：可能因为正反相抵消而表现变差。

------

## 20.4 PCA 第一主成分

```text
对多通道直接 PCA
取第一主成分作为呼吸波形
```

预期效果：可解决部分方向问题，但可能被高方差噪声影响。

------

## 20.5 MRC-PCA

```text
SNR 权重 + PCA 符号校正
```

预期效果：最稳定。

------

# 21. Baseline 示例代码

```python
def baseline_best_subcarrier(X, fs, resp_band=(0.1, 0.6), noise_band=(0.8, 3.0)):
    """
    选择 SNR 最高的单通道作为呼吸波形。
    """
    X0 = X - np.mean(X, axis=0, keepdims=True)
    X_bp = bandpass_filter(X0, fs, low=resp_band[0], high=resp_band[1])
    snr, snr_db = estimate_snr_psd(
        X_bp,
        fs=fs,
        signal_band=resp_band,
        noise_band=noise_band
    )
    best = np.argmax(snr)
    waveform = X_bp[:, best]
    waveform = (waveform - np.mean(waveform)) / (np.std(waveform) + 1e-10)

    return waveform, {
        "best_channel": best,
        "snr": snr,
        "snr_db": snr_db
    }


def baseline_direct_mrc(X, fs, resp_band=(0.1, 0.6), noise_band=(0.8, 3.0)):
    """
    直接 MRC，不做 PCA 符号校正。
    """
    X0 = X - np.mean(X, axis=0, keepdims=True)
    X_bp = bandpass_filter(X0, fs, low=resp_band[0], high=resp_band[1])
    snr, snr_db = estimate_snr_psd(
        X_bp,
        fs=fs,
        signal_band=resp_band,
        noise_band=noise_band
    )

    gains = compute_mrc_gains(snr, mode="sqrt")
    waveform = X_bp @ gains
    waveform = (waveform - np.mean(waveform)) / (np.std(waveform) + 1e-10)

    return waveform, {
        "gains": gains,
        "snr": snr,
        "snr_db": snr_db
    }


def baseline_pca_first_component(X, fs, resp_band=(0.1, 0.6)):
    """
    PCA 第一主成分 baseline。
    """
    X0 = X - np.mean(X, axis=0, keepdims=True)
    X_bp = bandpass_filter(X0, fs, low=resp_band[0], high=resp_band[1])

    scaler = StandardScaler(with_mean=True, with_std=True)
    X_std = scaler.fit_transform(X_bp)

    pca = PCA(n_components=1)
    comp = pca.fit_transform(X_std)[:, 0]

    waveform = comp - np.mean(comp)
    waveform = waveform / (np.std(waveform) + 1e-10)

    return waveform, {
        "explained_variance_ratio": pca.explained_variance_ratio_[0],
        "components": pca.components_[0]
    }
```

------

# 22. 一个最小可运行示例：模拟多通道呼吸信号

如果你暂时没有 CSI 数据，可以先用模拟数据验证 MRC-PCA 是否能解决正反相问题。

------

## 22.1 模拟数据代码

```python
import numpy as np
import matplotlib.pyplot as plt

def simulate_multichannel_respiration(
    fs=20,
    duration=120,
    rr_bpm=15,
    n_channels=20,
    noise_level=0.5,
    random_state=0
):
    """
    模拟多通道呼吸信号，其中部分通道正相，部分通道反相，SNR 不同。
    """
    rng = np.random.default_rng(random_state)

    t = np.arange(0, duration, 1 / fs)
    f_resp = rr_bpm / 60.0

    true_resp = np.sin(2 * np.pi * f_resp * t)

    X = []

    for i in range(n_channels):
        amp = rng.uniform(0.2, 2.0)
        sign = rng.choice([-1, 1])
        noise = rng.normal(0, noise_level * rng.uniform(0.5, 2.0), size=len(t))
        drift = 0.1 * np.sin(2 * np.pi * rng.uniform(0.01, 0.05) * t)
        x = sign * amp * true_resp + noise + drift
        X.append(x)

    X = np.stack(X, axis=1)

    return t, true_resp, X


# 运行模拟
fs_sim = 20
t, true_resp, X_sim = simulate_multichannel_respiration(fs=fs_sim)

wave_best, _ = baseline_best_subcarrier(X_sim, fs=fs_sim)
wave_mrc, _ = baseline_direct_mrc(X_sim, fs=fs_sim)
wave_pca, _ = baseline_pca_first_component(X_sim, fs=fs_sim)
wave_mrc_pca, info = mrc_pca_fusion(X_sim, fs=fs_sim, top_k=20)

rr_mrc_pca, _ = estimate_rr_acf_single_window(wave_mrc_pca, fs=fs_sim)

print("Estimated RR by MRC-PCA:", rr_mrc_pca, "bpm")

plt.figure(figsize=(12, 8))
plt.subplot(5, 1, 1)
plt.plot(t, true_resp)
plt.title("Ground Truth Respiration")

plt.subplot(5, 1, 2)
plt.plot(t, wave_best)
plt.title("Best Subcarrier")

plt.subplot(5, 1, 3)
plt.plot(t, wave_mrc)
plt.title("Direct MRC")

plt.subplot(5, 1, 4)
plt.plot(t, wave_pca)
plt.title("PCA First Component")

plt.subplot(5, 1, 5)
plt.plot(t, wave_mrc_pca)
plt.title("MRC-PCA")

plt.tight_layout()
plt.show()
```

------

# 23. 与原文实验结果对应关系

如果复现正确，趋势应接近论文：

| 方法                | 预期现象                 |
| ------------------- | ------------------------ |
| 单 CSI amplitude    | 检测率低，盲区多         |
| CSI ratio           | 检测率显著提升           |
| MRC-PCA             | 呼吸波形更平滑，SNR 更高 |
| CSI ratio + MRC-PCA | 最佳                     |
| ACF                 | 呼吸率估计稳定，误差小   |

论文报告的呼吸检测结果为：

| 方法                | 检测率 | SNR     |
| ------------------- | ------ | ------- |
| CSI                 | 53.5%  | -4.4 dB |
| MRC-PCA             | 62.9%  | -3.3 dB |
| CSI ratio           | 91.9%  | 2.4 dB  |
| CSI ratio + MRC-PCA | 97.8%  | 4.8 dB  |

呼吸率 90% 误差：

| 方法          | 90% error |
| ------------- | --------- |
| CSI amplitude | 6.9 bpm   |
| CSI ratio     | 6.2 bpm   |
| MRC-PCA       | 0.77 bpm  |
| WiFi-Sleep    | 0.29 bpm  |

------

# 24. 最终推荐复现版本

如果你的目标是尽快得到可用结果，建议按以下配置实现：

```python
fs_raw = 200
fs_proc = 20

antenna_pairs = [(0, 1), (0, 2), (1, 2)]

use_amplitude = True
use_phase = True

resp_band = (0.1, 0.6)
noise_band = (0.8, 3.0)

filter_order = 4

mrc_gain = "sqrt_snr"

top_k = 60

acf_window_sec = 30
acf_step_sec = 1

min_bpm = 6
max_bpm = 36
```

推荐主流程：

```text
CSI
→ resample to 200 Hz
→ CSI ratio
→ ratio amplitude + unwrapped ratio phase
→ downsample to 20 Hz
→ bandpass 0.1–0.6 Hz
→ PSD SNR estimation
→ keep top-60 channels
→ MRC gain = sqrt(SNR)
→ PCA sign from first component
→ signed MRC weighted average
→ respiration waveform
→ ACF sliding window
→ respiration rate
→ morphology features
```

------

# 25. 简短总结

WiFi-Sleep 的呼吸估计算法核心可以总结为：

> **CSI ratio 解决相位不稳定和幅度盲区；MRC 根据 SNR 分配多通道融合权重；PCA 判断不同子载波呼吸波形的正反相，避免抵消；ACF 从增强后的周期性呼吸波形中估计呼吸率。**

其中最关键的实现点是：

```text
MRC 负责权重大小
PCA 负责权重符号
ACF 负责周期估计
CSI ratio 负责稳定相位并增强可检测性
```

如果要复现，不建议只做 PCA 或只做 MRC，而应做：

```text
CSI ratio + Bandpass + PSD-SNR + MRC gain + PCA sign + ACF
```