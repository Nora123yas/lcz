# utils/geemodules_sampling.py
import ee
import random
import os
import csv
import pandas as pd
import matplotlib.pyplot as plt
from utils import config as Config


def split_feature_collection(fc, train_ratio=0.7, seed=0):
    """Split a FeatureCollection into train and validation sets."""
    fc_random = fc.randomColumn('rand', seed)
    train_fc = fc_random.filter(ee.Filter.lt('rand', train_ratio))
    val_fc = fc_random.filter(ee.Filter.gte('rand', train_ratio))
    return train_fc, val_fc

def get_stable_samples(city_id, year, region, num_points=100, scale=100, seed=42):
    """从稳定区域采样（避免 YOD 年份 >= 当前年）"""
    yod = ee.Image(f"{Config.GEE_ASSETS['LCZ_YOD']}YOD_{city_id}_open")
    #classified = ee.Image(f'projects/chinalcz/assets/worldlcz_classification/LCZ_{city_id}_{year}').rename('LCZ')
    classified = ee.Image('projects/globallcz/assets/lcz_filter_v1').rename('LCZ')
    stable_mask = yod.lte(year - 1)
    sample_img = classified.updateMask(stable_mask)

    return sample_img.stratifiedSample(
        numPoints=num_points,
        classBand='LCZ',
        region=region.geometry(),
        scale=scale,
        seed=seed,
        geometries=True
    )

def get_target_year_samples(city_id, year, region, num_points=100, scale=100, seed=24):
    """从目标年份影像中采样，使用 YOD 掩膜去除当年变化像元"""
    yod = ee.Image(f"{Config.GEE_ASSETS['LCZ_YOD']}YOD_{city_id}_open")
    classified = ee.Image('projects/globallcz/assets/lcz_filter_v1').rename('LCZ')
    stable_mask = yod.lt(year)
    sample_img = classified.updateMask(stable_mask)

    return sample_img.stratifiedSample(
        numPoints=num_points,
        classBand='LCZ',
        region=region.geometry(),
        scale=scale,
        seed=seed,
        geometries=True
    )

def get_cross_city_samples(target_city_id, year, region_fc, other_ids, num_points=100, scale=30, seed=56):
    fc_list = []
    for city_id in [target_city_id] + other_ids:
        region = region_fc.filter(ee.Filter.eq('id', city_id)).first()
        if region is None:
            continue
        yod = ee.Image(f"{Config.GEE_ASSETS['LCZ_YOD']}YOD_{city_id}_open")
        classified = ee.Image('projects/globallcz/assets/lcz_filter_v1').rename('LCZ')
        stable_mask = yod.neq(year)
        sample_img = classified.updateMask(stable_mask)

        samples = sample_img.stratifiedSample(
            numPoints=num_points,
            classBand='LCZ',
            region=region.geometry(),
            scale=scale,
            seed=seed,
            geometries=True
        )
        fc_list.append(samples)

    return ee.FeatureCollection(fc_list).flatten()

def evaluate_sampling_strategies(city_id, year, region_fc, other_ids, num_points=200, validation_fc_path=None, methods=['stable', 'target', 'cross'], seed_offset=0):
    from utils.geemodules import LandsatProcessor
    region = region_fc.filter(ee.Filter.eq('id', city_id)).first()

    image = LandsatProcessor.get_median_composite_by_city(year, city_id).rename(['B1', 'B2', 'B3', 'B4', 'B5', 'B6'])

    method_map = {
        'stable': get_stable_samples(city_id, year, region, num_points=num_points, seed=42 + seed_offset),
        'target': get_target_year_samples(city_id, year, region, num_points=num_points, seed=24 + seed_offset),
        'cross': get_cross_city_samples(city_id, year, region_fc, other_ids, num_points=num_points,seed=56 + seed_offset)
    }

    accuracy_results = {}

    for name in methods:
        raw_samples = method_map[name]
        print(f"\n✨ 正在评估采样方法: {name} | 样本数: {num_points} per class | 随机种子: {seed_offset}")

        samples = image.sampleRegions(
            collection=raw_samples,
            properties=['LCZ'],
            scale=100,
            geometries=True
        )

        trained = ee.Classifier.smileRandomForest(numberOfTrees=50).train(
            features=samples,
            classProperty='LCZ',
            inputProperties=image.bandNames()
        )

        if validation_fc_path:
            validation_fc = ee.FeatureCollection(validation_fc_path)
            validated = image.sampleRegions(
                collection=validation_fc,
                properties=['Class'],
                scale=100
            )
            cm = validated.classify(trained).errorMatrix('Class', 'classification')
            oa = cm.accuracy().getInfo()
        else:
            print('no validation samples available')
            oa = 0

        print(f"Overall Accuracy ({name}):", oa)
        accuracy_results[name] = oa

    return accuracy_results
