
# 论文方法详解报告：Position-Free Breath Detection During Sleep via Commodity WiFi

## 1. 论文基本信息

**论文题目：** Position-Free Breath Detection During Sleep via Commodity WiFi  
**期刊：** IEEE Sensors Journal  
**年份：** 2023  
**作者：** Hongyang Zhuo, Xianda Wu, Qinghua Zhong, Han Zhang  

本文研究的是基于商用 WiFi CSI 的非接触式睡眠呼吸检测问题。系统利用一对 WiFi 设备、多个天线和 CSI ratio 信号，在未知睡姿条件下实现鲁棒的呼吸信号提取和呼吸率估计。

---

## 2. 一句话概括

这篇文章提出了一个基于商用 WiFi CSI ratio 的睡眠呼吸检测系统。方法先利用 CSI ratio 抵消商用 WiFi 设备中的随机相位偏移，再通过复平面投影联合利用幅度和相位互补性，使用周期性与变化性联合评分选择最优呼吸模式信号，随后通过波形方向调整、PCA 多子载波融合和 VMD 模态分解提取干净的呼吸成分，最后使用峰值检测和伪峰剔除估计呼吸率。

---

## 3. 对原始理解的修正

你之前的理解是：

> 这篇文章大概是 MRC + VMD 做呼吸信号的信噪比提升，以及频率估计。

这个理解抓住了“信噪比提升”和“频率估计”这个主线，但方法名称需要修正。

本文提出的核心融合方法不是 **MRC + VMD**，而是：

> **PCA + VMD**

其中：

- **MRC** 是文章用来对比的 baseline；
- **PCA-VMD** 才是本文提出的主要融合方案；
- MRC 的问题是容易受到坏子载波、反相波形和冗余噪声成分影响；
- PCA-VMD 先提取多子载波中的主导呼吸成分，再通过 VMD 提取更干净的呼吸模态。

更准确的理解应为：

> 这篇文章提出了一个 CSI ratio 复平面投影、周期性/变化性联合呼吸模式选择、PCA-VMD 多天线多子载波融合的 WiFi 睡眠呼吸检测方法，用于提升不同睡姿下的呼吸信号质量，并进行高精度呼吸率估计。

---

# 4. 研究背景

## 4.1 为什么需要非接触式睡眠呼吸检测？

呼吸率是重要的生理指标，可用于辅助判断：

- 睡眠呼吸暂停；
- 夜间低通气；
- 慢性阻塞性肺病；
- 心肺健康状态；
- 睡眠质量。

传统呼吸检测设备包括：

- 多导睡眠监测 PSG；
- 胸带；
- 鼻气流传感器；
- 可穿戴传感器。

这些设备的问题是：

1. 佩戴复杂；
2. 可能影响睡眠；
3. 长期使用舒适性差；
4. 家庭部署成本较高；
5. 第一晚效应可能影响真实睡眠状态。

WiFi 呼吸检测的优势是：

- 非接触；
- 无需佩戴；
- 可复用家庭已有 WiFi 设备；
- 对用户打扰小；
- 有潜力长期部署。

---

## 4.2 为什么选择 CSI 而不是 RSSI？

早期 WiFi 感知常用 RSSI，即 received signal strength indicator。

但 RSSI 的问题是：

- 粒度粗；
- 只反映整体接收强度；
- 对微小胸腔运动不够敏感；
- 难以描述多径变化。

CSI，即 channel state information，可以提供更细粒度的信道信息。

对于 OFDM WiFi 系统，CSI 可以描述每个子载波上的信道频率响应：

\[
H(f,t)
\]

CSI 通常是复数，包含：

- 幅度；
- 相位。

因此它更适合感知人体呼吸这类毫米级微动。

---

# 5. 现有方法不足

## 5.1 幅度或相位单独使用会出现 blind spot

WiFi 信号在室内传播时包括：

- 静态路径：墙壁、家具等反射；
- 动态路径：人体呼吸导致的反射变化。

CSI 可以表示为：

\[
H(f,t)=H_s(f)+H_d(f,t)
\]

其中：

\[
H_d(f,t)=a(f,t)e^{-j2\pi d(t)/\lambda}
\]

于是：

\[
H(f,t)=H_s(f)+a(f,t)e^{-j2\pi d(t)/\lambda}
\]

其中：

- \(H_s(f)\)：静态路径成分；
- \(H_d(f,t)\)：动态路径成分；
- \(a(f,t)\)：动态路径复增益；
- \(d(t)\)：动态路径长度；
- \(\lambda\)：信号波长。

人体呼吸会引起胸腔位移，导致 \(d(t)\) 发生微小变化，从而引起 CSI 变化。

但在不同几何关系下，呼吸造成的 CSI 变化可能主要体现在：

- 幅度变化；
- 或相位变化。

因此：

- 只用 CSI amplitude，可能在幅度不敏感区域失败；
- 只用 CSI phase，可能在相位不敏感区域失败。

这就是所谓的 **blind spot** 问题。

---

## 5.2 商用 WiFi 设备的 CSI 相位不可靠

商用 WiFi 网卡提取到的 CSI 相位通常包含大量硬件误差，例如：

- sampling frequency offset, SFO；
- carrier frequency offset, CFO；
- packet detection delay, PDD；
- random phase offset。

因此原始 CSI 相位不能直接用于呼吸检测。

本文采用 **CSI ratio** 方法抵消共同相位偏移。

---

## 5.3 只根据周期性选择呼吸信号容易选错

很多已有方法会选择周期性最强的信号作为呼吸信号。

但本文指出：

> 周期性强不一定意味着频率正确。

在某些情况下，一个投影信号看起来非常规整，但它的频率可能是实际呼吸频率的两倍。

因此只使用 BNR、PSD 峰值或周期性能量指标可能导致错误选择。

本文的改进是同时考虑：

1. 周期性，periodicity；
2. 变化性，variability。

---

## 5.4 单天线对无法覆盖所有睡姿

人在睡眠时存在多种姿态，例如：

- fetus；
- log；
- yearner；
- soldier；
- freefaller；
- starfish。

不同睡姿下，胸腔呼吸位移在 WiFi 链路方向上的投影不同。

一般来说：

