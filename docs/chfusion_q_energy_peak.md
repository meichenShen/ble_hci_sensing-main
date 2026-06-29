# q_energy + q_peak 融合方法

> 实现：`src/ble_analysis/chfusion.py`  
> 实验脚本：`notebooks/scripts/chFusion_fft-q.py`

---

## 1. Benchmark 对比的五种方法

| 方法 | 权重 / 策略 | 方法键 |
|------|------------|--------|
| **Single** | 最大 η 单信道 FFT 峰 | `fft_single_max_energy` |
| **Uniform** | 各信道谱等权平均 | `fft_uniform_fusion` |
| **FFT+q_energy** | `q_energy` | `fft_q_energy_fusion` |
| **FFT+q_peak** | `q_peak` | `fft_q_peak_fusion` |
| **FFT+q_energy_peak** | `√(q_energy · q_peak)` | `fft_q_energy_peak_fusion` |

四种 CS 变量（amp / remote / local / phase）各跑一遍 → **4×5 = 20** 组合排行榜。

---

## 2. 子分数（均为对数域映射）

### q_energy

- **信号**：高通 `highpass_filtered`
- **原始量**：η = E_breath / E_total（呼吸带 / 总带 FFT 能量比）
- **映射**（与 q_peak 相同 log-linear 公式）：

  $$q_{\text{energy}} = \operatorname{clip}\left( \frac{\log \eta - \log \eta_{\min}} {\log \eta_{\mathrm{good}} - \log \eta_{\min}},\, 0,\, 1 \right)$$

  默认 η_min=0.02，η_good=0.20。

### q_peak

- **信号**：带通 `bandpass_filtered`
- **原始量**：ρ = max(P)/median(P)（呼吸带内）
- **映射**：同上 log-linear（默认 ρ ∈ [1.5, 6.0]）

---

## 3. 多信道融合

每滑窗、每信道：

1. 带通 FFT → 归一化谱 P̄_c(f)
2. 计算 q_energy、q_peak（及组合的 q_energy_peak）
3. Softmax 权重 → 加权融合谱 S(f) → argmax → BPM

---

## 4. 配置

| 参数 | 默认 |
|------|------|
| `energy_ratio_min` / `energy_ratio_good` | 0.02 / 0.20 |
| `peak_snr_min` / `peak_snr_good` | 1.5 / 6.0 |

---

## 5. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-06-01 | 初版 energy+peak；Top-K 实验（已归档，不再纳入 benchmark） |
| 2026-06-01 | **精简为 3 方法**：FFT+q_energy / q_peak / q_energy_peak；q_energy 统一 log 映射 |
| 2026-06-01 | **恢复 Single / Uniform 基线**，benchmark 共 5 方法（基线在前） |

*后续改动请在本表追加并更新上文章节。*
