# chFusion 模态与信道融合探索 — 工作汇报

> 对应脚本：`chFusion_fft-q.py` → `chFusion_plan2.py` → `chFusion_plan2_diff_domain_verify.py`  
> 场景配置：`config/scenarios/cs_091339.json`、`cs_095806.json`、`cs_102621.json`  
> 详细实验笔记见：[CS呼吸算法验证整体进度.md](./CS呼吸算法验证整体进度.md)

---

## 1. 背景与目标

BLE CS 一次测量提供 **72 信道 × 4 类观测量**：

| 变量 | 含义 |
|------|------|
| `remote_amplitudes` | 远端 PCT 幅值 |
| `local_amplitudes` | 本地 PCT 幅值 |
| `amplitudes` | 总幅值（远端×本地向量合成） |
| `phases` | 总相位（unwrap 后） |

核心问题分两路：

1. **模态融合**：呼吸 BPM 应主要信幅值、相位，还是二者联合？
2. **信道融合**：多信道加权平均是否优于「每窗只留能量最大的一路」？

本阶段在 **金属板脚本**（三场次录制、分段 GT 相同、帧 index 不同）上，用统一滑窗 FFT + 脚本分段 GT 做相对 BPM 误差评估。

---

## 2. 探索路线（按脚本与 Git 脉络）

### 阶段 A — `chFusion_fft-q.py`（信道融合 × 四变量）

**Commits 脉络：** `b56c8fa` 初版 pipeline → `a2bca38` 四变量 benchmark + 小提琴图 → `49df326`/`5a86700` q_energy_peak → `e6a1d7b` 精简为三种 log-q 融合 → `16c6c05` 恢复 Single/Uniform 基线。

**方法（5 种）：**

- **Single**：每窗选呼吸频段能量比 η 最大的单信道，再 FFT 寻峰
- **Uniform**：各信道**归一化呼吸频谱**等权平均后寻峰（不是 BPM 平均）
- **FFT+q_energy / q_peak / q_energy_peak**：全信道按 q 分数加权融合频谱

**主要发现（091339，见进度文档）：**

- 四变量上 **Single max-η 信道** 整体优于各类多信道加权；Uniform / q 融合常把 BPM 拉向错误方向（方差变小但偏差变大）。
- **Remote 幅值** 在 091339 上通常最好；**相位** 稳定性好于预期，介于「较好单侧幅值」与「较差单侧幅值 / 总幅值」之间。
- **Remote vs local 谁更好因场景而异**，不能写死部署策略。
- 波形上可见 **幅值–相位互补**：某一变量准的窗口，另一变量往往偏差更大。

**结论导向：** 信道侧应谨慎做「全信道平均」；变量侧需要 **模态级** 而非仅信道级的下一步实验 → 引出 Plan 2。

---

### 阶段 B — `chFusion_plan2.py`（改进方案 2：互补性 + 模态融合）

**Commits 脉络：** `cb20932` Plan2 API + 脚本 → `b2fe847` η/ρ 选路切换 + top-2 模态 → `af82abb` 互补性 9 图、对比图、η 优于 ρ 结论。

**Part A — 幅值相位互补性（波形）**

- 对 **phase / remote / local** 三种参考变量，各取 Single best/worst/median BPM 窗口；
- 在该窗、该参考变量 max-η 信道上，画四变量 **带通归一化波形** + η + 各变量 BPM。
- 目的：在原始波形上验证「对谁互补、何时互补」，而非只看标量误差。

**Part B — 模态融合（每变量各自 max-η 信道，再融频谱）**

不参与融合：总幅值（已是 remote/local 合成）。参与融合：phase + remote + local。

| 策略 | 说明 |
|------|------|
| Modal equal | 三变量等权 1/3 |
| Modal η-weight | 按各变量 max-η 归一化加权 |
| Modal 0.5/0.25/0.25 | 固定 phase 0.5，remote/local 各 0.25 |
| Modal top2 equal | 每窗按 η 排序取 **前二变量**，等权 0.5 |
| Modal top2 ρ-weight | top-2 按 ρ 加权 |

**091339 关键数字（η 选路）：**

| 方法 | mean err% |
|------|-----------|
| Single remote | **10.91** |
| Modal top2 equal | 13.04 |
| Modal η-weight | 13.25 |
| Single phase | 15.13 |
| Single local | 30.49 |

**091339 小结：**

- 信道选择：**η 优于 ρ**（ρ 下 Single remote ~20%，易选「峰尖但频率错」的信道）。
- 模态融合落在 Single remote 与 Single phase **之间**，符合「折中较好幅值与相位」；
- **top-2** 略优于三变量 equal，且多数窗剔除 η 最低的 local；
- 部署时无法 oracle 选 remote → 模态融合 (~13%) 是 safer 默认。

---