- 胸部正对 LoS 链路时，信号变化最大；
- 身体侧面对 LoS 链路时，信号变化最小；
- 背部对 LoS 链路时，信号变化介于二者之间。

文章引用的人体呼吸位移范围为：

- 胸前方向：约 \(4.2\text{--}5.4\ \text{mm}\)；
- 身体侧向：约 \(0.6\text{--}1.1\ \text{mm}\)。

因此一个 TX-RX 链路在某个睡姿下可能表现很好，在另一个睡姿下可能信噪比很低。

---

## 5.5 传统融合方法不充分

已有方法通常使用：

- 多子载波加权；
- 多链路加权；
- 呼吸率结果加权；
- MRC 最大比合并。

这些方法的问题包括：

1. 坏子载波仍然可能参与融合；
2. 方向相反的呼吸波形会互相抵消；
3. 加权融合无法彻底剥离非呼吸频率成分；
4. 融合后可能仍有伪峰和噪声；
5. 多天线的互补优势没有被充分利用。

本文因此提出 PCA-VMD 融合方案。

---

# 6. 本文主要贡献

## 6.1 从睡姿角度分析 WiFi 呼吸检测问题

本文强调睡眠姿态是影响 WiFi 呼吸检测性能的重要因素。睡姿会改变胸腔运动相对于 WiFi 链路的方向，从而影响信号幅度和信噪比。

---

## 6.2 使用 CSI ratio 缓解商用设备相位偏移问题

通过对两个天线或链路的 CSI 做 ratio，可以抵消共同随机相位偏移，使得相位信息更可用。

---

## 6.3 通过复平面投影联合利用幅度和相位

本文不是简单地使用 amplitude 或 phase，而是将 CSI ratio 看作复平面轨迹，通过不同方向的投影生成多个候选呼吸信号，从而利用 I/Q 正交互补性。

---

## 6.4 使用周期性和变化性联合选择呼吸模式

本文提出使用：

\[
S(j)=w_1\cdot \text{Bnr}(j)+w_2\cdot \text{Var}(j)
\]

选择最优投影候选，其中：

\[
w_1=w_2=0.5
\]

这种方法避免了只看周期性或只看方差带来的错误选择。

---

## 6.5 提出 PCA-VMD 多天线多子载波融合

本文先用 PCA 从多子载波中提取主导呼吸成分，再用 VMD 分解出更细的呼吸频率模态。

其中 VMD 模态数设置为：

\[
K=3
\]

最后选择方差最大的模态作为最终呼吸信号。

---

# 7. 系统输入与硬件配置

## 7.1 硬件配置

论文实验中使用：

| 模块 | 配置 |
|---|---|
| TX | TP-Link wireless router |
| RX | Ubuntu 14.04 LTS microhost |
| WiFi 网卡 | Intel 5300 NIC |
| 中心频率 | 5.785 GHz |
| 带宽 | 20 MHz |
| TX 天线数 | 2 |
| RX 天线数 | 2 |
| 子载波数 | 每个 TX-RX 对 30 个 |
| TX 到 RX1 距离 | 180 cm |
| TX 到 RX2 距离 | 100 cm |
| 天线类型 | 普通全向天线 |
| 天线摆放 | 平行于地面 |

---

## 7.2 CSI 数据维度

MIMO 系统中，CSI 数据维度为：

\[
M \times N \times 30
\]

其中：

- \(M\)：发射天线数；
- \(N\)：接收天线数；
- 30：Intel 5300 提供的子载波数量。

本文中：

\[
M=2,\quad N=2
\]

因此每个 CSI packet 包含：

\[
2\times 2\times 30 = 120
\]

个 CSI stream。

---

# 8. 方法整体流程

本文方法可以分为三大模块：

1. 数据预处理；
2. 幅度与相位联合呼吸模式选择；
3. 自适应融合与呼吸率估计。

完整流程如下：

```text
Raw CSI
  ↓
CSI Ratio Extraction
  ↓
Savitzky-Golay Smoothing
  ↓
Projection on Complex Plane
  ↓
Candidate Respiratory Pattern Generation
  ↓
BNR + Variance Scoring
  ↓
Best Respiratory Pattern Selection
  ↓
Linear Interpolation
  ↓
Savitzky-Golay Filtering
  ↓
Waveform Direction Adjustment
  ↓
False Peak / Low-frequency Interference Handling
  ↓
PCA Fusion
  ↓
VMD Decomposition
  ↓
Breath Component Selection
  ↓
Peak Detection
  ↓
False Peak Removal
  ↓
Breath Rate Estimation
~~~
```

# 9. 详细信号处理流程

------

## 9.1 Step 1：原始 CSI 获取

对每个时间采样点 $t$，获取 CSI：

$H_{m,n,k}(t)$

其中：

- $m \in \{1,2\}$：TX 天线索引；
- $n \in \{1,2\}$：RX 天线索引；
- $k \in \{1,\dots,30\}$：子载波索引。

因此原始 CSI 可表示为：

$H(t)\in \mathbb{C}^{2\times 2\times 30}$

假设总采样点数为 $T$，则数据可组织为：

$H\in \mathbb{C}^{T\times 2\times 2\times 30}$

------

## 9.2 Step 2：CSI ratio 提取

本文使用两个 TX 天线在同一 RX 天线上形成 ratio。

对每个 RX 天线 $n$ 和子载波 $k$，计算：

$R_{n,k}(t)=\frac{H_{1,n,k}(t)}{H_{2,n,k}(t)}$

其中：

- $H_{1,n,k}(t)$：TX1 到 RX$n$ 的第 $k$ 个子载波 CSI；
- $H_{2,n,k}(t)$：TX2 到 RX$n$ 的第 $k$ 个子载波 CSI。

每个 RX 产生 30 个 CSI ratio：

$R_{n,k}(t),\quad k=1,\dots,30$

两个 RX 总共得到：

$2\times 30 = 60$

个 CSI ratio stream。

数据维度变为：

$R\in \mathbb{C}^{T\times 60}$

------

## 9.3 Step 3：CSI ratio 平滑

CSI ratio 仍包含随机噪声。本文对每个复数 ratio 的实部和虚部分别使用 Savitzky-Golay filter。

如果：

