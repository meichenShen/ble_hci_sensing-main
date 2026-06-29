# WiFi 非接触式呼吸信号提取与呼吸频率估计方法复现报告

> 对象论文：
>  **Fan et al., “A Contactless Breathing Pattern Recognition System Using Deep Learning and WiFi Signal,” IEEE Internet of Things Journal, 2024.**
>
> 本报告主要聚焦论文中**呼吸信号提取、信噪比/BNR 提升、呼吸频率估计可复现流程**，暂不重点讨论后续 CNN-LSTM 呼吸模式分类部分。

------

# 1. 报告目标

本文报告旨在回答以下问题：

1. 这篇文章前端信号处理流程具体做了什么？
2. 每一步的背景、作用、输入输出是什么？
3. 如何把论文中的流程复现为代码？
4. 如果只关注呼吸频率计算，应该如何基于该论文方法扩展实现？
5. 论文中哪些参数是明确给出的，哪些需要复现者自行设定？
6. 论文中有哪些可能被误解或需要注意的细节？

------

# 2. 论文任务概述

这篇文章提出了一个基于 WiFi 信号的非接触式呼吸模式识别系统。系统整体由三部分组成：

```text
Data Collection
    ↓
Data Preprocessing
    ↓
Breathing Pattern Recognition Module
```

其中前两部分与呼吸频率估计最相关：

```text
WiFi WCI/CSI 采集
    ↓
WCI Ratio 提取
    ↓
Amplitude / Phase 提取
    ↓
基于 MRC 的子载波合并
    ↓
Savitzky–Golay 去噪
    ↓
归一化
    ↓
得到 60 s 呼吸波形
```

论文后续把该 60 s 呼吸波形输入 CNN-LSTM，用于识别六种呼吸模式：

| 类别          | 含义          | 主要特征                              |
| ------------- | ------------- | ------------------------------------- |
| Eupnea        | 正常呼吸      | 频率、幅度、节律较稳定                |
| Bradypnea     | 呼吸过缓      | $RR < 12$ bpm                         |
| Tachypnea     | 呼吸过快      | $RR > 20$ bpm                         |
| Biot          | Biot 呼吸     | 高频、近似等深呼吸，中间有 apnea      |
| Cheyne–Stokes | 陈-施呼吸     | 幅度渐强-渐弱，之后 apnea 或 hypopnea |
| Kussmaul      | Kussmaul 呼吸 | 深、快、费力                          |

------

# 3. 对论文方法的准确理解

你之前的理解是：

> 这篇文章写的是 MRC + VMD 做呼吸信号信噪比提升，以及频率估计。

这个理解需要修正。

更准确的说法是：

> 这篇文章前端使用 **WCI ratio + MRC-based subcarrier combination + Savitzky–Golay filtering** 来提取高 BNR 呼吸波形。
>  该波形可以用于呼吸频率估计，但论文的主要任务不是 RR estimation，而是六类呼吸模式识别。
>  文中没有使用 VMD。

也就是说，论文中并没有：

```text
VMD / Variational Mode Decomposition
```

而是使用：

```text
Savitzky–Golay filter
```

用于对 MRC 合并后的呼吸波形进行平滑去噪。

------

# 4. 现有方法不足

论文从接触式方法、视觉方法、已有 RF 方法三个角度说明已有方法的不足。

------

## 4.1 接触式呼吸监测方法的问题

传统接触式方法包括：

- ECG 电极；
- 呼吸带；
- 压力传感器；
- 加速度传感器；
- 可穿戴胸带；
- 穿戴式织物传感器等。

优点是精度较高，但问题明显：

1. 需要与人体接触；
2. 长期佩戴舒适性差；
3. 设备可能较重、较贵、操作复杂；
4. 可穿戴设备需要充电、清洁和维护；
5. 接触本身可能改变被试的自然呼吸模式。

因此，这类方法不适合长期、无感、家庭式呼吸监测。

------

## 4.2 视觉式非接触方法的问题

视觉式方法包括：

- RGB camera；
- infrared thermal camera；
- depth camera；
- Kinect 类设备。

问题包括：

1. 需要视距，受遮挡影响；
2. 有隐私风险；
3. 对光照、温度、环境变化敏感；
4. 计算复杂度较高；
5. 睡眠场景下被子遮挡会显著降低鲁棒性。

------

## 4.3 现有 RF 方法的问题

RF-based 方法包括：

- Doppler radar；
- UWB radar；
- FMCW radar；
- RFID；
- SDR；
- WiFi CSI/WCI。

雷达方法效果较好，但通常需要专用硬件。WiFi 方法具有：

- 低成本；
- 易部署；
- 商用硬件普及；
- 可与通信系统共存；
- 适合室内连续监测。

但已有 WiFi 呼吸研究大多集中在：

```text
呼吸检测
呼吸频率估计
睡眠状态监测
姿态感知
咳嗽/打喷嚏/打哈欠等状态监测
```

较少研究：

```text
基于 WiFi 信号的多类别呼吸模式识别
```

因此，论文的目标是进一步从 WiFi 信号中提取稳定呼吸波形，并进行异常呼吸模式分类。

------

# 5. 论文主要贡献

------

## 5.1 提出 WiFi 非接触式呼吸模式识别系统

系统可以连续监测人的呼吸活动，并自动识别六类呼吸模式：

```text
Eupnea
Bradypnea
Tachypnea
Biot
Cheyne–Stokes
Kussmaul
```

------

## 5.2 提出一套呼吸信息提取流程

前端信号处理流程包括：

```text
WCI Ratio Extraction
    ↓
Amplitude / Phase Extraction
    ↓
MRC-based Subcarrier Combination
    ↓
Savitzky–Golay Denoising
    ↓
Normalization
```

