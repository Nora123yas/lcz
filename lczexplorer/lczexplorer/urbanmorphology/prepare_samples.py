"""
prepare_samples.py
==================
将大连训练样本（projects/dalianlcz/assets/Samples/training）转换为
urbanmorphology 软件包 Scenario 1 / Scenario 2 所需的格式，并导出到 GEE。

原始数据结构
------------
  - 单个 FeatureCollection，每个 Feature 包含多个年份字段（2000, 2001, …, 2020）
  - 每个年份字段的值为该年对应的 LCZ 类别编号（整数，0 表示无效）

目标格式（软件包要求）
----------------------
  Scenario 1 – 逐年独立样本资产
    每个年份导出一个独立的 FeatureCollection，路径为：
      <OUTPUT_FOLDER>/training_{year}
    每个 Feature 只保留一个属性字段：
      "LCZ"（值为该年的 LCZ 类别编号）
    无效点（LCZ == 0）自动过滤。

  Scenario 2 – 单年样本资产
    选择一个参考年份（默认 2020），导出一个 FeatureCollection，路径为：
      <OUTPUT_FOLDER>/training_s2_ref
    字段同上，只保留 "LCZ"。

使用方法
--------
  1. 修改下方 ── USER SETTINGS ── 区域中的参数。
  2. 在已完成 GEE 认证的 Python 环境中运行：
       python3 prepare_samples.py
  3. 在 GEE Task Manager 中等待所有导出任务完成。
  4. 将导出路径填入 config.py：
       SCENARIO1_SAMPLE_TEMPLATE = "<OUTPUT_FOLDER>/training_{year}"
       SCENARIO2_SAMPLE_ASSET    = "<OUTPUT_FOLDER>/training_s2_ref"
"""

import ee

# ============================================================
# ── USER SETTINGS ──  修改这里
# ============================================================

# GEE 项目 ID（与 config.py 中的 GEE_PROJECT 保持一致）
GEE_PROJECT = "dalianlcz"

# 原始训练样本资产路径
SOURCE_ASSET = "projects/dalianlcz/assets/Samples/training"

# 导出目标文件夹（必须已在 GEE Asset Manager 中存在）
OUTPUT_FOLDER = "projects/dalianlcz/assets/Samples"

# 原始数据中年份字段的范围
YEAR_START = 2000
YEAR_END   = 2020

# 原始数据中 LCZ 字段名的格式（字段名即年份数字，如 "2000", "2001", …）
# 如果字段名是纯数字字符串（如 "2000"），保持默认即可。
# 如果字段名有前缀（如 "lcz_2000"），改为 "lcz_{year}"。
YEAR_FIELD_TEMPLATE = "{year}"   # 例: "2000" → 字段名就是年份本身

# 软件包使用的 LCZ 属性字段名（不要修改，与 config.py 中 CLASS_PROPERTY 一致）
LCZ_FIELD = "LCZ"

# Scenario 2 参考年份（通常选择样本质量最好的年份）
S2_REF_YEAR = 2020

# 是否同时导出 Scenario 2 的单年参考样本
EXPORT_S2 = True

# ============================================================
# ── 脚本主体  ──  通常不需要修改
# ============================================================

def main():
    # 初始化 GEE
    ee.Initialize(project=GEE_PROJECT)
    print(f"✅ GEE initialized (project: {GEE_PROJECT})")

    source = ee.FeatureCollection(SOURCE_ASSET)
    years  = list(range(YEAR_START, YEAR_END + 1))

    submitted = 0

    # ── Scenario 1：逐年导出 ──────────────────────────────────
    print(f"\n📦 Exporting {len(years)} per-year sample assets for Scenario 1 …")
    for year in years:
        field_name = YEAR_FIELD_TEMPLATE.format(year=year)

        # 1. 过滤掉该年份 LCZ 值为 0（无效）的点
        valid = source.filter(ee.Filter.neq(field_name, 0))

        # 2. 将年份字段重命名为统一的 "LCZ" 字段，删除其他年份字段
        def remap_feature(feat):
            lcz_val = feat.get(field_name)
            # 只保留几何和 LCZ 字段
            return ee.Feature(feat.geometry()).set(LCZ_FIELD, lcz_val)

        remapped = valid.map(remap_feature)

        # 3. 提交导出任务
        asset_id   = f"{OUTPUT_FOLDER}/training_{year}"
        task = ee.batch.Export.table.toAsset(
            collection  = remapped,
            description = f"training_{year}",
            assetId     = asset_id,
        )
        task.start()
        print(f"  🚀 Submitted: {asset_id}")
        submitted += 1

    # ── Scenario 2：单年参考样本 ─────────────────────────────
    if EXPORT_S2:
        ref_field = YEAR_FIELD_TEMPLATE.format(year=S2_REF_YEAR)
        valid_ref = source.filter(ee.Filter.neq(ref_field, 0))

        def remap_ref(feat):
            lcz_val = feat.get(ref_field)
            return ee.Feature(feat.geometry()).set(LCZ_FIELD, lcz_val)

        remapped_ref = valid_ref.map(remap_ref)

        asset_id_s2 = f"{OUTPUT_FOLDER}/training_s2_ref"
        task_s2 = ee.batch.Export.table.toAsset(
            collection  = remapped_ref,
            description = "training_s2_ref",
            assetId     = asset_id_s2,
        )
        task_s2.start()
        print(f"\n📦 Scenario 2 reference sample submitted: {asset_id_s2}")
        submitted += 1

    print(f"\n✅ Done – {submitted} export task(s) submitted.")
    print("\n── 下一步 ──")
    print("1. 在 GEE Task Manager 中等待所有任务完成。")
    print("2. 在 config.py 中填入以下路径：")
    print(f'   SCENARIO1_SAMPLE_TEMPLATE = "{OUTPUT_FOLDER}/training_{{year}}"')
    if EXPORT_S2:
        print(f'   SCENARIO2_SAMPLE_ASSET    = "{OUTPUT_FOLDER}/training_s2_ref"')


if __name__ == "__main__":
    main()