$R_i(t)=I_i(t)+jQ_i(t)$

则分别处理：

$\tilde{I}_i(t)=\text{SGFilter}(I_i(t))$

$\tilde{Q}_i(t)=\text{SGFilter}(Q_i(t))$

然后重新组合：

$\tilde{R}_i(t)=\tilde{I}_i(t)+j\tilde{Q}_i(t)$

论文没有明确给出 Savitzky-Golay 的窗口长度和多项式阶数。复现时可以根据采样率设置。

如果采样率约为 100 Hz，可考虑：

| 参数          | 示例值      |
| ------------- | ----------- |
| window_length | 31, 51, 101 |
| polyorder     | 2 或 3      |

注意 window length 必须为奇数。

------

## 9.4 Step 4：复平面投影生成候选信号

CSI ratio 是复数：

$\tilde{R}_i(t)=I_i(t)+jQ_i(t)$

将其看作二维点：

$\mathbf{r}_i(t)= \begin{bmatrix} I_i(t)\\ Q_i(t) \end{bmatrix}$

定义投影轴：

$\mathbf{u}(\theta)= \begin{bmatrix} \cos\theta\\ \sin\theta \end{bmatrix}$

投影得到一维候选信号：

$x_{i,\theta}(t)=I_i(t)\cos\theta+Q_i(t)\sin\theta$

由于投影轴具有对称性，本文设置：

$\theta \in [0,\pi]$

步长为：

$\Delta \theta = \frac{\pi}{100}$

因此每个子载波生成 100 个候选信号。

实际实现可以使用：

$\theta_j = \frac{j\pi}{100},\quad j=0,1,\dots,99$

或者 $j=1,\dots,100$。两种写法只要保持 100 个候选即可。

------

## 9.5 Step 5：使用前 12 秒数据选择最佳投影轴

本文使用每个子载波信号的前 12 s 数据进行呼吸模式选择。

假设采样率为：

$f_s = 100\ \text{Hz}$

则前 12 s 对应：

$N_{\text{sel}}=12\times 100=1200$

个样本。

文章为了提高频谱计算精度，对 1200 个样本做 zero-padding 到：

$N_{\text{FFT}}=8192$

注意：zero-padding 不提升真实频谱分辨率，但可以使频谱峰位置的采样更密集，便于计算 BNR。

------

## 9.6 Step 6：计算 BNR

BNR 即 breathing-to-noise ratio，用来衡量呼吸频段能量占比。

论文引用的是 short-term BNR 思想，但未在正文中给出非常具体的频带上下限。复现时可根据常见成人呼吸频率设置呼吸频带。

常见呼吸频率范围：

- 10 breaths/min $\approx 0.167\ \text{Hz}$；
- 37 breaths/min $\approx 0.617\ \text{Hz}$。

可以设置：

$f_{\text{low}}=0.1\ \text{Hz}$

$f_{\text{high}}=0.7\ \text{Hz}$

或者更保守地设置：

$f_{\text{low}}=0.1\ \text{Hz},\quad f_{\text{high}}=0.5\ \text{Hz}$

若需要覆盖论文中的 37 breaths/min，应使用上限至少 $0.65\ \text{Hz}$。

对候选信号 $x(t)$，计算 FFT：

$X(f)=\text{FFT}(x(t))$

功率谱：

$P(f)=|X(f)|^2$

BNR 可定义为：

$\text{BNR}= \frac{ \sum_{f\in [f_{\text{low}},f_{\text{high}}]}P(f) }{ \sum_{f\in [0,f_s/2]}P(f) }$

也可以排除 DC 分量：

$\text{BNR}= \frac{ \sum_{f\in [f_{\text{low}},f_{\text{high}}]}P(f) }{ \sum_{f\in [f_{\min},f_s/2]}P(f) }$

其中 $f_{\min}$ 可取 0.05 Hz。

------

## 9.7 Step 7：计算 variance

对候选信号 $x(t)$，计算方差：

$\text{Var}=\frac{1}{N}\sum_{t=1}^{N}(x(t)-\bar{x})^2$

variance 用于衡量信号变化幅度。

------

## 9.8 Step 8：BNR 和 variance 归一化

对同一个子载波的 100 个候选，分别得到：

$\text{BNR}_1,\dots,\text{BNR}_{100}$

$\text{Var}_1,\dots,\text{Var}_{100}$

需要进行归一化。

可使用 min-max normalization：

$\widehat{\text{BNR}}_j= \frac{ \text{BNR}_j-\min(\text{BNR}) }{ \max(\text{BNR})-\min(\text{BNR})+\epsilon }$

$\widehat{\text{Var}}_j= \frac{ \text{Var}_j-\min(\text{Var}) }{ \max(\text{Var})-\min(\text{Var})+\epsilon }$

其中 $\epsilon$ 是防止除零的小常数，例如：

$\epsilon=10^{-8}$

------

## 9.9 Step 9：联合评分选择最佳呼吸模式

本文定义评分：

$S(j)=w_1\cdot \widehat{\text{BNR}}_j+w_2\cdot \widehat{\text{Var}}_j$

其中：

$w_1=w_2=0.5$

选择：

$j^\*=\arg\max_j S(j)$

对应的投影角度为：

$\theta^\*=\theta_{j^\*}$

最终该子载波的呼吸模式信号为：

$x_i(t)=I_i(t)\cos\theta^\*+Q_i(t)\sin\theta^\*$

对 60 个 CSI ratio stream 都执行上述过程，得到 60 个候选后的最优呼吸信号：

$X(t)\in \mathbb{R}^{T\times 60}$

------

## 9.10 Step 10：线性插值

由于 WiFi 包可能丢失或时间戳不均匀，需要对信号进行插值。

假设原始时间戳为：

$t_1,t_2,\dots,t_N$

目标均匀时间轴为：

$\tau_1,\tau_2,\dots,\tau_M$

使用线性插值：

$x(\tau)=\text{LinearInterp}(t,x(t),\tau)$

如果原始数据已经是均匀采样，可以跳过此步。

------

## 9.11 Step 11：Savitzky-Golay 滤波

对每个选出的呼吸模式信号再次使用 Savitzky-Golay filter。

目的：

- 去除高频噪声；
- 保留呼吸波形形状；
- 避免峰宽和峰位过度畸变。

