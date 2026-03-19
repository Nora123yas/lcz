"""Utility functions for Landsat processing, LST handling and detrending analysis."""
import ee
import utils.config as Config

class AssetManager:
    @staticmethod
    def find_asset(asset_name, asset_type):
        """Return the first existing asset path for the given name and type."""
        if asset_type == "LANDSAT":
            bases = Config.LANDSAT_BASES
        else:
            base = Config.GEE_ASSETS.get(asset_type)
            if not base:
                return None
            bases = [base]

        for b in bases:
            full_path = f"{b.rstrip('/')}/{asset_name}"
            try:
                ee.data.getAssetAcl(full_path)
                return full_path
            except Exception:
                continue
        return None

    @staticmethod
    def get_existing_asset_path(year, city_id):
        # Priority 1: user-defined template (LANDSAT_ASSET_TEMPLATE in config.py)
        template = getattr(Config, "LANDSAT_ASSET_TEMPLATE", None)
        if template:
            path = template.format(year=year, city_id=city_id)
            try:
                ee.data.getAsset(path)
                return path
            except Exception:
                print(f"⚠️ Landsat asset not found at template path: {path}")
                return None

        # Priority 2: legacy search across LANDSAT_BASES
        asset_name = f"landsat_{year}_{city_id}_3yr"
        path = AssetManager.find_asset(asset_name, "LANDSAT")
        if not path:
            print(f"⚠️ 影像 {asset_name} 在任何路径下都未找到")
        return path


class LSTProcessor:
    @staticmethod
    def mask_qa_issues(image, qa_band):
        QA = image.select(qa_band)
        return image.updateMask(
            QA.bitwiseAnd(1 << 2).eq(0).And(QA.bitwiseAnd(1 << 3).eq(0))
        )

    @classmethod
    def get_summer_lst(cls, year, band_type='day'):
        band_map = {
            'day': ('LST_Day_1km', 'QC_Day'),
            'night': ('LST_Night_1km', 'QC_Night')
        }
        value_band, qa_band = band_map[band_type]

        aqua = ee.ImageCollection("MODIS/061/MYD11A2")
        filtered = (aqua.filterDate(f'{year}-06-01', f'{year}-08-31')
                    .map(lambda img: img.updateMask(img.select(value_band).gt(0)))
                    .map(lambda img: cls.mask_qa_issues(img, qa_band)))

        return (filtered.mean()
                .select(value_band)
                .multiply(0.02)
                .subtract(273.15)
                .multiply(100)
                .toInt16()
                .rename(f'LST_{band_type}_{year}'))

    @classmethod
    def create_lst_lcz_composite(cls, city_id, year, band_type, region, sampling_method='stable'):
        suffix = f'_{sampling_method}' if sampling_method and sampling_method != 'stable' else ''
        lcz = ee.Image(f'{Config.GEE_ASSETS["LCZ_FINAL"]}LCZ_{city_id}_{year}{suffix}_integrated').toInt16()
        lst = cls.get_summer_lst(year, band_type)
        return lst.addBands(lcz.rename(f'LCZ_{year}'))

# === analysis/detrend_analyzer.py ===
"""Detrending analysis for LST data"""
import numpy as np
import pandas as pd
import rasterio
from collections import defaultdict