核心作用是从原始 WiFi 信道信息中提取高质量呼吸波形。

------

## 5.3 将工程信号处理与深度学习结合

论文强调系统并不只是深度学习分类器，而是：

```text
工程方法：从 WiFi 信号中准确提取呼吸波形
    +
深度学习：对提取的呼吸波形进行模式分类
```

其中工程方法负责提高输入信号质量，CNN-LSTM 负责分类。

------

## 5.4 搭建实际 WiFi 原型机

论文使用一个集成式 WiFi 收发原型机，而不是纯仿真。

硬件配置如下：

| 参数             | 值                    |
| ---------------- | --------------------- |
| Tx 天线数        | 1                     |
| Rx 天线数        | 3                     |
| 子载波数         | 30                    |
| 工作频率         | 5.32 GHz              |
| 带宽             | 20 MHz                |
| 采样率           | 50 Hz                 |
| Tx-Rx 距离       | 2 m                   |
| 设备高度         | 与腹部平齐            |
| 信号窗口长度     | 60 s                  |
| 每个窗口采样点数 | $50 \times 60 = 3000$ |

------

# 6. WiFi 呼吸感知理论背景

------

## 6.1 多径信道模型

室内 WiFi 信号会通过多条路径传播：

```text
LoS 直达路径
墙面/家具静态反射路径
人体胸腹部动态反射路径
```

无线信道信息 WCI 可以表示为：

$H(f_k,t)=\sum_{i=1}^{L} a_i(f_k,t)e^{-j2\pi f_k\tau_i(t)}$

其中：

| 符号         | 含义                                     |
| ------------ | ---------------------------------------- |
| $H(f_k,t)$   | 第 $k$ 个子载波在时刻 $t$ 的复数信道响应 |
| $L$          | 多径数量                                 |
| $a_i(f_k,t)$ | 第 $i$ 条路径的衰减                      |
| $\tau_i(t)$  | 第 $i$ 条路径传播时延                    |
| $f_k$        | 第 $k$ 个子载波频率                      |

由于：

$\tau_i(t)=\frac{d_i(t)}{c}$

所以：

$H(f_k,t)=\sum_{i=1}^{L} a_i(f_k,t)e^{-j2\pi d_i(t)/\lambda_k}$

其中：

| 符号        | 含义                |
| ----------- | ------------------- |
| $d_i(t)$    | 第 $i$ 条路径长度   |
| $c$         | 电磁波传播速度      |
| $\lambda_k$ | 第 $k$ 个子载波波长 |

------

## 6.2 静态分量与动态分量

当人体位于 WiFi 覆盖区域内时，胸腹呼吸运动会导致人体反射路径周期变化。

因此信道可分解为：

$H(f_k,t)=H_s(f_k)+H_d(f_k,t)$

其中：

| 分量         | 含义                           |
| ------------ | ------------------------------ |
| $H_s(f_k)$   | 静态分量，来自墙、家具、LoS 等 |
| $H_d(f_k,t)$ | 动态分量，来自呼吸运动         |

进一步可写为：

$H(f_k,t)=H_s(f_k)+A(f_k,t)e^{-j2\pi d(t)/\lambda_k}$

呼吸造成的胸腹位移通常是毫米级。论文中提到，胸腹壁位移平均约 $3\sim6$ mm，最大可达约 12 mm。对于 5.32 GHz WiFi 信号，波长约：

$\lambda = \frac{3\times10^8}{5.32\times10^9} \approx 56.4\ \text{mm}$

因此呼吸引起的路径变化通常小于一个波长，所以复平面中的 WCI 轨迹通常表现为圆弧，而不是完整圆。

------

# 7. 为什么需要 WCI Ratio？

------

## 7.1 原始 WCI 相位存在偏移问题

原始 WCI 可写为：

$H(f_k,t)=e^{-j\theta(t,k)} \left[ H_s(f_k)+A(f_k,t)e^{-j2\pi d(t)/\lambda_k} \right]$

其中 $e^{-j\theta(t,k)}$ 是硬件引入的相位偏移。

论文将相位偏移建模为：

$\theta(t,k)=[\theta_P(t)+\theta_S(t)]k+\theta_C(t)+\theta_{PLL}$

其中：

| 符号           | 含义                           |
| -------------- | ------------------------------ |
| $\theta_P(t)$  | Packet Detection Delay, PDD    |
| $\theta_S(t)$  | Sampling Frequency Offset, SFO |
| $\theta_C(t)$  | Carrier Frequency Offset, CFO  |
| $\theta_{PLL}$ | PLL 初始相位                   |

这些偏移会严重干扰原始 WCI 相位，使直接利用相位检测呼吸变得困难。

------

## 7.2 WCI Ratio 的消偏思想

论文使用两个接收天线的 WCI 做比值：

$H_r(f_k,t)=\frac{H_1(f_k,t)}{H_2(f_k,t)}$

若：

$H_1(f_k,t)=e^{-j\theta(t,k)}\tilde{H}_1(f_k,t)$

$H_2(f_k,t)=e^{-j\theta(t,k)}\tilde{H}_2(f_k,t)$

则：

$H_r(f_k,t) = \frac{ e^{-j\theta(t,k)}\tilde{H}_1(f_k,t) }{ e^{-j\theta(t,k)}\tilde{H}_2(f_k,t) } = \frac{\tilde{H}_1(f_k,t)}{\tilde{H}_2(f_k,t)}$

这样可以抵消公共相位偏移。

------

## 7.3 WCI Ratio 的作用总结

WCI Ratio 的作用是：

1. 消除原始 WCI 中不同天线共享的相位偏移；
2. 保留由胸腹呼吸运动引起的信号变化；
3. 使幅度和相位都可能包含清晰呼吸波形；
4. 为后续 MRC 子载波合并提供更高质量输入。