示例参数：

| 采样率 | window_length | polyorder |
| ------ | ------------- | --------- |
| 50 Hz  | 21 或 31      | 2 或 3    |
| 100 Hz | 51 或 101     | 2 或 3    |
| 200 Hz | 101 或 201    | 2 或 3    |

如果后续还要进行呼吸频带带通滤波，也可以设置：

$0.1\text{--}0.7\ \text{Hz}$

------

## 9.12 Step 12：波形方向调整

不同子载波的呼吸波形可能方向相反。为避免融合时抵消，需要统一方向。

论文做法大致为：

1. 对每个子载波信号做峰值检测；
2. 找到第一个峰和第一个谷；
3. 判断第一个呼吸周期的上升/下降方向；
4. 以信噪比最高的信号作为参考；
5. 若某信号方向与参考相反，则乘以 $-1$。

一种可复现的简化实现：

### 方法 A：基于与参考信号的相关系数

1. 先选出评分最高或 BNR 最高的子载波作为参考信号 $x_{\text{ref}}$；
2. 对每个信号 $x_i$，计算相关系数：

$\rho_i=\text{corr}(x_i,x_{\text{ref}})$

1. 如果：

$\rho_i<0$

则：

$x_i \leftarrow -x_i$

这种方法实现简单，在工程复现中很常用。

### 方法 B：基于第一个峰谷方向

更贴近论文描述：

- 若第一个显著极值是峰，则方向记为一种方向；
- 若第一个显著极值是谷，则方向相反；
- 与最高 SNR 信号方向对齐。

但这种方法对峰值检测稳定性要求更高。

------

## 9.13 Step 13：Hampel filter 去除异常点和低频干扰

论文提到使用 Hampel filter 处理零频干扰和环境成分。

Hampel filter 是一种基于滑动窗口中位数和 MAD 的异常值检测方法。

对于窗口内数据：

$m=\text{median}(x)$

$MAD=\text{median}(|x-m|)$

若某点满足：

$|x_i-m| > n_\sigma \cdot 1.4826 \cdot MAD$

则认为是异常点，并用中位数替换。

常用参数：

| 参数        | 示例                    |
| ----------- | ----------------------- |
| window size | 0.5 s 到 2 s 对应样本数 |
| $n_\sigma$  | 3                       |

------

## 9.14 Step 14：PCA 融合

经过前面处理后，得到矩阵：

$X\in \mathbb{R}^{T\times 60}$

其中：

- 每一列是一个子载波/链路的呼吸模式信号；
- 每一行是一个时间点。

首先中心化：

$X_c = X - \mu$

其中 $\mu$ 是每列均值。

PCA 的目标是寻找最大方差方向。

协方差矩阵：

$C=\frac{1}{T-1}X_c^T X_c$

求最大特征值对应的特征向量：

$\mathbf{v}_1$

PCA 融合信号为：

$y_{\text{PCA}}=X_c\mathbf{v}_1$

即第一主成分。

论文称其为 dominant respiratory signal。

------

## 9.15 Step 15：VMD 分解

对 PCA signal 进行 VMD。

VMD 将信号分解为 $K$ 个模态：

$y_{\text{PCA}}(t)=\sum_{k=1}^{K}u_k(t)$

其中每个 $u_k(t)$ 是一个具有中心频率的窄带模态。

论文设置：

$K=3$

然后选择方差最大的模态作为最终呼吸信号：

$k^\*=\arg\max_k \text{Var}(u_k)$

$y_{\text{final}}(t)=u_{k^\*}(t)$

这就是 PCA-VMD signal。

------

## 9.16 Step 16：峰值检测

对最终信号 $y_{\text{final}}(t)$ 做峰值检测。

如果预期呼吸频率范围为：

$0.1\text{--}0.7\ \text{Hz}$

则呼吸周期范围为：

$T_b \in [1/0.7,1/0.1]\approx [1.43,10]\ \text{s}$

峰间最小距离可设置为：

$d_{\min}=f_s \times 1.0\text{--}1.5\ \text{s}$

如果只考虑成人正常呼吸：

$0.1\text{--}0.5\ \text{Hz}$

则最小峰距可设置为：

$d_{\min}=f_s \times 1.5\text{--}2.0\ \text{s}$

论文中还使用 false peak removal 方法进一步移除伪峰。

------

## 9.17 Step 17：伪峰剔除

伪峰来源包括：

- 小凸包；
- 噪声尖峰；
- 投影误差；
- 深浅呼吸交替时的局部波形畸变。

一种简单可复现的伪峰剔除策略：

1. 检测所有候选峰；
2. 计算相邻峰间隔；
3. 如果某个峰导致间隔明显小于合理呼吸周期下限，则剔除；
4. 可以结合 prominence 或 amplitude threshold。

例如：

$\Delta t_i = t_{i+1}-t_i$

若：

$\Delta t_i < T_{\min}$

则两个峰中保留 prominence 更大的一个。

其中：

$T_{\min}=1.0\text{--}1.5\ \text{s}$

------

## 9.18 Step 18：呼吸率估计

设最终真实峰位置为：

$p_1,p_2,\dots,p_L$

对应时间为：

$t_{p_1},t_{p_2},\dots,t_{p_L}$

平均呼吸周期：

$\bar{T}=\frac{1}{L-1}\sum_{i=1}^{L-1}(t_{p_{i+1}}-t_{p_i})$

呼吸频率：

$f_b=\frac{1}{\bar{T}}$

呼吸率，单位 breaths/min：

$BR=\frac{60}{\bar{T}}$

论文实验中每个 3 min 片段计算一次呼吸率。

------

# 10. 推荐复现参数表