### 阶段 C — `chFusion_plan2_diff_domain_verify.py`（跨场景重复性）

**Commits 脉络：** `00268d6` 095806 验证 → `920969d` 场景 JSON 化 → 本阶段扩展三场景 + 跨域聚合图。

**动机：** 091339 上「Single remote 最优」是否可推广？换录制日 / 帧段后是否仍成立？

**三场景：** 同金属板协议，GT 相同，index 不同（`cs_091339` / `cs_095806` / `cs_102621`）。

**单场景最优（η 选路，各域不同）：**

| 场景 | 单场景最优（约） | 备注 |
|------|------------------|------|
| 091339 | Single remote **10.91%** | 与 fft-q 一致 |
| 095806 | Uniform phase **6.75%** | Single remote 12.16%，Uniform 全面逆袭 |
| 102621 | Modal η-weight **4.60%** | Single remote 8.29%，模态全面领先 |

**三场景并排（核心方法 mean err%）：**

| 方法 | 091339 | 095806 | 102621 |
|------|--------|--------|--------|
| Single Remote | 10.91 | 12.16 | 8.29 |
| Single Local | 30.49 | 13.17 | 7.32 |
| Single Phase | 15.13 | 11.12 | 12.55 |
| Uniform Remote | 17.09 | 9.15 | 6.82 |
| Modal top2 equal | 13.04 | 10.61 | 4.69 |
| Modal η-weight | 13.25 | 10.50 | **4.60** |
| Modal equal | 13.61 | 10.50 | 4.64 |

**跨场景聚合（各域 overall mean 再对三域求 mean ± std）：**

| 方法 | mean | ±std |
|------|------|------|
| **Modal top2 equal** | **9.45** | 4.29 |
| **Modal η-weight** | **9.45** | 4.42 |
| Modal equal | 9.58 | 4.56 |
| Single Remote | 10.45 | **1.97** |
| Uniform Remote | 11.02 | 5.39 |
| Single Local | 16.99 | 12.05 |

图：`outputs/figures/plan2_cross_domain_aggregate_bars.png`

---

### 阶段 D — `chFusion_pca_svd.py`（PCA/SVD 共同模式提取）

**动机：** 利用 72 信道相关性，用 PC1 / 第一奇异向量提取呼吸共同模式，与 Plan2「每窗选最优信道」对照。

**单场景 102621（v1 + v2，7 breath 段）：**

| 方法 | mean err% |
|------|-----------|
| **PCA-Cmplx Total ch-η**（v2） | **3.81** |
| Modal η-weight（Plan2） | 4.60 |
| PCA-Modal3 η/ch-η（v2） | 5.72 |
| PCA Total Amp（v1 带通） | 6.62 |
| SVD Complex \|u₁\|（v1） | 52+（失效） |

**跨场景三域 aggregate：**

| 方法 | mean |
|------|------|
| **Modal top2 / η-weight** | **9.45%** |
| PCA-Modal3 η/ch-η | 10.92% |
| **PCA-Cmplx-Modal rem+loc η**（不 oracle 选端） | **11.95%** |
| Single Remote | 10.45% |
| PCA-Cmplx η-blend / Dual-Amp ch-η | ~14.2–14.7% |
| PCA-Cmplx Total ch-η | 14.66%（102621 优、091339 差） |

**双幅值整合（2026-06）：** 在不预先知道 remote/local 哪端更好时，**方案4（两端各自复 PCA → 模态谱融合）** 跨域最优；方案3 η-blend 单场景 102621 可达 4.71% 但 091339 不稳。脚本 §9 对 091339 统计窗级倍频/半频占比，解释 η-blend / Dual-Amp 失败。

**要点：**

- **方法流程详解**见 `docs/chFusion_pca_svd_plan.md` **§9**（滤波级、信道/模态加权、BPM 路径逐项对照）；整合结果见 **§8.8**。
- **PCA + 模态谱融合**（高通 + ch-η）优于带通单变量 PCA；**复 PCA Re(PC1)** 单场景最优但跨域不稳。
- **已停测：** SVD Complex \|u₁\|、Remote·e^jφ、144 列 Dual-Amp 作部署路线。
- **§8 重跑（2026-06）：** Modal 仍跨域 **9.45%**；PCA-Modal3 **top16** 为 PCA 系列最优 **10.85%**；top2 模态 PCA **未超越** Plan2 Modal。
- **091339 诊断：** 段 2b 窗级 **100% 半频**（η-blend/Dual-Amp）；谱图见 `pca_svd_091339_worst_seg_pc1_spectrum.png`。
- **快捷脚本：** `chFusion_pca_svd_cross_domain.py`（§8）、`chFusion_pca_svd_p1_diag.py`（P1）。

图：`pca_svd_102621_leaderboard_bars.png`、`pca_svd_cross_domain_aggregate_bars.png`。

---