------

# 8. 幅度与相位互补性

WCI Ratio 是复数：

$H_r(f_k,t)=|H_r(f_k,t)|e^{j\angle H_r(f_k,t)}$

可以提取：

```text
Amplitude: |H_r(f_k,t)|
Phase:     angle(H_r(f_k,t))
```

论文指出，WCI Ratio 在复平面上的轨迹近似为圆弧。根据圆弧所在位置不同：

- 有些子载波的幅度变化明显；
- 有些子载波的相位变化明显；
- 单独用幅度或单独用相位都可能失败。

因此论文同时使用：

```text
WCI ratio amplitude
WCI ratio phase
```

并在后续通过 BNR 选择最优呼吸波形。

------

# 9. 前端信号处理完整流程

下面给出论文中呼吸信息提取流程的可复现版本。

------

## 9.1 输入数据定义

假设原始 WCI 数据为：

$H_i(f_k,t)$

其中：

| 维度           | 含义              |
| -------------- | ----------------- |
| $i=1,2,3$      | 三根 Rx 天线      |
| $k=1,\dots,30$ | 30 个 OFDM 子载波 |
| $t=1,\dots,N$  | 时间采样点        |
| $N=3000$       | 60 s × 50 Hz      |

代码中可表示为：

```python
H.shape == (num_rx, num_subcarriers, num_samples)
```

即：

```python
H.shape == (3, 30, 3000)
```

每个元素是复数。

------

## 9.2 Step 1：计算 WCI Ratio

三根接收天线两两相除：

$H_{r12}(f_k,t)=\frac{H_1(f_k,t)}{H_2(f_k,t)}$

$H_{r13}(f_k,t)=\frac{H_1(f_k,t)}{H_3(f_k,t)}$

$H_{r23}(f_k,t)=\frac{H_2(f_k,t)}{H_3(f_k,t)}$

得到 3 组 ratio。

代码维度：

```python
ratios.shape == (3, 30, 3000)
```

------

## 9.3 Step 2：提取 Amplitude 和 Phase

对每个 ratio 提取：

$A_{ij}(f_k,t)=|H_{rij}(f_k,t)|$

$P_{ij}(f_k,t)=\angle H_{rij}(f_k,t)$

得到：

```text
3 组 ratio amplitude
3 组 ratio phase
```

总共 6 组候选数据，每组包含 30 个子载波。

代码维度可组织为：

```python
candidates.shape == (6, 30, 3000)
```

其中：

```text
0: ratio12 amplitude
1: ratio12 phase
2: ratio13 amplitude
3: ratio13 phase
4: ratio23 amplitude
5: ratio23 phase
```

------

## 9.4 Step 3：Hampel 异常值去除

对每一条子载波时序进行 Hampel filter。

作用：

```text
去除尖峰噪声、异常采样点、WiFi 突发测量异常
```

Hampel filter 的常用参数：

| 参数        | 建议值       | 说明                   |
| ----------- | ------------ | ---------------------- |
| window_size | 5–15 samples | 局部窗口半径或窗口长度 |
| n_sigmas    | 3            | 判断异常点的阈值       |
| scale       | 1.4826       | MAD 到标准差的缩放系数 |

论文没有明确给出 Hampel 参数。复现时可从以下配置开始：

```python
window_size = 7
n_sigmas = 3.0
```

------

## 9.5 Step 4：估计每个子载波的 BNR

论文使用 PSD 估计每条子载波的 breathing-to-noise ratio, BNR。

基本思想：

$BNR_k= \frac{ \text{呼吸频段内能量} }{ \text{呼吸频段外能量} }$

可以通过 Welch PSD 实现：

$P_{xx}(f)=\text{Welch}(x(t))$

然后：

$E_{\text{breath}}=\sum_{f\in \mathcal{B}}P_{xx}(f)$

$E_{\text{noise}}=\sum_{f\notin \mathcal{B}}P_{xx}(f)$

$BNR=\frac{E_{\text{breath}}}{E_{\text{noise}}+\epsilon}$

------

## 9.6 呼吸频段如何设置？

论文文本中说使用 normal RR range。正常成人呼吸频率大约为：

$12\sim20\ \text{bpm}$

换算为 Hz：

$f=\frac{RR}{60}$

所以：

$12\ \text{bpm}=0.2\ \text{Hz}$

$20\ \text{bpm}=0.333\ \text{Hz}$

即：

```text
0.2–0.33 Hz
```

但是，论文还需要识别：

```text
Bradypnea: RR < 12 bpm
Tachypnea: RR > 20 bpm
```

因此，如果代码中只用 0.2–0.33 Hz 作为 BNR 频段，可能会压制异常呼吸成分。

为了复现呼吸频率估计，我建议使用更宽的频段，例如：

```text
0.1–0.6 Hz
```

对应：

```text
6–36 bpm
```

推荐配置：

| 任务             | 推荐频段    |
| ---------------- | ----------- |
| 正常呼吸增强     | 0.2–0.33 Hz |
| 通用 RR 估计     | 0.1–0.6 Hz  |
| 包含异常呼吸模式 | 0.08–0.8 Hz |
| 睡眠呼吸监测     | 0.05–0.6 Hz |

本文后续代码默认使用：

```python
breath_band = (0.1, 0.6)
```

------

## 9.7 Step 5：基于 MRC 的子载波合并

对于某一候选集合，例如：

```text
ratio12 phase
```

它有 30 条子载波时序：

$x_1(t),x_2(t),\dots,x_{30}(t)$

每条子载波对应一个 BNR：

$BNR_1,BNR_2,\dots,BNR_{30}$

MRC 权重可以设为：