| 模块             | 参数                 | 论文/建议值                    |
| ---------------- | -------------------- | ------------------------------ |
| CSI 维度         | TX × RX × subcarrier | $2\times2\times30$             |
| CSI ratio 数量   | stream 数            | 60                             |
| 呼吸模式选择窗口 | duration             | 12 s                           |
| 选择窗口样本数   | samples              | 1200，若 $f_s=100\ \text{Hz}$  |
| FFT zero-padding | $N_{\text{FFT}}$     | 8192                           |
| 投影角范围       | $\theta$             | $[0,\pi]$                      |
| 投影步长         | $\Delta\theta$       | $\pi/100$                      |
| 每子载波候选数   | candidates           | 100                            |
| 评分权重         | $w_1,w_2$            | 0.5, 0.5                       |
| SG filter        | window               | 31/51/101，依采样率调整        |
| SG filter        | polyorder            | 2 或 3                         |
| 呼吸频带         | band                 | 0.1–0.7 Hz，建议覆盖异常快呼吸 |
| PCA 成分数       | component            | 1                              |
| VMD 模态数       | $K$                  | 3                              |
| VMD 选模态准则   | criterion            | 最大方差                       |
| 呼吸率估计       | method               | 峰值间隔                       |
| 实验片段长度     | duration             | 3 min                          |

------

# 11. Python 示例代码

下面给出一个尽量贴近论文流程的示例代码。
 注意：这是复现框架，不是论文官方代码。实际使用时需要根据你的 CSI 数据格式进行适配。

------

## 11.1 依赖库

```python
import numpy as np
from scipy.signal import savgol_filter, find_peaks, butter, filtfilt
from sklearn.decomposition import PCA
```

如果使用 VMD，可安装第三方库：

```bash
pip install vmdpy
```

然后：

```python
from vmdpy import VMD
```

------

## 11.2 CSI ratio 提取

假设原始 CSI 数据格式为：

```python
# H shape: [T, TX, RX, Subcarrier]
# dtype: complex
# example: H.shape = [T, 2, 2, 30]
```

代码：

```python
def extract_csi_ratio(H, eps=1e-8):
    """
    Extract CSI ratio streams.

    Parameters
    ----------
    H : np.ndarray
        Complex CSI data with shape [T, 2, 2, 30].
        H[:, tx, rx, subcarrier]
    eps : float
        Small constant to avoid division by zero.

    Returns
    -------
    R : np.ndarray
        CSI ratio streams with shape [T, 60].
    """
    T, num_tx, num_rx, num_sc = H.shape
    assert num_tx == 2
    assert num_rx == 2
    assert num_sc == 30

    ratio_streams = []

    for rx in range(num_rx):
        for sc in range(num_sc):
            numerator = H[:, 0, rx, sc]
            denominator = H[:, 1, rx, sc]
            ratio = numerator / (denominator + eps)
            ratio_streams.append(ratio)

    R = np.stack(ratio_streams, axis=1)  # [T, 60]
    return R
```

------

## 11.3 Savitzky-Golay 平滑复数 CSI ratio

```python
def smooth_complex_ratio(R, window_length=51, polyorder=3):
    """
    Smooth real and imaginary parts of CSI ratio separately.

    Parameters
    ----------
    R : np.ndarray
        Complex CSI ratio, shape [T, num_streams].
    window_length : int
        Window length for Savitzky-Golay filter. Must be odd.
    polyorder : int
        Polynomial order.

    Returns
    -------
    R_smooth : np.ndarray
        Smoothed complex CSI ratio.
    """
    T, D = R.shape

    if window_length >= T:
        window_length = T - 1 if (T - 1) % 2 == 1 else T - 2

    if window_length % 2 == 0:
        window_length += 1

    R_smooth = np.zeros_like(R, dtype=np.complex128)

    for d in range(D):
        real_sm = savgol_filter(np.real(R[:, d]), window_length, polyorder)
        imag_sm = savgol_filter(np.imag(R[:, d]), window_length, polyorder)
        R_smooth[:, d] = real_sm + 1j * imag_sm

    return R_smooth
```

------

## 11.4 BNR 计算

```python
def compute_bnr(x, fs, n_fft=8192, band=(0.1, 0.7), f_min_total=0.05):
    """
    Compute breathing-to-noise ratio.

    Parameters
    ----------
    x : np.ndarray
        1D signal.
    fs : float
        Sampling frequency.
    n_fft : int
        FFT length.
    band : tuple
        Breathing frequency band in Hz.
    f_min_total : float
        Minimum frequency considered in denominator to avoid DC dominance.

    Returns
    -------
    bnr : float
        Breathing-to-noise ratio.
    """
    x = np.asarray(x)
    x = x - np.mean(x)

    X = np.fft.rfft(x, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / fs)
    power = np.abs(X) ** 2

    breath_mask = (freqs >= band[0]) & (freqs <= band[1])
    total_mask = (freqs >= f_min_total) & (freqs <= fs / 2)

    breath_energy = np.sum(power[breath_mask])
    total_energy = np.sum(power[total_mask]) + 1e-12

    return breath_energy / total_energy
```

------

## 11.5 投影候选生成与最佳呼吸模式选择

