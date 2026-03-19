# urbanmorphology

**Annual Local Climate Zone Mapping & Urban Morphology Analysis**
**逐年城市局地气候区制图与城市形态分析**

> A Python package for producing annual LCZ classification maps of cities using Google Earth Engine, with built-in support for change detection, temporal consistency correction, and three configurable classification scenarios.
>
> 一个基于 Google Earth Engine 的 Python 工具包，用于生成城市逐年局地气候区（LCZ）分类图，内置变化检测、时序一致性校正，并支持三种可配置的分类场景。

---

## Table of Contents · 目录

1. [Overview · 项目概述](#1-overview--项目概述)
2. [Package Structure · 包结构](#2-package-structure--包结构)
3. [Installation · 安装](#3-installation--安装)
4. [Quick Start · 快速上手](#4-quick-start--快速上手)
5. [Configuration · 配置说明](#5-configuration--配置说明)
6. [Processing Pipeline · 六步处理流程](#6-processing-pipeline--六步处理流程)
7. [Classification Scenarios · 分类场景](#7-classification-scenarios--分类场景)
8. [Module Reference · 模块说明](#8-module-reference--模块说明)
9. [CLI Reference · 命令行参数](#9-cli-reference--命令行参数)
10. [Troubleshooting · 常见问题](#10-troubleshooting--常见问题)
11. [LCZ Class Reference · LCZ 类别参考](#11-lcz-class-reference--lcz-类别参考)

---

## 1. Overview · 项目概述

**urbanmorphology** automates the production of annual LCZ maps for a large number of cities by chaining six processing steps on Google Earth Engine (GEE). The pipeline ingests Landsat surface reflectance composites and Google Satellite Embedding features, applies Random Forest classification, corrects temporal inconsistencies using a year-of-disturbance (YOD) signal derived from LandTrendr, and exports the final per-year maps as GEE assets.

**urbanmorphology** 通过在 Google Earth Engine（GEE）上串联六个处理步骤，自动化生成大量城市的逐年 LCZ 分类图。流程以 Landsat 地表反射率合成影像和 Google Satellite Embedding 特征为输入，采用随机森林分类器，利用 LandTrendr 提取的变化年份（YOD）信号校正时序不一致性，最终将逐年分类结果导出为 GEE 资产。

The package is designed to be flexible: users with different levels of labelled data can choose from three classification scenarios, ranging from fully supervised (per-year training samples) to fully unsupervised (no external samples required).

本包设计灵活：拥有不同程度标注数据的用户可从三种分类场景中选择，从完全监督（逐年训练样本）到完全无监督（无需外部样本）均有支持。

---

## 2. Package Structure · 包结构

```
urbanmorphology/
├── urbanlst.py                    # CLI entry point & six-step pipeline
│                                  # 命令行入口 & 六步流程主控
├── setup.py                       # Package installation · 包安装
├── .gitignore
├── README.md
└── utils/
    ├── config.py                  # All user-facing configuration
    │                              # 所有用户配置项
    ├── time_series_scenarios.py   # Three classification scenarios (core)
    │                              # 三种分类场景（核心模块）
    ├── geemodules.py              # GEE wrappers: LandsatProcessor,
    │                              #   ChangeDetector, LCZClassifier,
    │                              #   TemporalAggregator
    ├── sampling.py                # Training sample strategies
    │                              # 训练样本采集策略
    ├── processors.py              # AssetManager, LSTProcessor,
    │                              #   DetrendAnalyzer
    ├── accuracy.py                # Accuracy validation utilities
    │                              # 精度验证工具
    ├── lcz_tools.py               # LCZ transition & summary statistics
    │                              # LCZ 转移矩阵与统计
    ├── visualizer.py              # LSTPlotter, LCZPlotter
    │                              # 可视化工具
    ├── TaskManager.py             # GEE task polling & local file manager
    │                              # GEE 任务轮询 & 本地文件管理
    └── pixel_plot.py              # Pixel-level time-series plots
                                   # 像元级时间序列绘图
```

---

## 3. Installation · 安装

### Prerequisites · 前置条件

| Requirement | Version | Notes · 说明 |
|---|---|---|
| Python | ≥ 3.9 | |
| earthengine-api | ≥ 0.1.370 | `pip install earthengine-api` |
| Google Earth Engine account | — | Requires project access · 需要项目访问权限 |
| GEE project | — | Set `GEE_PROJECT` in `config.py` · 在 `config.py` 中设置 |

### Install · 安装步骤

```bash
# Clone the repository · 克隆仓库
git clone https://github.com/tongmiao233/urbanmorphology.git
cd urbanmorphology

# Install dependencies · 安装依赖
pip install earthengine-api

# Install the package in editable mode · 以可编辑模式安装
pip install -e .

# Authenticate with Google Earth Engine · GEE 身份认证
earthengine authenticate
```

---

## 4. Quick Start · 快速上手

### Step 1 – Edit the configuration · 第一步：编辑配置文件

Open `utils/config.py` and fill in the **REQUIRED** section at the top. All parameters marked `← REQUIRED` must be provided before running.

打开 `utils/config.py`，填写顶部的 **REQUIRED** 区块。所有标注 `← REQUIRED` 的参数必须在运行前填写。

```python
# utils/config.py  ── ① REQUIRED ──────────────────────────────────────────
GEE_PROJECT = "your-gee-project-id"        # ← REQUIRED
CITY_IDS    = [36081]                       # ← REQUIRED
START_YEAR  = 2003
END_YEAR    = 2024

GEE_ASSETS = {
    "LCZ_CLASSIFICATION": "projects/your-project/assets/lcz_classification/",
    "LCZ_CORRECTED":      "projects/your-project/assets/lcz_corrected/",
    "LCZ_YOD":            "projects/your-project/assets/lcz_yod/",
    "LCZ_FINAL":          "projects/your-project/assets/lcz_final/",
    "LCZ_TEMP_SMOOTH":    "projects/your-project/assets/lcz_smooth/",
    "GUB":                "projects/globallcz/assets/gub/gub2018",
}
```

### Step 2 – Choose a scenario and enable steps · 第二步：选择场景并开启步骤

```python
# utils/config.py  ── ② PIPELINE ─────────────────────────────────────────
STEPS = {
    "STEP1_LANDSAT_EXPORT":   False,  # skip if composites already exist
    "STEP2_CHANGE_DETECTION": False,  # skip if YOD asset already exists
    "STEP3_CLASSIFICATION":   True,   # ← enable classification
    "STEP4_AGGREGATION":      True,   # ← enable temporal correction
    "STEP4_TEMPORAL_SMOOTHING": False,
    "STEP4_LANDCOVER_FUSION":   False,
    "STEP5_VISUALISATION":    False,
    "STEP6_VALIDATION":       False,
}

# utils/config.py  ── ③ SCENARIO ─────────────────────────────────────────
ACTIVE_SCENARIO = 3   # 1, 2, or 3 · 选择 1、2 或 3

# For Scenario 3 · 场景三专用参数:
SCENARIO3_MAP_2020_ASSET = "projects/jjjdata/assets/aggregatedmaps_v2/result2020"
SCENARIO3_CONFI_MASK_OUT = "projects/your-project/assets/confi_mask_36081"
```

### Step 3 – Run · 第三步：运行

```bash
# Command line · 命令行
urbanlst --city_ids 36081

# Multiple cities · 多个城市
urbanlst --city_ids 36081 36082 36083
```

```python
# Or in Python / Jupyter · 或在 Python / Jupyter 中
from urbanlst import main
main(city_ids=[36081])
```

---

## 5. Configuration · 配置说明

All configuration lives in `utils/config.py`. The file is divided into four clearly labelled sections. Users typically only need to edit sections ① and ③.

所有配置均位于 `utils/config.py`，文件分为四个清晰标注的区块。用户通常只需编辑 ① 和 ③ 两个区块。

### ① REQUIRED · 必填项

| Parameter · 参数 | Type · 类型 | Description · 说明 |
|---|---|---|
| `GEE_PROJECT` | `str` | GEE project ID · GEE 项目 ID |
| `CITY_IDS` | `list[int]` | City IDs matching the GUB feature collection · 与 GUB 要素集匹配的城市 ID |
| `START_YEAR` | `int` | First year to process · 起始年份 |
| `END_YEAR` | `int` | Last year to process (inclusive) · 结束年份（含） |
| `GEE_ASSETS` | `dict` | Output asset folder paths · 输出资产文件夹路径字典 |
| `LANDSAT_BASES` | `list[str]` | Landsat composite asset search paths · Landsat 合成影像资产搜索路径 |
| `LANDSAT_EXPORT_BASE` | `str` | Destination for new Landsat composite exports · 新 Landsat 合成影像的导出目标路径 |

### ② PIPELINE · 流程开关

Each key in `STEPS` controls one processing step. Set to `True` to run, `False` to skip. Steps whose output GEE asset already exists are automatically skipped regardless of this flag.

`STEPS` 中每个键控制一个处理步骤，设为 `True` 运行，`False` 跳过。无论此标志如何设置，输出 GEE 资产已存在的步骤都会自动跳过。

| Key · 键 | Step · 步骤 |
|---|---|
| `STEP1_LANDSAT_EXPORT` | Export Landsat 3-year median composites · 导出 Landsat 三年中值合成影像 |
| `STEP2_CHANGE_DETECTION` | LandTrendr texture change detection → YOD · LandTrendr 纹理变化检测 → YOD |
| `STEP3_CLASSIFICATION` | LCZ classification (scenario-based) · LCZ 分类（场景驱动） |
| `STEP4_AGGREGATION` | Temporal consistency correction & YOD fusion · 时序一致性校正与 YOD 融合 |
| `STEP4_TEMPORAL_SMOOTHING` | Optional temporal mode filter before correction · 可选：校正前的时序众数滤波 |
| `STEP4_LANDCOVER_FUSION` | Replace non-urban pixels with FROM-GLC Plus · 用 FROM-GLC Plus 替换非城市像元 |
| `STEP5_VISUALISATION` | LCZ change visualisations (requires local rasters) · LCZ 变化可视化（需本地栅格文件） |
| `STEP6_VALIDATION` | Accuracy validation against reference dataset · 对照参考数据集进行精度验证 |

### ③ SCENARIO · 场景参数

Set `ACTIVE_SCENARIO` to `1`, `2`, or `3`, then fill in the corresponding parameter block. See [Section 7](#7-classification-scenarios--分类场景) for details on each scenario.

将 `ACTIVE_SCENARIO` 设为 `1`、`2` 或 `3`，然后填写对应参数块。各场景详情见[第 7 节](#7-classification-scenarios--分类场景)。

### ④ ADVANCED · 高级参数

These parameters have sensible defaults and rarely need changing.

这些参数有合理的默认值，通常无需修改。

| Parameter · 参数 | Default · 默认值 | Description · 说明 |
|---|---|---|
| `SCALE` | `100` | Output pixel size in metres · 输出像元大小（米） |
| `CLASSIFIER_TREES` | `150` | RF tree count · 随机森林树数量 |
| `SAMPLES_PER_CLASS` | `200` | Training samples per LCZ class (Sc. 1 & 2) · 每类训练样本数（场景 1 & 2） |
| `SCENARIO3_CF_N_PER_CLASS` | `100` | Samples per class per confidence-mask RF round · 每轮置信掩膜每类样本数 |
| `SCENARIO3_CF_ROUNDS` | `3` | Number of confidence-mask RF rounds · 置信掩膜 RF 轮数 |
| `SCENARIO3_CF_RF_TREES` | `100` | Trees per confidence-mask round · 每轮置信掩膜树数量 |
| `SCENARIO3_SAMPLES_PER_CLASS` | `300` | Samples per class for final Sc. 3 classification · 场景三最终分类每类样本数 |
| `SCENARIO3_TILE_SCALE` | `16` | GEE tileScale for sampling (increase for large cities) · 采样 tileScale（大城市建议增大） |
| `GLC_TO_LCZ_MAP` | `{1:14, 2:11, …}` | FROM-GLC Plus → LCZ class mapping · FROM-GLC Plus 到 LCZ 类别映射 |

---

## 6. Processing Pipeline · 六步处理流程

The pipeline runs sequentially for each city ID. Steps whose output GEE asset already exists are automatically skipped, making it safe to re-run after interruption.

流程对每个城市 ID 顺序执行。输出 GEE 资产已存在的步骤将自动跳过，因此中断后重新运行是安全的。

### Step 1 · Landsat Composite Export · Landsat 合成影像导出

For each year in `[START_YEAR, END_YEAR]`, a **three-year median composite** is built from Landsat 5 (≤ 2012) or Landsat 8/9 (> 2012) surface reflectance. Images are cloud-masked using the `QA_PIXEL` band and exported as GEE assets at 30 m resolution. The composite window spans `year−1` to `year+1` to maximise cloud-free coverage.

对 `[START_YEAR, END_YEAR]` 中的每一年，基于 Landsat 5（≤ 2012）或 Landsat 8/9（> 2012）地表反射率构建**三年中值合成影像**。使用 `QA_PIXEL` 波段进行云掩膜处理，以 30 m 分辨率导出为 GEE 资产。合成窗口跨越 `year−1` 至 `year+1` 以最大化无云覆盖。

> **Skip condition · 跳过条件:** Asset `landsat_{year}_{city_id}_3yr` already exists in any path listed in `LANDSAT_BASES`.

### Step 2 · Change Detection (YOD) · 变化检测（YOD）

LandTrendr-based **texture change detection** is applied to the Landsat composites to identify the year in which each pixel underwent a significant land-cover change. The result is a single-band integer image (`YOD_{city_id}_open`) where pixel values represent the year of disturbance (0 = no change detected).

对 Landsat 合成影像应用基于 LandTrendr 的**纹理变化检测**，识别每个像元发生显著土地覆盖变化的年份。结果为单波段整型影像（`YOD_{city_id}_open`），像元值表示变化年份（0 = 未检测到变化）。

> **Skip condition · 跳过条件:** Asset `YOD_{city_id}_open` already exists in `GEE_ASSETS["LCZ_YOD"]`.

### Step 3 · LCZ Classification · LCZ 分类

The core classification step. One of three scenarios is executed based on `ACTIVE_SCENARIO` in `config.py` (see [Section 7](#7-classification-scenarios--分类场景)). The output is one LCZ image per year, exported to `GEE_ASSETS["LCZ_CLASSIFICATION"]`.

核心分类步骤。根据 `config.py` 中的 `ACTIVE_SCENARIO` 执行三种场景之一（见[第 7 节](#7-classification-scenarios--分类场景)）。输出为每年一张 LCZ 影像，导出至 `GEE_ASSETS["LCZ_CLASSIFICATION"]`。

### Step 4 · Temporal Consistency Correction · 时序一致性校正

The per-year classification results are stacked and corrected for temporal inconsistencies using the YOD image. The correction logic propagates the most recent reliable classification backwards in time, replacing pixels that changed before the YOD year with the post-change label. Two optional sub-steps are available:

逐年分类结果被堆叠，并利用 YOD 影像校正时序不一致性。校正逻辑将最近可靠的分类结果向历史年份回填，用变化后的标签替换 YOD 年份之前发生变化的像元。两个可选子步骤：

- **`STEP4_TEMPORAL_SMOOTHING`** — Applies a temporal mode filter across the time series before correction, suppressing single-year classification noise. · 在校正前对时间序列应用时序众数滤波，抑制单年分类噪声。
- **`STEP4_LANDCOVER_FUSION`** — Replaces non-urban pixels with FROM-GLC Plus land-cover classes after correction. · 校正后用 FROM-GLC Plus 土地覆盖类别替换非城市像元。

**Outputs · 输出:**

| Asset folder · 资产文件夹 | Content · 内容 |
|---|---|
| `LCZ_CORRECTED` | Per-year temporally corrected LCZ maps · 逐年时序校正 LCZ 图 |
| `LCZ_TEMP_SMOOTH` | Per-year smoothed intermediate results (optional) · 逐年平滑中间结果（可选） |
| `LCZ_FINAL` | Per-year YOD-integrated final LCZ maps · 逐年 YOD 融合最终 LCZ 图 |

### Step 5 · Visualisation · 可视化

Generates LCZ change charts and transition matrices from locally downloaded raster files. Requires `LOCAL_DATA_ROOT` and `CHANGE_CLASS_CSV` to be set in `config.py`. Can also be run standalone via `utils.pixel_plot`.

从本地下载的栅格文件生成 LCZ 变化图表和转移矩阵。需要在 `config.py` 中设置 `LOCAL_DATA_ROOT` 和 `CHANGE_CLASS_CSV`。也可通过 `utils.pixel_plot` 单独运行。

### Step 6 · Accuracy Validation · 精度验证

Compares the final LCZ maps against a reference feature collection (`VALIDATION_FC`) using GEE's `errorMatrix` function. Reports overall accuracy (OA) and the full confusion matrix for each year and city.

使用 GEE 的 `errorMatrix` 函数，将最终 LCZ 图与参考要素集（`VALIDATION_FC`）进行比较，报告每年每个城市的总体精度（OA）和完整混淆矩阵。

---

## 7. Classification Scenarios · 分类场景

All three scenarios are implemented in `utils/time_series_scenarios.py` and exposed through the `LCZTimeSeriesScenarios` class.

三种场景均在 `utils/time_series_scenarios.py` 中实现，通过 `LCZTimeSeriesScenarios` 类对外提供。

**Feature source by year · 按年份的特征来源:**

| Year range · 年份范围 | Feature source · 特征来源 |
|---|---|
| ≤ 2016 | Landsat composite (6 bands + NDVI, NDBI, MNDWI, NIR_STD) |
| > 2016 | Google Satellite Embedding (`EMB_*` bands) |

---

### Scenario 1 · 场景一 — Yearly Sample Assets · 逐年样本资产

**Best for · 适用场景:** You have a dedicated, labelled training sample asset for every target year.

**最适合：** 每个目标年份都有专属的标注训练样本资产。

**How it works · 工作原理:** For each year, the per-year sample asset is loaded, feature values are extracted at sample locations, a Random Forest is trained independently, and the full image is classified. A focal-mode spatial filter is applied after classification to reduce salt-and-pepper noise.

**工作原理：** 对每一年，加载对应年份的样本资产，在样本位置提取特征值，独立训练随机森林并对全图分类，分类后应用焦点众数空间滤波以减少椒盐噪声。

**Configuration · 配置:**

```python
# utils/config.py
ACTIVE_SCENARIO = 1
SCENARIO1_SAMPLE_TEMPLATE = "users/yourname/Samples/training_{year}"
# {year} is replaced with the actual year · {year} 会被替换为实际年份
```

**Python API:**

```python
from utils.time_series_scenarios import LCZTimeSeriesScenarios

runner = LCZTimeSeriesScenarios()
ic = runner.scenario_one(city_id=36081)  # returns ee.ImageCollection
```

---

### Scenario 2 · 场景二 — Single-Year Sample + YOD Fusion · 单年样本 + YOD 融合

**Best for · 适用场景:** You have one reliable labelled sample (e.g. for 2020) and want to reuse it across all years.

**最适合：** 你只有一个可靠的标注样本（例如 2020 年），希望将其复用于所有年份。

**How it works · 工作原理:** A single fixed sample asset is used for all years. Two strategies are applied depending on the year:

**工作原理：** 所有年份使用同一个固定样本资产，根据年份采用两种策略：

- **HYBRID (year ≤ 2016):** Stable pixels (YOD = 0) from the fixed sample are combined with *ghost samples* drawn from FROM-GLC Plus in areas of detected change (YOD ≠ 0). The final map uses the GLC guide as a base layer and replaces built-up pixels (`lc_label = 8`) with the RF result.
- **HYBRID（年份 ≤ 2016）：** 固定样本中的稳定像元（YOD = 0）与从 FROM-GLC Plus 在变化区域（YOD ≠ 0）采集的*幽灵样本*合并。最终图以 GLC 引导图为底图，将建成区像元（`lc_label = 8`）替换为 RF 分类结果。

- **STABLE (year > 2016):** Only stable pixels from the fixed sample are used, and the RF result is taken directly.
- **STABLE（年份 > 2016）：** 仅使用固定样本中的稳定像元，直接采用 RF 分类结果。

**Configuration · 配置:**

```python
# utils/config.py
ACTIVE_SCENARIO = 2
SCENARIO2_SAMPLE_ASSET = "users/yourname/Samples/training_2020"
SCENARIO2_GHOST_POINTS = 500   # ghost samples per changed area · 变化区域的幽灵样本数
```

**Python API:**

```python
runner = LCZTimeSeriesScenarios()
ic = runner.scenario_two(city_id=36081)  # returns ee.ImageCollection
```

---

### Scenario 3 · 场景三 — No External Samples · 无外部样本

**Best for · 适用场景:** You have no labelled training data. Only a 2020 LCZ product is required.

**最适合：** 没有标注训练数据，仅需一个 2020 年 LCZ 产品。

**How it works · 工作原理:** The workflow proceeds in two stages that must be run separately:

**工作原理：** 工作流分为两个阶段，必须分开运行：

**Stage 1 – Confidence Mask · 阶段一：置信掩膜**

Three independent Random Forest classifiers are trained on the 2020 Google Satellite Embedding features using the 2020 LCZ product as pseudo-labels. A pixel is marked as *confident* only when all three predictions agree with each other **and** all three equal the pseudo-label. The confidence mask is exported as a GEE asset before proceeding to Stage 2.

在 2020 年 Google Satellite Embedding 特征上，以 2020 年 LCZ 产品为伪标签，训练三个独立的随机森林分类器。仅当三个预测结果相互一致**且**均与伪标签相符时，该像元才被标记为*置信*。置信掩膜导出为 GEE 资产后，方可进行阶段二。

**Stage 2 – Per-year Classification · 阶段二：逐年分类**

- **Embedding years (> 2016):** The confidence mask restricts sampling to high-confidence pixels. A RF is trained on these stable samples and applied to the full embedding image.
- **Embedding 年份（> 2016）：** 置信掩膜将采样限制在高置信度像元。在这些稳定样本上训练 RF，并应用于全图。

- **Landsat years (≤ 2016):** A label image is built by fusing the FROM-GLC Plus land-cover guide with the 2020 LCZ product. After RF classification, built-up pixels (`lc_label = 8`) are replaced by the RF result.
- **Landsat 年份（≤ 2016）：** 通过融合 FROM-GLC Plus 土地覆盖引导图与 2020 年 LCZ 产品构建标签影像。RF 分类后，建成区像元（`lc_label = 8`）被 RF 结果替换。

**Configuration · 配置:**

```python
# utils/config.py
ACTIVE_SCENARIO           = 3
SCENARIO3_MAP_2020_ASSET  = "projects/jjjdata/assets/aggregatedmaps_v2/result2020"
SCENARIO3_CONFI_MASK_OUT  = "projects/your-project/assets/confi_mask_36081"

# Tuning · 调参 (in ④ ADVANCED)
SCENARIO3_CF_N_PER_CLASS      = 100   # samples/class per CF round · 每轮置信掩膜每类样本数
SCENARIO3_CF_ROUNDS           = 3     # number of RF rounds · RF 轮数
SCENARIO3_SAMPLES_PER_CLASS   = 300   # samples/class for final classification · 最终分类每类样本数
SCENARIO3_TILE_SCALE          = 16    # increase for large cities · 大城市建议增大
```

**Two-step Python API · 两步 Python 用法:**

```python
import ee
from utils.time_series_scenarios import LCZTimeSeriesScenarios

ee.Initialize(project="your-gee-project")

runner = LCZTimeSeriesScenarios(
    map_2020_asset_id="projects/jjjdata/assets/aggregatedmaps_v2/result2020",
    confi_mask_asset_out="projects/your-project/assets/confi_mask_36081",
)

# Stage 1: export confidence mask
# Wait for the GEE task to reach COMPLETED status before running Stage 2.
# 阶段一：导出置信掩膜
# 等待 GEE 任务状态变为 COMPLETED 后再执行阶段二。
runner.export_confi_mask(city_id=36081)

# Stage 2: run per-year classification (after Stage 1 is COMPLETED)
# 阶段二：运行逐年分类（在阶段一任务完成后执行）
ic = runner.scenario_three(city_id=36081, use_confi=True)
```

---

## 8. Module Reference · 模块说明

### `utils/config.py`

The single configuration file for the entire package. Organised into four sections (REQUIRED, PIPELINE, SCENARIO, ADVANCED). See [Section 5](#5-configuration--配置说明) for a full parameter reference.

整个包的唯一配置文件，分为四个区块（REQUIRED、PIPELINE、SCENARIO、ADVANCED）。完整参数说明见[第 5 节](#5-configuration--配置说明)。

---

### `utils/time_series_scenarios.py`

The core classification module. Provides the `LCZTimeSeriesScenarios` class which implements all three scenarios.

核心分类模块，提供实现三种场景的 `LCZTimeSeriesScenarios` 类。

```python
from utils.time_series_scenarios import LCZTimeSeriesScenarios

runner = LCZTimeSeriesScenarios(
    years=[2017, 2018, 2019, 2020],   # optional override · 可选覆盖年份列表
    map_2020_asset_id="...",           # required for Scenario 3 · 场景三必填
    confi_mask_asset_out="...",        # required for Scenario 3 · 场景三必填
    n_per_class=300,                   # samples per class · 每类样本数
    tile_scale=16,                     # GEE tileScale · GEE tileScale 参数
)
```

**Public methods · 公开方法:**

| Method · 方法 | Returns · 返回值 | Description · 说明 |
|---|---|---|
| `scenario_one(city_id)` | `ee.ImageCollection` | Yearly-sample classification · 逐年样本分类 |
| `scenario_two(city_id)` | `ee.ImageCollection` | Single-year sample + YOD fusion · 单年样本 + YOD 融合分类 |
| `scenario_three(city_id, use_confi, export_confi_mask)` | `ee.ImageCollection` | Confidence-mask based classification · 置信掩膜分类 |
| `build_confi_mask(city_id)` | `ee.Image` | Build confidence mask in-memory · 在内存中构建置信掩膜 |
| `export_confi_mask(city_id)` | `None` | Submit confidence mask export task to GEE · 向 GEE 提交置信掩膜导出任务 |

---

### `utils/geemodules.py`

Low-level GEE wrappers used internally by the pipeline. Can also be used directly for custom workflows.

流程内部使用的底层 GEE 封装，也可直接用于自定义工作流。

| Class · 类 | Key method · 主要方法 | Description · 说明 |
|---|---|---|
| `LandsatProcessor` | `get_median_composite(year, bound)` | Build 3-year Landsat median composite · 构建三年 Landsat 中值合成影像 |
| `LandsatProcessor` | `get_median_composite_by_city(year, city_id)` | Load pre-exported Landsat composite from GEE asset · 从 GEE 资产加载预导出合成影像 |
| `ChangeDetector` | `detect_changes(city_id, years, bound)` | LandTrendr texture YOD detection · LandTrendr 纹理 YOD 检测 |
| `LCZClassifier` | `classify_image(feat_img, samples)` | Train RF and classify a single image · 训练 RF 并分类单幅影像 |
| `TemporalAggregator` | `correct_temporal_consistency(stacked, years)` | Stack & correct LCZ time series · 堆叠并校正 LCZ 时间序列 |
| `TemporalAggregator` | `integrate_with_change_detection(corrected, yod, years)` | YOD-guided backward integration · YOD 引导向后融合 |
| `TemporalAggregator` | `temporal_smoothing(lcz_series)` | Apply temporal mode filter · 应用时序众数滤波 |

---

### `utils/sampling.py`

Training sample collection strategies. These functions return `ee.FeatureCollection` objects ready to be passed to a classifier.

训练样本采集策略。这些函数返回可直接传入分类器的 `ee.FeatureCollection` 对象。

| Function · 函数 | Description · 说明 |
|---|---|
| `get_stable_samples(city_id, year, region)` | Sample from pixels stable before the target year (YOD < year) · 从目标年份前稳定像元采样（YOD < year） |
| `get_target_year_samples(city_id, year, region)` | Sample from pixels stable in the target year (YOD ≠ year) · 从目标年份稳定像元采样（YOD ≠ year） |
| `get_cross_city_samples(target_city_id, year, region_fc, other_ids)` | Pool samples from multiple cities · 从多个城市汇集样本 |
| `evaluate_sampling_strategies(city_id, year, region)` | Compare all strategies side-by-side · 并排比较所有策略 |
| `sample_size_sensitivity_test(city_id, year, region)` | Test accuracy vs. sample size · 测试精度与样本量的关系 |

---

### `utils/processors.py`

Asset management and LST processing utilities.

资产管理和 LST 处理工具。

| Class · 类 | Description · 说明 |
|---|---|
| `AssetManager` | Check, find, and list GEE assets · 检查、查找和列出 GEE 资产 |
| `LSTProcessor` | Extract and process Land Surface Temperature from Landsat thermal bands · 从 Landsat 热红外波段提取和处理地表温度 |
| `DetrendAnalyzer` | Detrend LST time series to remove long-term warming signal · 对 LST 时间序列去趋势，去除长期增温信号 |

---

### `utils/accuracy.py`

Accuracy validation against a reference feature collection.

对照参考要素集进行精度验证。

```python
from utils.accuracy import validate_year, validate_series

# Validate a single year · 验证单年
oa, matrix = validate_year(
    city_id=36081,
    year=2020,
    validation_fc_path="projects/yourproject/assets/val_samples",
    label_field="LCZ",
)
print(f"Overall Accuracy: {oa.getInfo():.3f}")

# Validate all years at once · 一次验证所有年份
results = validate_series(
    city_id=36081,
    years=list(range(2003, 2025)),
    validation_fc_path="projects/yourproject/assets/val_samples",
    label_field="LCZ",
)
for year, (oa, matrix) in results.items():
    print(f"{year}: OA = {oa.getInfo():.3f}")
```

---

### `utils/lcz_tools.py`

LCZ transition statistics and city-level summaries.

LCZ 转移统计和城市级汇总。

| Function · 函数 | Description · 说明 |
|---|---|
| `compute_lcz_transition(city_id, output_path)` | Compute year-to-year LCZ transition matrix and save to CSV · 计算逐年 LCZ 转移矩阵并保存为 CSV |
| `summarize_cities(city_ids, output_path)` | Aggregate LCZ area statistics across cities · 汇总多城市 LCZ 面积统计 |

---

### `utils/visualizer.py`

Plotting utilities for LST and LCZ change analysis. Requires locally downloaded raster files.

LST 和 LCZ 变化分析绘图工具，需要本地下载的栅格文件。

| Class · 类 | Description · 说明 |
|---|---|
| `LSTPlotter` | Plot LST time series, seasonal patterns, and urban heat island intensity · 绘制 LST 时间序列、季节模式和城市热岛强度 |
| `LCZPlotter` | Plot LCZ class area changes and transition Sankey diagrams · 绘制 LCZ 类别面积变化和转移桑基图 |

---

### `utils/TaskManager.py`

GEE task management and local file discovery.

GEE 任务管理和本地文件发现。

| Class · 类 | Method · 方法 | Description · 说明 |
|---|---|---|
| `TaskManager` | `wait_for_tasks()` | Poll GEE every 90 s until all READY/RUNNING tasks complete · 每 90 秒轮询 GEE，直至所有任务完成 |
| `FileManager` | `get_city_files(city_id, input_folder)` | Discover per-city raster files; supports stacked, single, and separate LST/LCZ layouts · 发现城市栅格文件，支持堆叠、单文件和分离 LST/LCZ 格式 |

---

### `utils/pixel_plot.py`

Single-pixel LST time-series inspection tool. Useful for debugging classification results at specific locations.

单像元 LST 时间序列检查工具，适用于在特定位置调试分类结果。

```bash
python -m utils.pixel_plot CITY_ID day|night CHANGE_CODE PIXEL_INDEX
```

The command plots the median LST of stable urban pixels with a fitted linear trend, the raw LST values for the selected pixel, and detrended values on a secondary y-axis.

该命令绘制稳定城市像元的中值 LST 及拟合线性趋势、所选像元的原始 LST 值，以及次坐标轴上的去趋势值。

---

## 9. CLI Reference · 命令行参数

```
urbanlst --city_ids <ID [ID ...]>
         [--sampling_method {stable,target,cross,asset}]
         [--asset_path GEE_ASSET_PATH]
         [--asset_paths PATH [PATH ...]]
         [--class_property PROPERTY_NAME]
         [--val_ratio FLOAT]
```

| Argument · 参数 | Default · 默认值 | Description · 说明 |
|---|---|---|
| `--city_ids` | *(required · 必填)* | One or more city IDs to process · 一个或多个待处理城市 ID |
| `--sampling_method` | `stable` | Sampling strategy for Steps 1/4/6 · 第 1/4/6 步的采样策略 |
| `--asset_path` | `None` | GEE asset path for `asset` sampling method · `asset` 采样方法的 GEE 资产路径 |
| `--asset_paths` | `None` | Per-year asset paths for `asset` method · `asset` 方法的逐年资产路径 |
| `--class_property` | `LCZ` | Class property name in training samples · 训练样本中的类别属性名 |
| `--val_ratio` | `None` | Fraction of samples held out for validation (0–1) · 用于验证的样本比例（0–1） |

**Examples · 示例:**

```bash
# Process a single city with default settings · 以默认设置处理单个城市
urbanlst --city_ids 36081

# Process multiple cities · 处理多个城市
urbanlst --city_ids 36081 36082 36083

# Use cross-city sampling · 使用跨城市采样
urbanlst --city_ids 36081 --sampling_method cross

# Hold out 30 % of samples for validation · 保留 30% 样本用于验证
urbanlst --city_ids 36081 --val_ratio 0.3
```

---

## 10. Troubleshooting · 常见问题

### `User memory limit exceeded` — No task appears in GEE Task Manager

**Cause · 原因:** A synchronous `.getInfo()` call is materialising a large intermediate result on the GEE client before any export task is submitted. This typically occurs when the city region is very large.

**原因：** 同步 `.getInfo()` 调用在提交任何导出任务之前，在 GEE 客户端实体化了一个大型中间结果。这通常发生在城市区域非常大时。

**Fix · 解决方法:** Increase `SCENARIO3_TILE_SCALE` in `config.py`:

**解决方法：** 在 `config.py` 中增大 `SCENARIO3_TILE_SCALE`：

| City size · 城市规模 | Recommended value · 建议值 |
|---|---|
| Small · 小城市 | `8` |
| Large · 大城市 | `16` (default · 默认) |
| Very large · 超大城市 | `32` |

---

### `Please authorize access to your Earth Engine account`

**Cause · 原因:** GEE authentication has not been completed in the current environment.

**原因：** 当前环境尚未完成 GEE 身份认证。

**Fix · 解决方法:**

```bash
earthengine authenticate
# Follow the browser link and paste the verification code back into the terminal.
# 按照浏览器链接操作，将验证码粘贴回终端。
```

---

### `No Landsat asset found for city {city_id}, year {year}`

**Cause · 原因:** The Landsat composite for this city/year does not exist in any of the paths listed in `LANDSAT_BASES`.

**原因：** 该城市/年份的 Landsat 合成影像在 `LANDSAT_BASES` 中的任何路径下均不存在。

**Fix · 解决方法:** Enable `STEP1_LANDSAT_EXPORT = True` in `config.py` and re-run to generate the missing composites.

**解决方法：** 在 `config.py` 中启用 `STEP1_LANDSAT_EXPORT = True` 并重新运行以生成缺失的合成影像。

---

### `Classification failed: … no training samples`

**Cause · 原因:** The stratified sampling returned zero samples, usually because the confidence mask or YOD mask is too restrictive for this city.

**原因：** 分层采样返回零样本，通常是因为置信掩膜或 YOD 掩膜对该城市过于严格。

**Fix (Scenario 3) · 解决方法（场景三）:** Regenerate the confidence mask with a lower `SCENARIO3_CF_N_PER_CLASS` (e.g. 50) or fewer `SCENARIO3_CF_ROUNDS` (e.g. 2) to produce a less restrictive mask.

**解决方法（场景三）：** 以较小的 `SCENARIO3_CF_N_PER_CLASS`（例如 50）或较少的 `SCENARIO3_CF_ROUNDS`（例如 2）重新生成置信掩膜，以产生限制较少的掩膜。

---

### GEE task submitted but fails with `Computation timed out`

**Cause · 原因:** The computation graph is too complex for a single GEE task, often due to processing too many years at once.

**原因：** 计算图对于单个 GEE 任务过于复杂，通常是由于一次处理过多年份导致。

**Fix · 解决方法:** Process years in smaller batches by setting `START_YEAR` and `END_YEAR` to a narrower range and running multiple times.

**解决方法：** 通过将 `START_YEAR` 和 `END_YEAR` 设置为较小范围并多次运行，分批处理年份。

---

## 11. LCZ Class Reference · LCZ 类别参考

| Class · 类别 | Name (EN) | 名称（中文） | Code in asset · 资产中的编码 |
|---|---|---|---|
| LCZ 1 | Compact high-rise | 密集高层 | `1` |
| LCZ 2 | Compact mid-rise | 密集中层 | `2` |
| LCZ 3 | Compact low-rise | 密集低层 | `3` |
| LCZ 4 | Open high-rise | 开放高层 | `4` |
| LCZ 5 | Open mid-rise | 开放中层 | `5` |
| LCZ 6 | Open low-rise | 开放低层 | `6` |
| LCZ 7 | Lightweight low-rise | 轻质低层 | `7` |
| LCZ 8 | Large low-rise | 大型低层 | `8` |
| LCZ 9 | Sparsely built | 稀疏建成 | `9` |
| LCZ 10 | Heavy industry | 重工业 | `10` |
| LCZ A | Dense trees | 密集树木 | `11` |
| LCZ B | Scattered trees | 散生树木 | `12` |
| LCZ C | Bush / scrub | 灌木丛 | `13` |
| LCZ D | Low plants | 低矮植被 | `14` |
| LCZ E | Bare rock / paved | 裸岩/铺装 | `15` |
| LCZ F | Bare soil / sand | 裸土/沙地 | `16` |
| LCZ G | Water | 水体 | `17` |

---

*Documentation for urbanmorphology v2.0.0 · urbanmorphology v2.0.0 说明文档*
