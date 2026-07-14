# 多变量融合研究计划报告

## 研究定位

本阶段我把项目主线从“比较 local amplitude / remote amplitude / phase 谁更好”推进到“研究 BLE CS 多观测变量如何融合”。单变量结果在这里主要作为信息能力分析：用来观察不同变量的稳定性、失效模式与互补性，为后续融合方法设计提供依据。

新的融合研究统一命名为 `multivariable_fusion`。严格 Liu 2016 原文复现仍保留在 `liu_2016_paper`，不混入 BLE 多变量融合。

更具体地说，本阶段希望回答的问题从单一变量选择，扩展为：

> local、remote、phase 各自提供什么信息？它们在什么情况下互补？如何在 tone 层和变量层把这些信息融合起来？

因此，当前实验重点放在：

> 在 BLE CS 中，local amplitude、remote amplitude 和 phase 各自什么时候可靠？多个 tone 如何融合？多个变量如何在窗口级互补？哪一类融合策略能降低平均误差、提高有效窗口覆盖率，并压低尾部误差？

本报告把研究拆成两个层级：第一层是同一变量内部的 channel/tone fusion，第二层是 local/remote/phase 之间的 variable fusion。这样每个实验方法都有清楚的层级、来源和对照关系，也便于后续和师兄讨论哪些方法值得继续深入。

## 文献对比表

| 文献 | 输入数据 | Channel / subcarrier fusion | Variable fusion | 权重或选择策略 | 对 BLE CS 的启发 |
|---|---|---|---|---|---|
| Liu et al. 2016 | WiFi CFR/CSI amplitude subcarriers | 多 subcarrier 频率候选融合 | 无 amplitude/phase 多变量融合 | `pr=A/RMSE` 后 weighted median | 可作为 tone-level weighted median 基线 |
| 西电博士论文 MRC | 校准后 WiFi CSI，不同天线与子载波 | 将天线/子载波看作多个 branch 做 MRC | 主要是 channel/subcarrier 层 | 最大比合并，目标是最大 SNR | 可迁移为 BLE tone-level SNR-MRC 和 quality-MRC |
| FullBreathe | WiFi CSI amplitude + phase | 有子载波/链路处理，但重点在 amplitude/phase 互补 | 利用 amplitude 与 phase 的互补性 | 根据两者互补关系进行感知设计 | 支持 BLE local/remote/phase 作为互补观测变量来研究 |
| ResBeat | WiFi bimodal CSI：amplitude + phase difference | 预处理后从 bimodal CSI 中提取呼吸信号 | bimodal adaptive signal selection | 基于信号能量和运动检测做 adaptive selection | 可迁移为窗口级变量选择或质量驱动选择 |
| Wi-Breath | WiFi CSI amplitude + phase difference | 选择合适 channel / signal | amplitude 与 phase difference 中选择信号 | SVM-based signal selection，另有 SNR/channel selection 思路 | 第一版先做无监督 adaptive selection，SVM 留作后续监督版本 |

文献给出的共同线索是：传统 WiFi 呼吸估计通常不会只依赖单个子载波或单个变量，而是通过子载波融合、branch combining、信号选择或 amplitude/phase 互补来提升稳定性。BLE CS 的变量结构不同于 WiFi CSI，但 local amplitude、remote amplitude 和 phase 同样可以被看作不同观测分支，因此适合转化为一个层级化融合问题。

这里保留一个方法边界：`liu_2016_paper` 继续对应 strict Liu reproduction；Liu-style weighted median 在新研究中作为 tone-level robust fusion baseline 使用，用来和 MRC、quality fusion 等方法做对照。

## 总体框架

### Stage 1：单变量信息能力分析

Stage 1 的目标是先把三个变量的信息形态摸清楚，重点观察：

- `local_amplitudes` 在哪些场景/片段中稳定；
- `remote_amplitudes` 是否提供与 local 不同的信息；
- `phases` 是否在部分窗口补充 amplitude 的失效；
- 三者是否存在后续融合的必要性。

统一 pipeline：

```text
BLE CS variable
→ existing filtered cache
→ same window-level BPM estimator
→ same tone/channel fusion baseline
→ quality diagnostics
```

输出文件：

- `outputs/reports/multivariable_fusion/stage1_variable_information_summary.csv`
- `outputs/reports/multivariable_fusion/stage1_variable_window_diagnostics.csv`
- `outputs/figures/multivariable_fusion/stage1_variable_quality_heatmap.png`
- `outputs/figures/multivariable_fusion/stage1_variable_validity_coverage.png`
- `outputs/figures/multivariable_fusion/stage1_variable_failure_modes.png`

Stage 1 的核心图用于回答三个问题：

![Stage 1 variable quality heatmap](../../outputs/figures/multivariable_fusion/stage1_variable_quality_heatmap.png)

图 1 展示每个场景/片段下不同变量的 periodicity quality。它用于观察某个变量是否在所有片段都稳定，或只在部分片段中质量较高。