```python
def minmax_norm(arr, eps=1e-8):
    arr = np.asarray(arr)
    return (arr - np.min(arr)) / (np.max(arr) - np.min(arr) + eps)


def select_best_projection_for_stream(
    r,
    fs,
    select_duration=12.0,
    num_angles=100,
    n_fft=8192,
    band=(0.1, 0.7),
    w_bnr=0.5,
    w_var=0.5
):
    """
    Select best projection axis for one CSI ratio stream.

    Parameters
    ----------
    r : np.ndarray
        Complex CSI ratio stream, shape [T].
    fs : float
        Sampling frequency.
    select_duration : float
        Duration used for respiratory pattern selection, in seconds.
    num_angles : int
        Number of projection candidates.
    n_fft : int
        FFT length for BNR.
    band : tuple
        Breathing frequency band.
    w_bnr : float
        Weight for BNR.
    w_var : float
        Weight for variance.

    Returns
    -------
    best_signal : np.ndarray
        Selected projected signal, shape [T].
    best_theta : float
        Best projection angle.
    score_info : dict
        Candidate BNRs, variances, and scores.
    """
    T = len(r)
    N_sel = min(int(select_duration * fs), T)

    I = np.real(r)
    Q = np.imag(r)

    # Use 100 axes in [0, pi)
    thetas = np.linspace(0, np.pi, num_angles, endpoint=False)

    candidates_full = []
    bnrs = []
    variances = []

    for theta in thetas:
        x = I * np.cos(theta) + Q * np.sin(theta)
        x_sel = x[:N_sel]

        bnr = compute_bnr(x_sel, fs=fs, n_fft=n_fft, band=band)
        var = np.var(x_sel)

        candidates_full.append(x)
        bnrs.append(bnr)
        variances.append(var)

    bnrs = np.array(bnrs)
    variances = np.array(variances)

    bnrs_norm = minmax_norm(bnrs)
    vars_norm = minmax_norm(variances)

    scores = w_bnr * bnrs_norm + w_var * vars_norm
    best_idx = int(np.argmax(scores))

    best_signal = candidates_full[best_idx]
    best_theta = thetas[best_idx]

    score_info = {
        "thetas": thetas,
        "bnrs": bnrs,
        "variances": variances,
        "scores": scores,
        "best_idx": best_idx
    }

    return best_signal, best_theta, score_info


def select_best_projections(
    R,
    fs,
    select_duration=12.0,
    num_angles=100,
    n_fft=8192,
    band=(0.1, 0.7),
    w_bnr=0.5,
    w_var=0.5
):
    """
    Select best projected respiratory pattern for all CSI ratio streams.

    Parameters
    ----------
    R : np.ndarray
        Complex CSI ratio streams, shape [T, D].

    Returns
    -------
    X : np.ndarray
        Selected real-valued respiratory signals, shape [T, D].
    theta_list : list
        Best projection angle for each stream.
    infos : list
        Score information for each stream.
    """
    T, D = R.shape
    X = np.zeros((T, D), dtype=float)
    theta_list = []
    infos = []

    for d in range(D):
        best_signal, best_theta, info = select_best_projection_for_stream(
            R[:, d],
            fs=fs,
            select_duration=select_duration,
            num_angles=num_angles,
            n_fft=n_fft,
            band=band,
            w_bnr=w_bnr,
            w_var=w_var
        )
        X[:, d] = best_signal
        theta_list.append(best_theta)
        infos.append(info)

    return X, theta_list, infos
```

------

## 11.6 带通滤波，可选

论文主要提到 SG filter 和 Hampel filter，但工程复现时可以加入呼吸频带带通滤波。

```python
def bandpass_filter(X, fs, band=(0.1, 0.7), order=4):
    """
    Apply Butterworth bandpass filter.

    Parameters
    ----------
    X : np.ndarray
        Signal matrix, shape [T, D] or [T].
    fs : float
        Sampling frequency.
    band : tuple
        Frequency band in Hz.
    order : int
        Filter order.

    Returns
    -------
    Y : np.ndarray
        Filtered signal.
    """
    nyq = fs / 2
    low = band[0] / nyq
    high = band[1] / nyq

    b, a = butter(order, [low, high], btype="bandpass")
    return filtfilt(b, a, X, axis=0)
```

------

## 11.7 波形方向调整

使用与参考信号相关系数的方法。

```python
def align_waveform_directions(X, reference_index=None):
    """
    Align waveform directions to avoid cancellation in fusion.

    Parameters
    ----------
    X : np.ndarray
        Signal matrix, shape [T, D].
    reference_index : int or None
        Reference stream index. If None, use the stream with maximum variance.

    Returns
    -------
    X_aligned : np.ndarray
        Direction-aligned signals.
    reference_index : int
        Used reference index.
    """
    X = np.asarray(X)
    T, D = X.shape

    X_centered = X - np.mean(X, axis=0, keepdims=True)

    if reference_index is None:
        reference_index = int(np.argmax(np.var(X_centered, axis=0)))

    ref = X_centered[:, reference_index]

    X_aligned = X_centered.copy()

    for d in range(D):
        corr = np.corrcoef(ref, X_centered[:, d])[0, 1]
        if np.isnan(corr):
            corr = 0.0
        if corr < 0:
            X_aligned[:, d] *= -1

    return X_aligned, reference_index
```

------

## 11.8 Hampel filter

```python
def hampel_filter_1d(x, window_size=101, n_sigmas=3.0):
    """
    Hampel filter for 1D signal.

    Parameters
    ----------
    x : np.ndarray
        Input signal.
    window_size : int
        Sliding window size. Should be odd.
    n_sigmas : float
        Threshold scale.

    Returns
    -------
    y : np.ndarray
        Filtered signal.
    """
    x = np.asarray(x).copy()
    y = x.copy()

    if window_size % 2 == 0:
        window_size += 1

    k = window_size // 2
    n = len(x)

    for i in range(k, n - k):
        window = x[i - k:i + k + 1]
        med = np.median(window)
        mad = np.median(np.abs(window - med)) + 1e-12
        threshold = n_sigmas * 1.4826 * mad

        if np.abs(x[i] - med) > threshold:
            y[i] = med

    return y


def hampel_filter_matrix(X, window_size=101, n_sigmas=3.0):
    """
    Apply Hampel filter to each column.
    """
    X = np.asarray(X)
    Y = np.zeros_like(X)

    for d in range(X.shape[1]):
        Y[:, d] = hampel_filter_1d(X[:, d], window_size, n_sigmas)

    return Y
```

------

## 11.9 PCA 融合

```python
def pca_fusion(X):
    """
    Fuse multi-stream respiratory signals using first principal component.

    Parameters
    ----------
    X : np.ndarray
        Signal matrix, shape [T, D].

    Returns
    -------
    y_pca : np.ndarray
        Fused PCA signal, shape [T].
    pca_model : PCA
        Fitted PCA model.
    """
    X = np.asarray(X)
    X_centered = X - np.mean(X, axis=0, keepdims=True)

    pca = PCA(n_components=1)
    y_pca = pca.fit_transform(X_centered).ravel()

    return y_pca, pca
```

------

## 11.10 VMD 分解

使用 `vmdpy`：