$w_k=\frac{BNR_k}{\sum_{m=1}^{30}BNR_m+\epsilon}$

合并信号：

$x_{\text{mrc}}(t)=\sum_{k=1}^{30}w_kx_k(t)$

对 6 个候选集合分别做 MRC，得到 6 条合并波形。

------

## 9.8 Step 6：选择 BNR 最高的合并波形

对 6 条合并波形再次计算 BNR：

$BNR_{\text{combined},q},\quad q=1,\dots,6$

选择 BNR 最大的那一条作为最优呼吸信号：

$H_o(t)=\arg\max_q BNR_{\text{combined},q}$

注意，这里不是把 6 条波形再平均或拼接，而是直接选择最优的一条。

------

## 9.9 Step 7：Savitzky–Golay 滤波去噪

论文使用 S-G filter 对最优呼吸信号去噪。

S-G filter 在局部窗口内进行多项式拟合，可以平滑噪声，同时较好保留峰谷形态。

常用参数：

| 参数          | 建议值 | 说明       |
| ------------- | ------ | ---------- |
| window_length | 51–151 | 必须为奇数 |
| polyorder     | 2 或 3 | 多项式阶数 |
| fs            | 50 Hz  | 采样率     |

考虑呼吸频率一般较低，采样率 50 Hz，60 s 窗口长度 3000 点，可从以下配置开始：

```python
window_length = 101
polyorder = 3
```

窗口长度 101 点约为：

$\frac{101}{50}=2.02\ \text{s}$

对呼吸波形通常是合理的。

如果希望保留更尖锐的 apnea 边界，可以减小窗口，例如：

```python
window_length = 51
polyorder = 3
```

------

## 9.10 Step 8：归一化

论文使用 min-max normalization 到 $[-1,1]$：

$X'=-1+2\cdot\frac{X-X_{\min}}{X_{\max}-X_{\min}}$

输出：

$H'_{od}(t)$

代码形式：

```python
x_norm = -1 + 2 * (x - x.min()) / (x.max() - x.min() + eps)
```

------

# 10. 用于呼吸频率估计的扩展流程

论文主要任务不是 RR estimation，但基于前端提取的呼吸波形，可以自然计算呼吸频率。

完整流程：

```text
H'od(t)
    ↓
去趋势，可选
    ↓
PSD / FFT
    ↓
在呼吸频段搜索主峰
    ↓
RR = 60 × f_peak
```

------

## 10.1 PSD 主峰法

对归一化呼吸信号 $x(t)$ 做 Welch PSD：

$P_{xx}(f)=\text{Welch}(x(t))$

在呼吸频带 $[f_{\min},f_{\max}]$ 内找最大峰：

$f_{\text{peak}}=\arg\max_{f\in[f_{\min},f_{\max}]}P_{xx}(f)$

呼吸频率为：

$RR=60f_{\text{peak}}$

单位是 bpm。

------

## 10.2 推荐 RR 搜索范围

| 场景         | $f_{\min}$ | $f_{\max}$ | bpm 范围 |
| ------------ | ---------- | ---------- | -------- |
| 成人正常呼吸 | 0.2        | 0.33       | 12–20    |
| 通用成人呼吸 | 0.1        | 0.6        | 6–36     |
| 异常模式识别 | 0.08       | 0.8        | 4.8–48   |
| 睡眠呼吸     | 0.05       | 0.6        | 3–36     |

推荐默认：

```python
rr_band = (0.1, 0.6)
```

------

# 11. 关键参数汇总

------

## 11.1 论文明确给出的参数

| 参数                  | 值              |
| --------------------- | --------------- |
| 工作频率              | 5.32 GHz        |
| 带宽                  | 20 MHz          |
| Tx 天线               | 1               |
| Rx 天线               | 3               |
| 子载波                | 30              |
| 采样率                | 50 Hz           |
| 每段时间窗            | 60 s            |
| 每段采样点数          | 3000            |
| Tx-Rx 距离            | 2 m             |
| 高度                  | 与腹部平齐      |
| CNN-LSTM 输入尺寸     | $3000 \times 1$ |
| CNN conv filter 数    | 96              |
| CNN kernel size       | 250             |
| max-pooling pool size | 4               |
| max-pooling stride    | 4               |
| LSTM hidden units     | 100             |
| learning rate         | 0.0005          |
| mini-batch size       | 60              |
| epochs                | 50              |
| optimizer             | Adam            |

------

## 11.2 论文没有明确给出的信号处理参数

以下参数论文没有详细给出，复现时需要自行设定：

| 参数               | 建议默认值     |
| ------------------ | -------------- |
| Hampel window size | 7              |
| Hampel threshold   | 3.0            |
| Welch nperseg      | 512 或 1024    |
| Welch noverlap     | nperseg 的 50% |
| BNR 频段           | 0.1–0.6 Hz     |
| S-G window length  | 101            |
| S-G polyorder      | 3              |
| RR 搜索频段        | 0.1–0.6 Hz     |

------

# 12. Python 复现示例代码

下面给出一个可以直接改造成工程代码的示例。

依赖：

```bash
pip install numpy scipy matplotlib
```

------

## 12.1 工具函数

```python
import numpy as np
from scipy.signal import welch, savgol_filter, detrend
import matplotlib.pyplot as plt
```

------

## 12.2 Hampel Filter

