# Notebooks 说明

本目录包含 BLE HCI 感知数据的 Jupyter 分析 notebook。按文件名前缀分为三类：

| 前缀 | 项目 | 说明 |
|------|------|------|
| **`glb_`** | Globecom 26 投稿 | CS / DF 金属板实验的呼吸指标估计与评估 |
| **`dip_`** | Direct IQ Pipeline | 直接 IQ 采集数据的加载、滤波与分析 |
| **其他**（`load_*`、`show_*`、`csdf_*` 等） | 早期探索代码 | 历史 notebook，逻辑已过时或已被 `glb_*` / `ble_analysis` 替代，**可不看** |

---

## Globecom 26 投稿（`glb_*`）

面向 Channel Sounding（CS）与 Direction Finding（DF）金属板场景的呼吸 BPM、IE 比、apnea 检测与误差评估。

| Notebook | 用途 |
|----------|------|
| [`glb_cs_load_and_explore.ipynb`](glb_cs_load_and_explore.ipynb) | CS 数据一键加载、单通道提取、采样率诊断与基础绘图 |
| [`glb_cs_segment_breath_analysis.ipynb`](glb_cs_segment_breath_analysis.ipynb) | CS 分段呼吸处理：按 GT 配置跑 BPM/IE/apnea 指标与误差可视化 |
| [`glb_cs_full_pipeline_demo.ipynb`](glb_cs_full_pipeline_demo.ipynb) | 全通道滤波算法步骤演示（**冻结，不再维护**，仅作参考） |
| [`glb_load_cs_saved_frames_show_analysis.ipynb`](glb_load_cs_saved_frames_show_analysis.ipynb) | 跳转说明：原 monolithic notebook 已拆分为上面三个 |
| [`glb_load_df_saved_frames_show_analysis.ipynb`](glb_load_df_saved_frames_show_analysis.ipynb) | DF 帧数据加载与分析（Globecom DF 实验） |

**推荐 CS 流程**：`glb_cs_load_and_explore` → `glb_cs_segment_breath_analysis`

---

## Direct IQ Pipeline（`dip_*`）

面向 DIP（`dip_direct_iq`）采集格式：仅 Local IQ、采样率高于 CS，复用 `src/ble_analysis/` 加载与滤波模块。

| Notebook | 用途 |
|----------|------|
| [`dip_load_and_filter_example.ipynb`](dip_load_and_filter_example.ipynb) | DIP JSONL 加载 → local IQ 提取 → 采样率估计 → 可选重采样 → 呼吸带通滤波 → 可视化 |

---

## 早期代码（可忽略）

以下 notebook 为项目早期手工实验，未接入 `ble_analysis` 工具包，保留仅供参考：

- `load_cs_saved_frames*.ipynb`、`load_df_saved_frames*.ipynb`、`load_saved_frames*.ipynb`
- `show_analysis_cs_frames_*.ipynb`、`show_analysis_df_frames_*.ipynb`
- `csdf_human.ipynb`、`csdf_power_and_range.ipynb`

---

## 通用引导

所有 **`glb_*`** 与 **`dip_*`** notebook 的第一个 code cell 都会：

1. 向上查找含 `src/` 的项目根目录
2. 将 `src/` 加入 `sys.path`
3. 调用 `ble_analysis.bootstrap.init_notebook()` 创建 `outputs/` 子目录

API 文档见 [`../src/ble_analysis/README.md`](../src/ble_analysis/README.md)。