## 3. 综合结论（从探索过程到部署启示）

### 3.1 单场景下「谁最好」不稳定

| 层次 | 观察 |
|------|------|
| **变量** | remote / local / phase 的优劣随场景翻转；091339 remote≫local，102621 local 甚至略优于 remote。 |
| **信道策略** | 091339 Single≫Uniform；095806 Uniform phase/remote 优于 Single。fft-q 与 Plan2 一致：**不能假设多信道平均总是更好或更差**。 |
| **091339 叙事** | 在首场景上 Single remote 像 oracle 上界，但 **不能外推为全局最优**。 |

### 3.2 跨场景聚合后，模态融合优势最清晰

- **Modal top2 / Modal η-weight** 跨三域平均 **~9.45%**，优于 Single remote（10.45%）及所有 Uniform/Single local 组合。
- Single remote **均值略差于模态**，但 **std 最小（1.97%）**——在「已知 remote 总是最好」的理想世界里更稳；真实部署无此先验。
- Modal 的 **std ~4.3%** 反映域间仍有波动，但 **mean 最低**，且在三域均未出现 local 误用级灾难（091339 的 30% local）。

**一句话：** 单场景争「冠军」无统一答案；**对多场景鲁棒性而言，每窗 phase+remote+local 按 η 选信道再模态融合（尤其 top-2）是当前最稳的折中。**

### 3.3 与 fft-q 阶段结论的衔接

| fft-q（信道融合） | Plan2（模态融合） |
|-------------------|-------------------|
| 全信道 q 加权常不如 Single max-η | 每**变量**各自 max-η，再在**变量维**融合 |
| 问题在「盲目多信道平均」 | 问题在「盲目单变量 / 单侧面幅值」 |
| 启示：信息可综合，BPM 应用**精选** | 启示：变量也应 **精选 + 融合**，top-2 动态去掉较差侧面 |

### 3.4 建议的默认策略（金属板脚本类场景）

1. **信道选择：** η（energy ratio），不用 ρ 作默认。
2. **模态：** phase + remote + local 参与；总幅值不参与。
3. **融合权重：** 优先 **Modal top2 equal** 或 **Modal η-weight**。
4. **评估：** 新场景接入 `config/scenarios/`，跑 `chFusion_plan2_diff_domain_verify.py`，看单域榜 + **跨域 aggregate**，不单凭一场景选方法。

---

## 4. 工程产出清单

| 类型 | 路径 |
|------|------|
| 脚本 | `notebooks/scripts/chFusion_fft-q.py` |
| 脚本 | `notebooks/scripts/chFusion_plan2.py` |
| 脚本 | `notebooks/scripts/chFusion_plan2_diff_domain_verify.py` |
| 脚本 | `notebooks/scripts/chFusion_pca_svd.py`（单场景） |
| 脚本 | `notebooks/scripts/chFusion_pca_svd_cross_domain.py`（跨域） |
| 脚本 | `notebooks/scripts/chFusion_pca_svd_p1_diag.py`（091339 诊断） |
| 核心 API | `src/ble_analysis/chfusion.py` — Plan2 Modal |
| 核心 API | `src/ble_analysis/pca_svd.py` — PCA/复 PCA 算法 |
| **流水线** | `src/ble_analysis/pca_svd_pipeline.py` — 实验表、排行榜、跨域、诊断 |
| 设计文档 | `docs/chFusion_pca_svd_plan.md`（§9 方法流程、§11 结论与开放问题） |
| 场景配置 | `config/scenarios/cs_*.json` |
| 报告缓存 | `outputs/reports/chfusion_pca_svd_*.npy` |

---

## 5. PCA/SVD 探索收官要点

**已闭合：** 带通 v1、SVD Complex \|u₁\|、Remote·e^jφ、Dual-Amp 部署路线；跨域 **Modal 9.45%** 仍为默认。

**PCA 最优但未及 Modal：** PCA-Modal3 top16 跨域 **10.85%**；复整合方案4 **11.95%**（不 oracle 选端）。

**091339 机理：** 复 PCA 整合在半频/倍频窗失效；Plan2 Modal 用单道带通，不出现同类 PC1 半频。PCA-Modal 差在**模态内 72 道 PCA**，非 top2 丢模态 alone。

## 6. 保留问题（详见 plan §11.3）

- Q1：PCA 模态内 — top1 信道 vs PCA vs top-K 细调
- Q2：复 PCA 半频抑制（谐波门控 / PC1 后再带通）
- Q3：PCA-Modal 与 Plan2 窗级共识门控
- Q4：更多场景（人体/非金属）验证
- Q5：Total ch-η 单场景调参是否值得尾部风险

---

*文档生成依据：三脚本实现、`docs/CS呼吸算法验证整体进度.md`、以及 cs_091339 / cs_095806 / cs_102621 实测输出。*