```python
def hampel_filter(x, window_size=7, n_sigmas=3.0):
    """
    Hampel filter for outlier removal.

    Parameters
    ----------
    x : np.ndarray, shape (N,)
        Input 1-D signal.
    window_size : int
        Half window size. Total window length is 2*window_size + 1.
    n_sigmas : float
        Threshold in scaled MAD units.

    Returns
    -------
    y : np.ndarray, shape (N,)
        Filtered signal.
    """
    x = np.asarray(x, dtype=float)
    y = x.copy()
    n = len(x)

    k = 1.4826  # scale factor for Gaussian distribution

    for i in range(n):
        start = max(i - window_size, 0)
        end = min(i + window_size + 1, n)

        window = x[start:end]
        median = np.median(window)
        mad = k * np.median(np.abs(window - median))

        if mad < 1e-12:
            continue

        if np.abs(x[i] - median) > n_sigmas * mad:
            y[i] = median

    return y
```

------

## 12.3 BNR 估计函数

```python
def estimate_bnr(
    x,
    fs=50.0,
    breath_band=(0.1, 0.6),
    nperseg=512,
    noverlap=None,
    eps=1e-12
):
    """
    Estimate breathing-to-noise ratio using Welch PSD.

    BNR = energy in breathing band / energy outside breathing band.

    Parameters
    ----------
    x : np.ndarray, shape (N,)
        Input signal.
    fs : float
        Sampling frequency.
    breath_band : tuple
        Frequency band for breathing, e.g., (0.1, 0.6) Hz.
    nperseg : int
        Segment length for Welch PSD.
    noverlap : int or None
        Overlap length for Welch PSD.
    eps : float
        Small value to avoid division by zero.

    Returns
    -------
    bnr : float
        Estimated BNR.
    f : np.ndarray
        Frequency bins.
    pxx : np.ndarray
        PSD values.
    """
    x = np.asarray(x, dtype=float)
    x = detrend(x)

    if noverlap is None:
        noverlap = nperseg // 2

    nperseg = min(nperseg, len(x))

    f, pxx = welch(
        x,
        fs=fs,
        nperseg=nperseg,
        noverlap=min(noverlap, nperseg // 2),
        scaling="density"
    )

    f_low, f_high = breath_band
    breath_mask = (f >= f_low) & (f <= f_high)

    # Optional: exclude DC and very low frequency drift from noise calculation
    valid_mask = f > 0.02

    breath_energy = np.sum(pxx[breath_mask])
    noise_energy = np.sum(pxx[valid_mask & (~breath_mask)])

    bnr = breath_energy / (noise_energy + eps)

    return bnr, f, pxx
```

------

## 12.4 MRC 子载波合并

```python
def mrc_combine_subcarriers(
    subcarrier_signals,
    fs=50.0,
    breath_band=(0.1, 0.6),
    hampel_window=7,
    hampel_sigmas=3.0,
    nperseg=512,
    eps=1e-12
):
    """
    Apply Hampel filtering, estimate BNR of each subcarrier,
    and combine subcarriers using MRC-like BNR weights.

    Parameters
    ----------
    subcarrier_signals : np.ndarray, shape (num_subcarriers, num_samples)
        Signals from 30 subcarriers for one candidate group.
    fs : float
        Sampling frequency.
    breath_band : tuple
        Breathing frequency band.
    hampel_window : int
        Hampel half-window size.
    hampel_sigmas : float
        Hampel threshold.
    nperseg : int
        Welch segment length.
    eps : float
        Small value.

    Returns
    -------
    combined : np.ndarray, shape (num_samples,)
        MRC-combined breathing signal.
    weights : np.ndarray, shape (num_subcarriers,)
        MRC weights.
    bnrs : np.ndarray, shape (num_subcarriers,)
        Estimated BNRs for each subcarrier.
    filtered_subcarriers : np.ndarray
        Hampel-filtered subcarrier signals.
    """
    X = np.asarray(subcarrier_signals, dtype=float)
    num_subcarriers, num_samples = X.shape

    filtered = np.zeros_like(X)
    bnrs = np.zeros(num_subcarriers)

    for k in range(num_subcarriers):
        xk = X[k]

        # Remove outliers
        xk_filtered = hampel_filter(
            xk,
            window_size=hampel_window,
            n_sigmas=hampel_sigmas
        )

        # Detrend before BNR estimation and combining
        xk_filtered = detrend(xk_filtered)

        filtered[k] = xk_filtered

        bnr, _, _ = estimate_bnr(
            xk_filtered,
            fs=fs,
            breath_band=breath_band,
            nperseg=nperseg
        )
        bnrs[k] = bnr

    if np.sum(bnrs) < eps:
        weights = np.ones(num_subcarriers) / num_subcarriers
    else:
        weights = bnrs / (np.sum(bnrs) + eps)

    combined = np.sum(weights[:, None] * filtered, axis=0)

    return combined, weights, bnrs, filtered
```

------

## 12.5 主流程：WCI Ratio + MRC + S-G + Normalization