class DetrendAnalyzer:
    def __init__(self, n_years=5):
        self.n_years = n_years

    def analyze_city(self, city_id, file_dict):
        all_years = sorted(file_dict.keys())
        if len(all_years) < 2 * self.n_years + 5:
            raise ValueError(f"Insufficient time series length for city {city_id}")

        results = {}
        pixel_records = defaultdict(dict)
        slopes = {}

        for daynight in ['day', 'night']:
            valid_years = [
                y for y in all_years
                if daynight in file_dict[y] and (
                    isinstance(file_dict[y][daynight], tuple) or 'lcz' in file_dict[y]
                )
            ]
            if len(valid_years) < 2 * self.n_years + 5:
                continue

            # Load data
            lcz_stack, lst_stack = self._load_data_stack(file_dict, valid_years, daynight)

            # Analyze trends
            change_diff, slope = self._analyze_trends(lcz_stack, lst_stack, valid_years)
            slopes[daynight] = slope

            # Store results
            results[daynight] = pd.DataFrame([
                {'change': int(k), f'{daynight}_diff': np.nanmedian(v)}
                for k, v in change_diff.items()
            ])

            # Store pixel-level data
            for change_code, diff_vals in change_diff.items():
                for idx, val in enumerate(diff_vals):
                    if not np.isnan(val):
                        key = (int(change_code), idx)
                        pixel_records[key][f'{daynight}_diff'] = round(val, 2)

        return results, pixel_records, slopes

    def _load_data_stack(self, file_dict, years, daynight):
        lcz_stack, lst_stack = [], []

        for year in years:
            entry = file_dict[year][daynight]
            if isinstance(entry, tuple):
                fname, start = entry
                with rasterio.open(fname) as src:
                    data = src.read([start + 1, start + 2])
                data_3d = np.moveaxis(data, 0, -1)
                lst_stack.append(data_3d[..., 0:1])
                lcz_stack.append(data_3d[..., 1:2])
            else:
                lst_path = entry
                lcz_path = file_dict[year].get('lcz')
                if lcz_path is None:
                    raise KeyError(f"Missing LCZ file for year {year}")
                with rasterio.open(lst_path) as lst_src, rasterio.open(lcz_path) as lcz_src:
                    lst = lst_src.read(1)
                    lcz = lcz_src.read(1)
                lst_stack.append(np.expand_dims(lst, axis=-1))
                lcz_stack.append(np.expand_dims(lcz, axis=-1))

        return np.concatenate(lcz_stack, axis=-1), np.concatenate(lst_stack, axis=-1)

    def _analyze_trends(self, lcz, lst, years):
        n = self.n_years
        year1, year2 = years[n - 1], years[-n]
        idx1, idx2 = years.index(year1), years.index(year2)

        # Calculate change types
        lcz_s, lcz_e = lcz[..., 0], lcz[..., -1]
        lcz1, lcz2 = lcz[..., idx1], lcz[..., idx2]
        change = lcz1 * 100 + lcz2

        # Get urban stable trend
        urban_mask = (lcz_s == lcz_e) & (lcz_s <= 10) & (lcz_s > 0)
        urban_data = lst[urban_mask, :]
        urban_data = urban_data[~np.any(urban_data == -32768, axis=1)]

        if urban_data.shape[0] == 0:
            return {}, None

        urban_median = np.nanmedian(urban_data / 100, axis=0)
        slope, intercept = np.polyfit(years, urban_median, 1)

        # Analyze changes for each transition type
        change_diff = {}
        change_l = change[(lcz2 <= 10) & (lcz1 > 0)]

        for change_code in np.unique(change_l):
            mask = (change == change_code)
            sample = lst[mask, :]
            sample = sample[~np.any(sample == -32768, axis=1)]

            if sample.shape[0] == 0:
                continue

            sample = sample / 100
            residuals = sample - (slope * np.array(years) + intercept)

            avg_before = np.nanmean(residuals[:, np.array(years) < year1], axis=1)
            avg_after = np.nanmean(residuals[:, np.array(years) > year2], axis=1)
            diff = avg_after - avg_before

            change_diff[change_code] = diff

        return change_diff, slope


def calculate_contributions(pixel_df, slopes):
    """Calculate contribution ratios and extra warming from pixel-level diffs."""
    import math

    # Accept pandas DataFrame or list of dicts
    if hasattr(pixel_df, 'to_dict'):
        records = pixel_df.to_dict(orient='records')
    else:
        records = list(pixel_df)

    groups = {}
    for rec in records:
        change = int(rec.get('change'))
        g = groups.setdefault(change, {'day': 0.0, 'night': 0.0})
        if 'day_diff' in rec and rec['day_diff'] is not None and not (isinstance(rec['day_diff'], float) and math.isnan(rec['day_diff'])):
            g['day'] += rec['day_diff']
        if 'night_diff' in rec and rec['night_diff'] is not None and not (isinstance(rec['night_diff'], float) and math.isnan(rec['night_diff'])):
            g['night'] += rec['night_diff']

    day_total = sum(v['day'] for v in groups.values())
    night_total = sum(v['night'] for v in groups.values())

    results = []
    for change, vals in groups.items():
        rec = {'change': change}
        if day_total:
            rec['day_ratio'] = vals['day'] / day_total
            rec['day_extra'] = vals['day'] / (slopes.get('day', 0) * 22) if slopes.get('day') else None
        if night_total:
            rec['night_ratio'] = vals['night'] / night_total
            rec['night_extra'] = vals['night'] / (slopes.get('night', 0) * 22) if slopes.get('night') else None
        results.append(rec)

    return results