```python
def vmd_decompose_and_select(
    y,
    K=3,
    alpha=2000,
    tau=0.0,
    DC=0,
    init=1,
    tol=1e-7
):
    """
    Apply VMD and select the mode with the largest variance.

    Parameters
    ----------
    y : np.ndarray
        Input PCA signal.
    K : int
        Number of VMD modes. The paper uses K=3.
    alpha : float
        Bandwidth constraint. Common default is 2000.
    tau : float
        Noise-tolerance parameter. 0 for strict fidelity.
    DC : int
        Whether to force first mode to be DC.
    init : int
        Initialization method. 1 means uniformly distributed omega.
    tol : float
        Convergence tolerance.

    Returns
    -------
    y_final : np.ndarray
        Selected VMD mode.
    modes : np.ndarray
        VMD modes, shape [K, T].
    selected_idx : int
        Selected mode index.
    """
    from vmdpy import VMD

    y = np.asarray(y)
    y = y - np.mean(y)

    modes, modes_hat, omega = VMD(y, alpha, tau, K, DC, init, tol)

    variances = np.var(modes, axis=1)
    selected_idx = int(np.argmax(variances))

    y_final = modes[selected_idx, :]

    return y_final, modes, selected_idx
```

说明：

- 论文明确给出 $K=3$；
- 但没有详细给出 VMD 的 $\alpha,\tau,DC,init,tol$；
- 上述参数是 vmdpy 常用设置；
- 实际复现时需要针对采样率、呼吸频带、噪声水平调参。

------

## 11.11 峰值检测和呼吸率估计

```python
def estimate_breath_rate_from_peaks(
    y,
    fs,
    min_breath_interval=1.2,
    max_breath_interval=10.0,
    prominence=None
):
    """
    Estimate breath rate from peak intervals.

    Parameters
    ----------
    y : np.ndarray
        Final respiratory signal.
    fs : float
        Sampling frequency.
    min_breath_interval : float
        Minimum allowed interval between breaths, in seconds.
    max_breath_interval : float
        Maximum allowed interval between breaths, in seconds.
    prominence : float or None
        Peak prominence threshold.

    Returns
    -------
    br_bpm : float
        Estimated breath rate in breaths per minute.
    peaks : np.ndarray
        Peak indices after basic detection.
    valid_intervals : np.ndarray
        Valid peak intervals in seconds.
    """
    y = np.asarray(y)
    y = y - np.mean(y)

    min_distance = int(min_breath_interval * fs)

    peaks, properties = find_peaks(
        y,
        distance=min_distance,
        prominence=prominence
    )

    if len(peaks) < 2:
        return np.nan, peaks, np.array([])

    intervals = np.diff(peaks) / fs

    valid_mask = (intervals >= min_breath_interval) & (intervals <= max_breath_interval)
    valid_intervals = intervals[valid_mask]

    if len(valid_intervals) == 0:
        return np.nan, peaks, valid_intervals

    mean_period = np.mean(valid_intervals)
    br_bpm = 60.0 / mean_period

    return br_bpm, peaks, valid_intervals
```

------

## 11.12 整体 Pipeline 示例

```python
def wifi_breath_detection_pipeline(
    H,
    fs,
    sg_window=51,
    sg_polyorder=3,
    select_duration=12.0,
    num_angles=100,
    n_fft=8192,
    breath_band=(0.1, 0.7),
    w_bnr=0.5,
    w_var=0.5,
    use_bandpass=True,
    use_hampel=True,
    hampel_window=101,
    vmd_K=3
):
    """
    Full pipeline for WiFi CSI-based breath detection.

    Parameters
    ----------
    H : np.ndarray
        Raw CSI, shape [T, 2, 2, 30], complex.
    fs : float
        Sampling frequency.

    Returns
    -------
    result : dict
        Dictionary containing intermediate and final results.
    """

    # 1. CSI ratio
    R = extract_csi_ratio(H)

    # 2. Smooth complex ratio
    R_smooth = smooth_complex_ratio(
        R,
        window_length=sg_window,
        polyorder=sg_polyorder
    )

    # 3. Projection and respiratory pattern selection
    X, theta_list, infos = select_best_projections(
        R_smooth,
        fs=fs,
        select_duration=select_duration,
        num_angles=num_angles,
        n_fft=n_fft,
        band=breath_band,
        w_bnr=w_bnr,
        w_var=w_var
    )

    # 4. Smooth selected signals
    X_smooth = np.zeros_like(X)
    for d in range(X.shape[1]):
        X_smooth[:, d] = savgol_filter(X[:, d], sg_window, sg_polyorder)

    # 5. Optional bandpass
    if use_bandpass:
        X_proc = bandpass_filter(X_smooth, fs=fs, band=breath_band, order=4)
    else:
        X_proc = X_smooth

    # 6. Optional Hampel filter
    if use_hampel:
        X_proc = hampel_filter_matrix(
            X_proc,
            window_size=hampel_window,
            n_sigmas=3.0
        )

    # 7. Direction alignment
    X_aligned, ref_idx = align_waveform_directions(X_proc)

    # 8. PCA fusion
    y_pca, pca_model = pca_fusion(X_aligned)

    # 9. VMD decomposition and mode selection
    y_final, modes, selected_mode_idx = vmd_decompose_and_select(
        y_pca,
        K=vmd_K
    )

    # 10. Breath rate estimation
    br_bpm, peaks, valid_intervals = estimate_breath_rate_from_peaks(
        y_final,
        fs=fs,
        min_breath_interval=1.2,
        max_breath_interval=10.0,
        prominence=None
    )

    result = {
        "R": R,
        "R_smooth": R_smooth,
        "X_projected": X,
        "X_processed": X_proc,
        "X_aligned": X_aligned,
        "theta_list": theta_list,
        "projection_infos": infos,
        "reference_index": ref_idx,
        "y_pca": y_pca,
        "vmd_modes": modes,
        "selected_mode_idx": selected_mode_idx,
        "y_final": y_final,
        "peaks": peaks,
        "valid_intervals": valid_intervals,
        "breath_rate_bpm": br_bpm,
        "pca_model": pca_model
    }

    return result
```

------

# 12. 实验设计总结

## 12.1 志愿者与场景

论文实验包括：

| 项目         | 内容               |
| ------------ | ------------------ |
| 志愿者数量   | 11                 |
| 女性数量     | 2                  |
| 实验周期     | 两周               |
| 实验地点     | 会议室             |
| 每次实验时长 | 3 min              |
| Ground truth | 手机节拍器同步呼吸 |

------

## 12.2 睡姿

论文测试六种常见睡姿：

1. fetus；
2. log；
3. yearner；
4. soldier；
5. freefaller；
6. starfish。

这些睡姿覆盖了大部分常见睡眠姿态。