```python
def extract_breathing_signal(
    H,
    fs=50.0,
    breath_band=(0.1, 0.6),
    hampel_window=7,
    hampel_sigmas=3.0,
    sg_window_length=101,
    sg_polyorder=3,
    nperseg=512,
    eps=1e-12,
    unwrap_phase=True
):
    """
    Extract optimal breathing signal from complex WCI/CSI.

    Parameters
    ----------
    H : np.ndarray, shape (3, 30, N)
        Complex WCI/CSI measurements from 3 Rx antennas, 30 subcarriers.
    fs : float
        Sampling frequency.
    breath_band : tuple
        Frequency band used for BNR estimation.
    hampel_window : int
        Hampel half-window size.
    hampel_sigmas : float
        Hampel threshold.
    sg_window_length : int
        Savitzky-Golay window length. Must be odd.
    sg_polyorder : int
        Savitzky-Golay polynomial order.
    nperseg : int
        Welch segment length.
    eps : float
        Small value.
    unwrap_phase : bool
        Whether to unwrap phase along time axis.

    Returns
    -------
    result : dict
        Contains:
        - breathing_signal_raw: selected MRC signal before S-G
        - breathing_signal_denoised: after S-G filter
        - breathing_signal_norm: normalized to [-1, 1]
        - selected_candidate_index
        - candidate_names
        - candidate_bnrs
        - all_combined_signals
        - all_weights
        - all_subcarrier_bnrs
    """
    H = np.asarray(H)

    assert H.ndim == 3, "H should have shape (3, 30, N)"
    assert H.shape[0] == 3, "Expected 3 Rx antennas"

    num_rx, num_subcarriers, num_samples = H.shape

    # ------------------------------------------------------------
    # Step 1: WCI ratio extraction
    # ------------------------------------------------------------
    ratio_pairs = [(0, 1), (0, 2), (1, 2)]
    ratios = []

    for i, j in ratio_pairs:
        ratio = H[i] / (H[j] + eps)
        ratios.append(ratio)

    ratios = np.stack(ratios, axis=0)
    # ratios.shape == (3, 30, N)

    # ------------------------------------------------------------
    # Step 2: amplitude and phase extraction
    # ------------------------------------------------------------
    candidates = []
    candidate_names = []

    for idx, (i, j) in enumerate(ratio_pairs):
        r = ratios[idx]

        amp = np.abs(r)
        phase = np.angle(r)

        if unwrap_phase:
            phase = np.unwrap(phase, axis=-1)

        candidates.append(amp)
        candidate_names.append(f"ratio_{i+1}{j+1}_amplitude")

        candidates.append(phase)
        candidate_names.append(f"ratio_{i+1}{j+1}_phase")

    candidates = np.stack(candidates, axis=0)
    # candidates.shape == (6, 30, N)

    # ------------------------------------------------------------
    # Step 3-5: Hampel + BNR + MRC for each candidate
    # ------------------------------------------------------------
    all_combined = []
    all_weights = []
    all_subcarrier_bnrs = []
    candidate_bnrs = []

    for q in range(candidates.shape[0]):
        combined, weights, bnrs, _ = mrc_combine_subcarriers(
            candidates[q],
            fs=fs,
            breath_band=breath_band,
            hampel_window=hampel_window,
            hampel_sigmas=hampel_sigmas,
            nperseg=nperseg,
            eps=eps
        )

        combined_bnr, _, _ = estimate_bnr(
            combined,
            fs=fs,
            breath_band=breath_band,
            nperseg=nperseg,
            eps=eps
        )

        all_combined.append(combined)
        all_weights.append(weights)
        all_subcarrier_bnrs.append(bnrs)
        candidate_bnrs.append(combined_bnr)

    all_combined = np.stack(all_combined, axis=0)
    all_weights = np.stack(all_weights, axis=0)
    all_subcarrier_bnrs = np.stack(all_subcarrier_bnrs, axis=0)
    candidate_bnrs = np.asarray(candidate_bnrs)

    # ------------------------------------------------------------
    # Step 6: select candidate with maximum BNR
    # ------------------------------------------------------------
    selected_idx = int(np.argmax(candidate_bnrs))
    breathing_raw = all_combined[selected_idx]

    # ------------------------------------------------------------
    # Step 7: Savitzky-Golay denoising
    # ------------------------------------------------------------
    if sg_window_length >= num_samples:
        sg_window_length = num_samples - 1

    if sg_window_length % 2 == 0:
        sg_window_length += 1

    if sg_window_length <= sg_polyorder:
        sg_window_length = sg_polyorder + 3
        if sg_window_length % 2 == 0:
            sg_window_length += 1

    breathing_denoised = savgol_filter(
        breathing_raw,
        window_length=sg_window_length,
        polyorder=sg_polyorder
    )

    # ------------------------------------------------------------
    # Step 8: normalization to [-1, 1]
    # ------------------------------------------------------------
    xmin = np.min(breathing_denoised)
    xmax = np.max(breathing_denoised)

    breathing_norm = -1 + 2 * (breathing_denoised - xmin) / (xmax - xmin + eps)

    result = {
        "breathing_signal_raw": breathing_raw,
        "breathing_signal_denoised": breathing_denoised,
        "breathing_signal_norm": breathing_norm,
        "selected_candidate_index": selected_idx,
        "selected_candidate_name": candidate_names[selected_idx],
        "candidate_names": candidate_names,
        "candidate_bnrs": candidate_bnrs,
        "all_combined_signals": all_combined,
        "all_weights": all_weights,
        "all_subcarrier_bnrs": all_subcarrier_bnrs,
    }

    return result
```

------

## 12.6 呼吸频率估计函数

```python
def estimate_respiration_rate(
    x,
    fs=50.0,
    rr_band=(0.1, 0.6),
    nperseg=1024
):
    """
    Estimate respiration rate from extracted breathing signal using PSD peak.

    Parameters
    ----------
    x : np.ndarray, shape (N,)
        Extracted breathing signal.
    fs : float
        Sampling frequency.
    rr_band : tuple
        Search band for respiration frequency.
    nperseg : int
        Welch PSD segment length.

    Returns
    -------
    rr_bpm : float
        Estimated respiration rate in breaths per minute.
    f_peak : float
        Peak frequency in Hz.
    f : np.ndarray
        Frequency bins.
    pxx : np.ndarray
        PSD.
    """
    x = np.asarray(x, dtype=float)
    x = detrend(x)

    nperseg = min(nperseg, len(x))

    f, pxx = welch(
        x,
        fs=fs,
        nperseg=nperseg,
        noverlap=nperseg // 2,
        scaling="density"
    )

    f_low, f_high = rr_band
    mask = (f >= f_low) & (f <= f_high)

    if not np.any(mask):
        raise ValueError("RR band does not overlap PSD frequency bins.")

    f_band = f[mask]
    pxx_band = pxx[mask]

    peak_idx = np.argmax(pxx_band)
    f_peak = f_band[peak_idx]
    rr_bpm = 60.0 * f_peak

    return rr_bpm, f_peak, f, pxx
```