'''
def sample_size_sensitivity_test(city_id, year, region_fc, all_city_ids, sizes=[50, 100, 200, 500], validation_fc_path=None, methods=['stable', 'target', 'cross']):
    all_results = {m: [] for m in methods}

    for n in sizes:
        print(f"\n========================\n📊 测试样本量: {n} / 类别")
        result = evaluate_sampling_strategies(
            city_id,
            year,
            region_fc,
            all_city_ids,
            num_points=n,
            validation_fc_path=validation_fc_path,
            methods=methods
        )
        for method in all_results:
            all_results[method].append(result.get(method, 0))

    plt.figure(figsize=(10, 6))
    for method, scores in all_results.items():
        plt.plot(sizes, scores, marker='o', label=method)

    plt.title(f'LCZ Accuracy change as sample sizes increase {city_id}')
    plt.xlabel("Sample size")
    plt.ylabel("Overall Accuracy")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()
'''
'''
def sample_size_sensitivity_test(city_id, year, region_fc, other_ids, sizes=[50, 100, 200, 500], validation_fc_path=None, methods=['stable', 'target', 'cross'], repetitions=5, output_csv=None):
    if output_csv is None:
        output_csv = f'sampling_accuracy_results_{city_id}.csv'
    all_results = []

    for n in sizes:
        for rep in range(repetitions):
            print(f"\n========================\n📊 测试样本量: {n} / 类别 | 重复次数: {rep + 1}/{repetitions}")
            result = evaluate_sampling_strategies(
                city_id, year, region_fc, other_ids,
                num_points=n,
                validation_fc_path=validation_fc_path,
                methods=methods,
                seed_offset=rep * 10
            )
            for method in methods:
                all_results.append({
                    'method': method,
                    'num_points': n,
                    'repetition': rep + 1,
                    'accuracy': result.get(method, 0)
                })

    # 写入 CSV 文件
    keys = ['method', 'num_points', 'repetition', 'accuracy']
    with open(output_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(all_results)

    # 可视化平均结果
    import pandas as pd
    df = pd.DataFrame(all_results)
    avg_results = df.groupby(['method', 'num_points'])['accuracy'].mean().unstack(0)

    avg_results.plot(marker='o', figsize=(10, 6), title=f"LCZ accuracy_{city_id}")
    plt.xlabel("Sample size")
    plt.ylabel("Overall Accuracy")
    plt.grid(True)
    plt.tight_layout()
    plt.show()
'''


def sample_size_sensitivity_test(city_id, year, region_fc, other_ids, sizes=[50, 100, 200, 500],
                                 validation_fc_path=None, methods=['stable', 'target', 'cross'], repetitions=5,
                                 output_csv=None):
    if output_csv is None:
        output_csv = f'lcz_sampling_accuracy_{city_id}.csv'

    # 自动创建保存目录（如果指定了路径）
    output_dir = os.path.dirname(output_csv)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    all_results = []

    for n in sizes:
        for rep in range(repetitions):
            print(f"\n========================\n📊 测试样本量: {n} / 类别 | 重复次数: {rep + 1}/{repetitions}")
            result = evaluate_sampling_strategies(
                city_id, year, region_fc, other_ids,
                num_points=n,
                validation_fc_path=validation_fc_path,
                methods=methods,
                seed_offset=rep * 10
            )
            for method in methods:
                all_results.append({
                    'method': method,
                    'num_points': n,
                    'repetition': rep + 1,
                    'accuracy': result.get(method, 0)
                })

    # 写入 CSV 文件
    keys = ['method', 'num_points', 'repetition', 'accuracy']
    with open(output_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(all_results)

    # 可视化平均结果 + 标准误差棒
    df = pd.DataFrame(all_results)
    avg = df.groupby(['method', 'num_points'])['accuracy'].mean().unstack(0)
    std_err = df.groupby(['method', 'num_points'])['accuracy'].sem().unstack(0)  # 标准误差

    ax = avg.plot(yerr=std_err, kind='line', marker='o', figsize=(10, 6), capsize=5, title=f"LCZ accuracy_{city_id}")
    ax.set_xlabel("Sample size")
    ax.set_ylabel("Overall Accuracy")
    ax.grid(True)
    plt.tight_layout()
    plt.show()