------

## 12.3 呼吸频率

志愿者按照节拍器进行三种频率的自然呼吸：

| 频率    | breaths/min |
| ------- | ----------- |
| 0.2 Hz  | 12 bpm      |
| 0.25 Hz | 15 bpm      |
| 0.3 Hz  | 18 bpm      |

补充实验还包括：

- 10 breaths/min；
- 37 breaths/min；
- 呼吸频率突然变化；
- 深浅呼吸交替；
- 睡姿切换。

------

# 13. 评价指标

## 13.1 Mean Estimation Accuracy, MEA

$\text{MEA}= \frac{1}{n} \sum_{i=1}^{n} \left( 1-\left| \frac{r_i-r'_i}{r'_i} \right| \right) \times 100\%$

其中：

- $r_i$：估计呼吸率；
- $r'_i$：真实呼吸率。

------

## 13.2 Mean Absolute Error, MAE

$\text{MAE}= \frac{1}{n} \sum_{i=1}^{n}|r_i-r'_i|$

单位通常为 breaths/min。

------

# 14. 实验结果与结论

## 14.1 不同睡姿下性能

在单天线对检测中，所有睡姿下的 median accuracy 不低于 96%。

在双天线对融合后，所有睡姿下 median accuracy 超过 99%。

这证明：

> 多天线对具有互补感知能力，可以提升未知睡姿下的呼吸检测鲁棒性。

------

## 14.2 与已有方法比较

论文比较了：

1. PhaseBeat；
2. FullBreathe；
3. WiFi-Sleep；
4. 本文方法。

结果显示本文方法在不同天线对配置下 MEA 均更高。

这证明：

> CSI ratio 投影 + 周期性/变化性联合选择能更好缓解 blind spot。

------

## 14.3 与融合方法比较

论文比较了：

1. Breath Rate Combining；
2. MRC；
3. PCA；
4. PCA-VMD。

结果显示 PCA-VMD 的 MAE 最低。

这证明：

> PCA-VMD 能比传统加权融合和单纯 PCA 更有效地提取呼吸成分。

------

## 14.4 特殊场景验证

论文还验证了：

- 慢呼吸；
- 快呼吸；
- 呼吸频率突变；
- 深浅呼吸交替；
- 睡姿切换。

其中睡姿切换时，大动作会影响呼吸估计。论文的处理策略是：

1. 检测大动作；
2. 暂停呼吸检测；
3. 动作结束后重新选择投影轴；
4. 恢复检测。

因此，本文的 position-free 更准确地说是：

> 对不同静态睡姿和未知睡姿鲁棒，而不是在大幅运动过程中连续无误估计。

------

# 15. 需要注意的复现细节

## 15.1 论文没有给出全部滤波参数

例如：

- Savitzky-Golay window length；
- Savitzky-Golay polyorder；
- Hampel filter window；
- VMD 的 alpha；
- peak detection prominence。

这些需要复现实验时根据采样率和数据质量调参。

------

## 15.2 Ground truth 不是临床级设备

论文使用手机节拍器让志愿者同步呼吸作为 ground truth。

这意味着结果适合证明算法有效性，但不能完全等同于临床睡眠监测精度。

------

## 15.3 多人场景不是本文重点

本文主要针对单人睡眠呼吸检测，不讨论多人呼吸分离。

------

## 15.4 翻身时不是连续估计

大幅运动期间呼吸检测会暂停，动作结束后重新初始化投影轴。

------

## 15.5 VMD 模态选择准则较简单

论文选择方差最大的模态作为呼吸模态。

在实际复现中，如果噪声模态方差很大，可能会误选。可以增强为：

$k^\*=\arg\max_k \left[ \text{Var}(u_k)\cdot \text{BNR}(u_k) \right]$

或者选择中心频率落在呼吸频带内且 BNR 最大的模态。

------

# 16. 可改进的复现建议

如果你后续要做代码复现或改进，可以考虑以下增强。

## 16.1 VMD 模态选择使用 BNR + variance

论文只用最大方差选 VMD 模态，但可以改成：

$S_k=\alpha \cdot \widehat{\text{BNR}}(u_k)+ (1-\alpha)\cdot \widehat{\text{Var}}(u_k)$

然后选择：

$k^\*=\arg\max_k S_k$

这和前面的投影选择逻辑更一致。

------

## 16.2 PCA 前加入子载波质量筛选

可以去除低质量子载波：

- BNR 太低；
- variance 太低；
- 与参考信号相关性太低；
- 异常值比例过高。

例如只保留评分前 30 个子载波再 PCA。

------

## 16.3 峰值检测可结合频谱估计

最终呼吸率可以融合两种估计：

1. peak interval；
2. FFT dominant frequency。

如果二者差异过大，则说明该片段质量可能较差。

------

## 16.4 睡姿切换可做运动检测

可以使用短时能量或频谱扩展检测大动作：

$E(t)=\sum_{i=1}^{D}x_i^2(t)$

若短时间能量突增，则判定为 motion period。

------

# 17. 最终总结

本文的核心不是单纯提高 SNR，也不是简单 MRC+VMD，而是一个完整的 WiFi CSI 呼吸检测 pipeline：

1. 用 CSI ratio 抵消商用 WiFi 随机相位偏移；
2. 在复平面投影中生成多个幅度/相位组合候选；
3. 用 BNR 和 variance 联合选择呼吸模式；
4. 用线性插值和 Savitzky-Golay 滤波处理采样抖动和高频噪声；
5. 做波形方向调整，避免多子载波融合时正负抵消；
6. 使用 PCA 融合多天线、多子载波的互补信息；
7. 使用 VMD 分解 PCA 信号，并选择方差最大的模态作为最终呼吸信号；
8. 通过峰值检测和伪峰剔除估计呼吸率。

最终系统在未知睡姿下实现了非常低的呼吸率估计误差，论文报告的 MAE 小于 0.05 breaths/min。

从复现角度看，最关键的模块是：

- CSI ratio 构造；
- 投影角选择；
- BNR + variance 评分；
- 波形方向调整；
- PCA-VMD 融合；
- 可靠峰值检测。

只要这几个模块实现稳定，基本就能复现本文方法的主要思想。

```

```