------

## 12.7 完整使用示例

假设你已经读入一段 WCI/CSI 数据：

```python
# H should be complex ndarray with shape (3, 30, 3000)
# H = load_your_wci_data(...)
```

调用流程：

```python
fs = 50.0

result = extract_breathing_signal(
    H,
    fs=fs,
    breath_band=(0.1, 0.6),
    hampel_window=7,
    hampel_sigmas=3.0,
    sg_window_length=101,
    sg_polyorder=3,
    nperseg=512
)

breath = result["breathing_signal_norm"]

rr_bpm, f_peak, f, pxx = estimate_respiration_rate(
    breath,
    fs=fs,
    rr_band=(0.1, 0.6),
    nperseg=1024
)

print("Selected candidate:", result["selected_candidate_name"])
print("Candidate BNRs:")
for name, bnr in zip(result["candidate_names"], result["candidate_bnrs"]):
    print(f"  {name}: {bnr:.4f}")

print(f"Estimated respiration frequency: {f_peak:.4f} Hz")
print(f"Estimated respiration rate: {rr_bpm:.2f} bpm")
```

------

## 12.8 可视化结果

```python
t = np.arange(len(breath)) / fs

plt.figure(figsize=(12, 8))

plt.subplot(3, 1, 1)
plt.plot(t, result["breathing_signal_raw"])
plt.title("Selected MRC Combined Breathing Signal Before S-G Filtering")
plt.xlabel("Time (s)")
plt.ylabel("Amplitude")

plt.subplot(3, 1, 2)
plt.plot(t, result["breathing_signal_norm"])
plt.title("Final Normalized Breathing Signal")
plt.xlabel("Time (s)")
plt.ylabel("Normalized Amplitude")

plt.subplot(3, 1, 3)
plt.semilogy(f, pxx)
plt.axvline(f_peak, color="r", linestyle="--", label=f"Peak = {f_peak:.3f} Hz")
plt.xlim(0, 1.0)
plt.title(f"PSD and Estimated RR = {rr_bpm:.2f} bpm")
plt.xlabel("Frequency (Hz)")
plt.ylabel("PSD")
plt.legend()

plt.tight_layout()
plt.show()
```

------

# 13. 代码复现时的工程注意事项

------

## 13.1 原始 CSI/WCI 数据格式

不同采集工具输出格式可能不同。例如常见格式可能是：

```text
time × subcarrier × antenna
antenna × subcarrier × time
packet × rx × tx × subcarrier
```

而本文代码假设：

```python
H.shape == (3, 30, N)
```

如果你的数据是：

```python
H_raw.shape == (N, 30, 3)
```

需要转换：

```python
H = np.transpose(H_raw, (2, 1, 0))
```

------

## 13.2 相位是否需要 unwrap？

论文中对 WCI ratio 提取 phase，但没有明确说明是否 unwrap。

工程上建议：

```python
phase = np.unwrap(np.angle(ratio), axis=-1)
```

原因是原始 `angle` 输出范围是：

$[-\pi,\pi]$

如果相位跨越边界，会出现跳变。`unwrap` 可以减少人工相位跳变。

但由于呼吸引起的是小范围圆弧运动，如果 ratio 相位本身不跨越 $\pm\pi$，unwrap 影响不大。

------

## 13.3 是否需要带通滤波？

论文没有在前端明确使用传统 bandpass filter，而是使用：

```text
MRC-based BNR selection + S-G filter
```

如果你只做 RR estimation，可以在最终呼吸信号上增加带通滤波，例如：

```text
0.1–0.6 Hz
```

但如果你要做呼吸模式分类，过强的带通滤波可能会破坏 apnea、幅度渐变等形态信息。因此需要谨慎。

------

## 13.4 BNR 频段选择很关键

若使用：

```python
breath_band = (0.2, 0.33)
```

则更偏向正常呼吸。

若要覆盖异常呼吸，建议：

```python
breath_band = (0.1, 0.6)
```

如果包括 Kussmaul 或快速呼吸，也可考虑：

```python
breath_band = (0.08, 0.8)
```

但频段越宽，噪声也可能越多。

------

## 13.5 S-G 滤波参数影响波形形态

推荐初值：

```python
sg_window_length = 101
sg_polyorder = 3
```

若波形过度平滑，降低窗口长度：

```python
sg_window_length = 51
```

若噪声较大，提高窗口长度：

```python
sg_window_length = 151
```

但窗口过大可能削弱：

- apnea 边界；
- Biot 呼吸中的暂停；
- Cheyne–Stokes 中的幅度变化；
- 快速呼吸波形。

------

# 14. 若要复现论文 CNN-LSTM 分类模块

虽然你目前不关注深度学习分类，但为了完整性，这里保留论文模型参数。

------

## 14.1 输入

每个样本为：

```text
60 s 呼吸信号
采样率 50 Hz
长度 3000
输入尺寸：3000 × 1
```

------

## 14.2 CNN-LSTM 结构

论文 Fig. 10 给出的结构可以概括为：

```text
Input: 3000 × 1
    ↓
Two convolutional blocks
    Conv1D: filters=96, kernel_size=250, padding=same, stride=1
    BatchNorm
    ReLU
    MaxPooling1D: pool_size=4, stride=4
    ↓
Flatten
    ↓
LSTM: hidden units=100
    ↓
Flatten
    ↓
Fully Connected
    ↓
Softmax
    ↓
6-class output
```

------

## 14.3 训练参数