![Stage 1 variable coverage](../../outputs/figures/multivariable_fusion/stage1_variable_validity_coverage.png)

图 2 展示有效窗口覆盖率。它用于判断变量是否经常无法产生有效呼吸估计。

![Stage 1 failure modes](../../outputs/figures/multivariable_fusion/stage1_variable_failure_modes.png)

图 3 汇总失效模式。它用于检查问题主要来自窗口过短、tone 无效，还是估计结果本身不可靠。

### Stage 2A：Channel / tone-level fusion

目标是在同一种变量内部研究多个 tone 如何融合。

| 方法 key | 来源 | 行为 |
|---|---|---|
| `best_tone` | baseline | 选择质量最高 tone |
| `equal_average` | baseline | tone waveform 等权平均 |
| `liu_weighted_median` | Liu 2016 | 每个 tone 估 BPM + `pr=A/RMSE`，再 weighted median |
| `snr_mrc` | 西电 MRC | breath-band SNR 作为 MRC 权重 |
| `quality_mrc` | BLE adaptation | 用 `snr/pr/stability` 组合质量做 MRC |

Stage 2A 重点比较“选择一个 tone”和“融合多个 tone”的差异：

![Stage 2A channel method comparison](../../outputs/figures/multivariable_fusion/stage2a_channel_method_comparison.png)

图 4 比较五种 tone-level 方法的整体误差。它用于判断简单平均、best tone、Liu-style weighted median、SNR-MRC 和 quality-MRC 哪类更适合 BLE tone 多样性。

![Stage 2A MRC quality distribution](../../outputs/figures/multivariable_fusion/stage2a_mrc_weight_distribution.png)

图 5 展示 MRC 类方法的质量分数分布。它用于检查 SNR-only 权重和综合质量权重是否在当前数据上形成了有效区分。

### Stage 2B：Variable-level fusion

目标是在 local amplitude、remote amplitude、phase 三个观测变量之间做融合。

| 方法 key | 来源 | 行为 |
|---|---|---|
| `variable_equal_average` | baseline | 三变量 BPM / waveform 等权融合 |
| `variable_quality_weighted` | FullBreathe / MRC 思想扩展 | 根据变量质量归一化加权 |
| `variable_weighted_median` | Liu-style extension | 三变量 BPM + quality 做 weighted median |
| `variable_mrc` | MRC 思想扩展 | 三变量作为 sensing branches 做 waveform MRC |
| `adaptive_selection` | ResBeat / Wi-Breath | 每窗口选择当前质量最高变量 |

Stage 2B 重点回答变量融合是否比单变量 reference 更稳：

![Stage 2B variable method comparison](../../outputs/figures/multivariable_fusion/stage2b_variable_method_comparison.png)

图 6 比较变量级融合和层级融合方法。它直接对应最终方法选择：equal average、quality weighted、weighted median、MRC、adaptive selection 以及 hierarchical fusion。

![Stage 2B adaptive selection distribution](../../outputs/figures/multivariable_fusion/stage2b_adaptive_selection_distribution.png)

图 7 展示 adaptive selection 在窗口级选择了哪些变量。它用于判断选择策略是否高度依赖单一变量，还是确实在不同窗口之间切换。

### Proposed hierarchical fusion

主方法命名为：

```text
hierarchical_quality_fusion
```

默认流程：

```text
per variable:
    quality_mrc tone fusion
        ↓
    variable-level quality estimate

across variables:
    variable_quality_weighted fusion
        ↓
    final BPM
```

同时保留以下对照：

- `best_tone__adaptive_selection`
- `liu_weighted_median__variable_weighted_median`
- `snr_mrc__variable_mrc`

## 命名边界

- `liu_2016_paper`：严格原文算法复现；
- `liu_eta_rho_adapted`：历史 BLE adapted baseline；
- `multivariable_fusion`：新的 BLE 多变量融合研究；
- `local_amplitudes / remote_amplitudes / phases`：融合研究中的观测变量，重点分析互补性和窗口级可靠性；
- `combined`：历史 exploratory ablation 的输出，不作为新主线方法名。

## 当前实现状态

已经新增：

- `src/ble_analysis/multivariable_fusion.py`
- `notebooks/scripts/chFusion_stage1_variable_information.py`
- `notebooks/scripts/chFusion_stage2_multivariable_fusion.py`
- `tests/test_multivariable_fusion.py`

已经生成：

- Stage 1 CSV 与三张图；
- Stage 2A / Stage 2B CSV 与四张图；
- 三份中文报告：本计划报告、Stage 1 报告、Stage 2 报告。

## 下一步实验优先级

下一步我计划优先验证 `snr_mrc__variable_mrc` 在更多采集条件下是否仍然稳定。随后会继续标定 `quality_mrc` 中 `snr/pr/stability` 的归一化方式，尤其关注 phase 的质量指标是否需要单独定义。再往后，可以参考 ResBeat / Wi-Breath，把 adaptive selection 从当前的无监督质量选择扩展到带运动检测或监督选择的版本。