| 参数            | 值     |
| --------------- | ------ |
| learning rate   | 0.0005 |
| mini-batch size | 60     |
| epochs          | 50     |
| optimizer       | Adam   |
| classes         | 6      |

------

## 14.4 数据集划分

论文数据：

| 项目         | 数量 |
| ------------ | ---- |
| 受试者       | 20   |
| 男           | 12   |
| 女           | 8    |
| 每类样本数   | 1075 |
| 类别数       | 6    |
| 总样本数     | 6450 |
| 每类训练样本 | 1000 |
| 每类测试样本 | 75   |
| 总训练样本   | 6000 |
| 总测试样本   | 450  |

------

# 15. 实验结果总结

------

## 15.1 CNN、LSTM、CNN-LSTM 比较

| 模型     | Accuracy | Precision | Recall | F1    |
| -------- | -------- | --------- | ------ | ----- |
| CNN      | 96.2%    | 96.6%     | 96.2%  | 96.4% |
| LSTM     | 90.7%    | 91.4%     | 90.7%  | 91.0% |
| CNN-LSTM | 97.8%    | 97.9%     | 97.8%  | 97.8% |

CNN-LSTM 最优。

------

## 15.2 不同环境测试

| 环境     | Accuracy | Precision | Recall | F1    |
| -------- | -------- | --------- | ------ | ----- |
| Corridor | 98.1%    | 98.2%     | 98.1%  | 98.1% |
| Bedroom  | 97.5%    | 98.0%     | 97.5%  | 97.7% |
| Office   | 96.7%    | 96.7%     | 96.7%  | 96.7% |

办公室最低，原因是障碍物更多，静态多径更多，BNR 降低。

------

## 15.3 与已有工作比较

| 方法         | 技术                  | 分类器        | 类别数 | Accuracy |
| ------------ | --------------------- | ------------- | ------ | -------- |
| Zhao et al.  | 2.4 GHz Doppler radar | SVM           | 6      | 94.7%    |
| Kim et al.   | UWB radar             | 1D CNN        | 5      | 93.9%    |
| Saeed et al. | USRP                  | DMLP          | 6      | 99%      |
| He et al.    | IR-UWB + Kinect       | Random Forest | 5      | 90%      |
| This work    | WiFi                  | CNN-LSTM      | 6      | 97.8%    |

------

# 16. 该方法用于呼吸频率估计时的建议实现

如果你的目标不是六分类，而是呼吸频率估计，建议最终实现如下：

```text
Input:
    H: complex WCI/CSI, shape = 3 × 30 × N

Preprocessing:
    1. Compute WCI ratios:
        H12 = H1 / H2
        H13 = H1 / H3
        H23 = H2 / H3

    2. Extract amplitude and phase:
        abs(H12), angle(H12)
        abs(H13), angle(H13)
        abs(H23), angle(H23)

    3. For each of the 6 candidate groups:
        a. Hampel filter each subcarrier
        b. Estimate BNR using PSD
        c. Compute MRC weights
        d. Weighted sum across 30 subcarriers

    4. Select candidate group with highest BNR

    5. Apply Savitzky–Golay filter

    6. Normalize to [-1, 1]

RR Estimation:
    7. Compute PSD of final breathing signal
    8. Find dominant frequency in 0.1–0.6 Hz
    9. RR = 60 × f_peak
```

------

# 17. 该方法的优点与局限

------

## 17.1 优点

1. 不需要专用雷达硬件；
2. 使用 WiFi 信号，成本低；
3. WCI ratio 可以有效减轻相位偏移问题；
4. 同时考虑幅度和相位，鲁棒性更好；
5. MRC 利用多子载波分集，提高 BNR；
6. S-G 滤波可以保留呼吸波形形态；
7. 输出的 60 s 波形既可用于 RR estimation，也可用于模式分类。

------

## 17.2 局限

1. 论文主要评价分类准确率，没有系统报告 RR 估计误差；
2. 异常呼吸数据来自健康受试者模拟，不是真实病人；
3. BNR 频段定义存在复现不确定性；
4. Hampel 和 S-G 参数未详细给出；
5. 对多人场景、运动干扰、强动态环境讨论不足；
6. 对不同距离、角度、穿墙、遮挡等场景的 RR 精度没有详细量化；
7. MRC 权重具体公式没有在文中完全展开，复现时需要合理假设。

------

# 18. 最终结论

这篇文章前端信号处理部分可以概括为：

```text
WCI Ratio + Amplitude/Phase Complementarity + MRC Subcarrier Combination + S-G Filter
```

它的作用是：

> 从受多径、相位偏移和噪声影响的 WiFi WCI/CSI 数据中，提取一条高 BNR 的呼吸波形。

如果你的目标是呼吸频率估计，可以在论文输出的最终呼吸波形上继续做：

```text
PSD/FFT 主峰搜索
```

得到：

$RR=60f_{\text{peak}}$

需要特别注意：

1. 文中没有使用 VMD；
2. MRC 是对子载波做 BNR 加权合并；
3. 先分别处理三组 WCI ratio 的幅度和相位；
4. 最后从六条合并波形中选择 BNR 最高的一条；
5. 论文主任务是呼吸模式分类，不是 RR estimation；
6. 若复现 RR estimation，需要自行设计 RR 误差评估实验。

推荐复现默认参数如下：

```python
fs = 50.0
window_length_seconds = 60
num_samples = 3000
num_rx = 3
num_subcarriers = 30

breath_band = (0.1, 0.6)
rr_band = (0.1, 0.6)

hampel_window = 7
hampel_sigmas = 3.0

welch_nperseg_bnr = 512
welch_nperseg_rr = 1024

sg_window_length = 101
sg_polyorder = 3
```

如果你后续要写代码复现，可以直接从本报告第 12 节的 Python 代码开始改造。