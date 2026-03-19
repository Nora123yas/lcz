import ee
from functools import lru_cache
from utils import config as Config
from utils.processors import AssetManager
from utils import sampling



@lru_cache(maxsize=1)
def _import_from_glc_plus_module():
    """Import the FROM-GLC Plus helper module with broad EE version support."""

    module_id = Config.FROM_GLC_PLUS_MODULE_ID

    importer = getattr(ee, "ImportedModule", None)
    if importer is not None:
        return importer(module_id)

    module_cls = getattr(ee, "Module", None)
    if module_cls is not None and hasattr(module_cls, "import_"):
        return module_cls.import_(module_id)

    script_cls = getattr(ee, "Script", None)
    if script_cls is not None and hasattr(script_cls, "import_"):
        return script_cls.import_(module_id)

    raise AttributeError(
        "The installed earthengine-api package does not support script modules via "
        "ImportedModule, Module.import_, or Script.import_. Upgrade to a newer "
        "version to import "
        f"'{module_id}'."
    )
class LandsatProcessor:
    @staticmethod
    def mask_sr(image):
        qa = image.select('QA_PIXEL')
        mask = qa.bitwiseAnd(int('11111', 2)).eq(0)
        saturation_mask = image.select('QA_RADSAT').eq(0)
        return image.updateMask(mask).updateMask(saturation_mask)

    @staticmethod
    def process_landsat(image, optical_bands, thermal_band):
        scaled_optical = image.select(optical_bands).multiply(0.0000275).add(-0.2)
        scaled_thermal = image.select(thermal_band).multiply(0.00341802).add(149.0)
        return scaled_optical.addBands(scaled_thermal).copyProperties(image, ["system:time_start"])

    @classmethod
    def get_median_composite(cls, year, bound):
        start = ee.Date.fromYMD(year - 1, 1, 1)
        end = ee.Date.fromYMD(year + 1, 12, 31)

        if year <= 2012:
            collection = ee.ImageCollection("LANDSAT/LT05/C02/T1_L2")
            optical_bands = ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7']
            thermal_band = 'ST_B6'
        else:
            collection = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
            optical_bands = ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7']
            thermal_band = 'ST_B10'

        collection = (collection.filterBounds(bound).filterDate(start, end)
                      .map(cls.mask_sr)
                      .map(lambda img: cls.process_landsat(img, optical_bands, thermal_band)))

        return collection.median().clip(bound)

    @classmethod
    def get_median_composite_by_city(cls, year, city_id):
        asset_paths = Config.LANDSAT_BASES
        image_name = f'landsat_{year}_{city_id}_3yr'

        for base in asset_paths:
            full_path = f'{base}/{image_name}'
            try:
                # Use the REST metadata endpoint instead of bandNames().getInfo().
                # ee.data.getAsset() only fetches asset metadata (a tiny JSON
                # object) and never triggers pixel-level computation, so it is
                # safe for large images and does not count against the user
                # memory limit.
                ee.data.getAsset(full_path)
                return ee.Image(full_path).select([0, 1, 2, 3, 4, 5])
            except Exception:
                continue
        raise ValueError(f'找不到影像 {image_name}，请检查 asset 是否存在于指定路径中')

# === processors/change_detector.py ===
"""Change detection using SWIR texture and LandTrendr"""


class ChangeDetector:
    def __init__(
        self,
        input_type=Config.INPUT_TYPE,
        scale=Config.SCALE,
        glcm_size=Config.GLCM_SIZE,
        texture_method=None,
        stable_threshold=None,
        mmu=None,
        mag_threshold=None,
        preval_threshold=None,
        built_up_asset=None,
    ):
        self.input_type = input_type
        self.scale = scale
        self.glcm_size = glcm_size
        self.texture_method = (texture_method or getattr(Config, "TEXTURE_METHOD", "glcm_diss")).lower()
        self.stable_threshold = (
            stable_threshold if stable_threshold is not None else getattr(Config, "TEXTURE_STABLE_THRESHOLD", 1.0)
        )
        self.mmu = mmu if mmu is not None else getattr(Config, "TEXTURE_MMU", 1)
        self.mag_threshold = (
            mag_threshold if mag_threshold is not None else getattr(Config, "TEXTURE_MAG_THRESHOLD", 0.5)
        )
        self.preval_threshold = (
            preval_threshold if preval_threshold is not None else getattr(Config, "TEXTURE_PREVAL_THRESHOLD", -9999)
        )
        self.built_up_asset = built_up_asset or getattr(Config, "BUILTUP_LANDCOVER_ASSET", None)

    def _get_swir_band(self, img, year):
        band = 'SR_B5' if year < 2013 else 'SR_B6'
        return img.select([band], ['swir'])

    def _compute_texture(self, img, year):
        swir = self._get_swir_band(img, year)

        if self.texture_method == 'stddev':
            return swir.reduceNeighborhood(
                reducer=ee.Reducer.stdDev(),
                kernel=ee.Kernel.square(1)
            ).rename('texture')

        if self.texture_method in ['glcm_diss', 'glcm']:
            swir_q = swir.clamp(0, 1).multiply(255).toUint8()
            return swir_q.glcmTexture(size=self.glcm_size).select('swir_diss').rename('texture')

        raise ValueError(f'Unsupported texture method: {self.texture_method}')

    def _get_urban_mask(self, geometry):
        if not self.built_up_asset:
            return ee.Image(1).clip(geometry).selfMask()
        try:
            lc = ee.Image(self.built_up_asset).clip(geometry)
            return lc.eq(8).selfMask()
        except Exception:
            return ee.Image(1).clip(geometry).selfMask()

    def _load_texture_image(self, city_id, year, geometry):
        asset_path = AssetManager.get_existing_asset_path(year, city_id)
        if not asset_path:
            return None
        image = ee.Image(asset_path).clip(geometry)
        return self._compute_texture(image, year).set('year', year)

    def _compute_baseline_stats(self, base_texture, mask, geometry):
        stats = base_texture.updateMask(mask).reduceRegion(
            reducer=ee.Reducer.mean().combine(
                reducer2=ee.Reducer.stdDev(),
                sharedInputs=True
            ),
            geometry=geometry,
            scale=self.scale,
            maxPixels=1e13,
            bestEffort=True
        )
        mean = ee.Number(stats.get('texture_mean'))
        std = ee.Number(stats.get('texture_stdDev'))
        std = ee.Number(ee.Algorithms.If(std.eq(0), 1, std))
        return mean, std

    def _build_raw_series(self, city_id, years, geometry, mean, std):
        images = []
        for year in years:
            texture = self._load_texture_image(city_id, year, geometry)
            if texture is None:
                continue
            z_score = texture.subtract(mean).divide(std).rename('diss')
            z_score = z_score.set('system:time_start', ee.Date.fromYMD(year, 6, 1).millis())
            images.append(z_score)

        if not images:
            raise ValueError(f'No valid texture images found for city {city_id}')

        return ee.ImageCollection.fromImages(images)

    def _build_stable_mask(self, raw_ts, urban_mask, start_year, end_year):
        start_epoch = raw_ts.filter(ee.Filter.calendarRange(start_year, start_year + 2, 'year')).mean()
        end_epoch = raw_ts.filter(ee.Filter.calendarRange(end_year - 2, end_year, 'year')).mean()
        return end_epoch.subtract(start_epoch).abs().lt(self.stable_threshold).And(urban_mask)

    def _normalize_by_stable_area(self, raw_ts, stable_mask, geometry):
        def _normalize(img):
            mean_dict = img.updateMask(stable_mask).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=geometry,
                scale=self.scale,
                maxPixels=1e13,
                bestEffort=True
            )
            bias = ee.Number(ee.Algorithms.If(mean_dict.get('diss'), mean_dict.get('diss'), 0))
            return img.subtract(bias).rename('diss').copyProperties(img, ['system:time_start'])

        return raw_ts.map(_normalize)

    def _apply_morphology(self, collection):
        kernel = ee.Kernel.square(radius=2, units='pixels')

        def _filter(img):
            closed = img.focalMax(kernel=kernel, iterations=1).focalMin(kernel=kernel, iterations=1)
            opened = closed.focalMin(kernel=kernel, iterations=1).focalMax(kernel=kernel, iterations=1)
            return opened.rename('diss').copyProperties(img, ['system:time_start'])

        return collection.map(_filter)

    def run_landtrendr(self, image_collection):
        return ee.Algorithms.TemporalSegmentation.LandTrendr(
            timeSeries=image_collection,
            maxSegments=6,
            spikeThreshold=0.9,
            vertexCountOvershoot=3,
            preventOneYearRecovery=True,
            recoveryThreshold=0.25,
            pvalThreshold=0.05,
            bestModelProportion=0.75,
            minObservationsNeeded=6
        ).select('LandTrendr')

    def extract_year_of_disturbance(self, lt_result, dist_dir=1, mmu=1):
        vertex_mask = lt_result.arraySlice(0, 3, 4)
        vertices = lt_result.arrayMask(vertex_mask)

        left = vertices.arraySlice(1, 0, -1)
        right = vertices.arraySlice(1, 1, None)
        start_year = left.arraySlice(0, 0, 1)
        start_val = left.arraySlice(0, 2, 3)
        end_year = right.arraySlice(0, 0, 1)
        end_val = right.arraySlice(0, 2, 3)

        dur = end_year.subtract(start_year)
        mag = end_val.subtract(start_val)
        preval = start_val.multiply(dist_dir)

        dist_img = ee.Image.cat([start_year.add(1), mag, dur, preval]).toArray(0).arraySort(mag.multiply(-1))
        temp = dist_img.arraySlice(1, 0, 1).unmask(ee.Image(ee.Array([[0], [0], [0], [0]])))

        final = ee.Image.cat(
            temp.arraySlice(0, 0, 1).arrayProject([1]).arrayFlatten([['yod']]),
            temp.arraySlice(0, 1, 2).arrayProject([1]).arrayFlatten([['mag']]),
            temp.arraySlice(0, 2, 3).arrayProject([1]).arrayFlatten([['dur']]),
            temp.arraySlice(0, 3, 4).arrayProject([1]).arrayFlatten([['preval']])
        )

        mask = (final.select('dur').lte(4)
                .And(final.select('mag').gt(self.mag_threshold))
                .And(final.select('preval').gt(self.preval_threshold)))
        result = final.updateMask(mask).int16()

        if mmu > 1:
            patch_mask = result.select('yod').connectedPixelCount(mmu, True).gte(mmu)
            result = result.updateMask(patch_mask)

        return result.select('yod')

    def detect_changes(self, city_id, years, region):
        years = sorted(years)
        start_year, end_year = years[0], years[-1]
        geometry = region.geometry()

        urban_mask = self._get_urban_mask(geometry)
        base_texture = self._load_texture_image(city_id, start_year, geometry)
        if base_texture is None:
            raise ValueError(f"No Landsat image found for {city_id} in {start_year}")

        mean, std = self._compute_baseline_stats(base_texture, urban_mask, geometry)
        raw_ts = self._build_raw_series(city_id, years, geometry, mean, std)
        stable_mask = self._build_stable_mask(raw_ts, urban_mask, start_year, end_year)
        corrected = self._normalize_by_stable_area(raw_ts, stable_mask, geometry)
        filtered = self._apply_morphology(corrected)

        lt_result = self.run_landtrendr(filtered)
        yod = self.extract_year_of_disturbance(lt_result, mmu=self.mmu).clip(region).unmask(0).short()

        # Additional smoothing for cleaner patches
        yod_smoothed = (yod.focalMin(kernel=ee.Kernel.circle(radius=1), iterations=1)
                        .focalMax(kernel=ee.Kernel.circle(radius=2), iterations=1))

        return yod_smoothed


# === processors/classifier.py ===
"""LCZ classification using Random Forest"""
import ee


class LCZClassifier:
    def __init__(self, num_trees=50, samples_per_class=100,
                 sampling_method='stable', asset_path=None, asset_paths=None,
                 class_property='LCZ', train_ratio=None, seed=42,
                 use_alpha_embedding=False):
        self.num_trees = num_trees
        self.samples_per_class = samples_per_class
        self.sampling_method = sampling_method
        self.asset_path = asset_path
        self.asset_paths = asset_paths or {}
        self.class_property = class_property
        self.train_ratio = train_ratio
        self.seed = seed
        self.use_alpha_embedding = use_alpha_embedding

    def _asset_for_year(self, year):
        if self.asset_paths:
            path = self.asset_paths.get(year)
            if not path:
                raise ValueError(f'Missing asset path for year {year}')
            return path
        if self.asset_path:
            return self.asset_path
        raise ValueError('asset_path or asset_paths must be provided for asset sampling')

    def select_bands_by_year(self, img, year):
        if year < 2013:
            return img.select(['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'],
                              ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6'])
        else:
            return img.select(['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'],
                              ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6'])

    def add_spectral_indices(self, image):
        ndvi = image.normalizedDifference(['SR_B4', 'SR_B3']).rename('NDVI')
        ndbi = image.normalizedDifference(['SR_B5', 'SR_B4']).rename('NDBI')
        mndwi = image.normalizedDifference(['SR_B2', 'SR_B5']).rename('MNDWI')
        return image.addBands([ndvi, ndbi, mndwi])

    def add_alpha_embedding(self, image, year):
        """Append the AlphaEarth embedding band when available.

        The dataset is optional and safely skipped when the configured
        collection is missing or does not contain the requested year.
        """

        if not self.use_alpha_embedding:
            return image

        collection_id = getattr(Config, "ALPHA_EARTH_COLLECTION", None)
        if not collection_id:
            return image

        try:
            start = ee.Date.fromYMD(int(year), 1, 1)
            end = ee.Date.fromYMD(int(year) + 1, 1, 1)
            emb = ee.ImageCollection(collection_id).filterDate(start, end).median()
            band_names = emb.bandNames()

            renamed = emb.rename(
                band_names.map(lambda b: ee.String("EMB_").cat(ee.String(b)))
            )
            return image.addBands(renamed)
        except Exception:
            # Gracefully ignore embedding errors and fall back to spectral-only
            return image

    def add_texture_features(self, image):
        glcm = image.select('SR_B5').multiply(1000).toInt().glcmTexture(size=3)
        return image.addBands(glcm.select('SR_B5_diss').rename('GLCM_S1'))

    def get_training_samples(self, city_id, year, region, region_fc=None, other_ids=None):
        """Return training samples according to the specified sampling method."""
        method = self.sampling_method
        if method == 'stable':
            fc = sampling.get_stable_samples(city_id, year, region,
                                             num_points=self.samples_per_class,
                                             seed=self.seed)
        elif method == 'target':
            fc = sampling.get_target_year_samples(city_id, year, region,
                                                  num_points=self.samples_per_class,
                                                  seed=self.seed)
        elif method == 'cross':
            if region_fc is None or other_ids is None:
                raise ValueError('region_fc and other_ids are required for cross sampling')
            fc = sampling.get_cross_city_samples(city_id, year, region_fc, other_ids,
                                                 num_points=self.samples_per_class,
                                                 seed=self.seed)
        elif method == 'asset':
            path = self._asset_for_year(year)
            fc = ee.FeatureCollection(path)
            fc = fc.map(lambda f: f.set('LCZ', f.get(self.class_property)))
        else:
            raise ValueError(f'Unknown sampling method: {method}')

        if self.train_ratio is not None:
            return sampling.split_feature_collection(fc, self.train_ratio, seed=self.seed)
        return fc

    def get_stable_samples(self, city_id, region):
        change_mask = ee.Image(f"{Config.GEE_ASSETS['LCZ_YOD']}YOD_{city_id}_open")
        stable_mask = change_mask.eq(0)
        stable_lcz = Config.LCZ_IMAGE.updateMask(stable_mask)

        samples = stable_lcz.stratifiedSample(
            numPoints=self.samples_per_class,
            classBand='b1',
            region=region.geometry(),
            scale=100,
            seed=42,
            geometries=True
        )

        return samples.map(lambda f: f.set('LCZ', f.get('b1')))

    def get_target_year_samples(city_id, year, region, num_points=100, scale=30):
        """从稳定区域采样（避免 YOD 年份 >= 当前年）"""
        yod = ee.Image(f"{Config.GEE_ASSETS['LCZ_YOD']}YOD_{city_id}_open")
        classified = ee.Image(f"{Config.GEE_ASSETS['LCZ_CLASSIFICATION']}LCZ_{city_id}_{year}")
        stable_mask = yod.lte(year - 1)
        sample_img = classified.updateMask(stable_mask)

        return sample_img.stratifiedSample(
            numPoints=num_points,
            classBand='b1',
            region=region.geometry(),
            scale=scale,
            seed=42,
            geometries=True
        )

    def classify_image(self, city_id, year, region, region_fc=None, other_ids=None,
                       samples_override=None):
        # Load and preprocess image
        asset_path = AssetManager.get_existing_asset_path(year, city_id)
        if not asset_path:
            raise ValueError(f"No Landsat image found for {city_id}, {year}")

        image = ee.Image(asset_path)
        image = self.select_bands_by_year(image, year).float()
        image = self.add_spectral_indices(image)
        image = self.add_texture_features(image)
        image = self.add_alpha_embedding(image, year)

        # Get training (and optionally validation) samples
        if samples_override is not None:
            samples = samples_override
        else:
            samples = self.get_training_samples(city_id, year, region, region_fc, other_ids)

        if isinstance(samples, tuple):
            train_samples, val_samples = samples
        else:
            train_samples, val_samples = samples, None

        training = image.sampleRegions(
            collection=train_samples,
            properties=['LCZ'],
            scale=100,
            tileScale=4
        )

        # Train classifier
        # Base Landsat bands are fixed; EMB_ bands are added server-side
        # using bandNames() without .getInfo() to avoid a client round-trip.
        base_bands = ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6',
                      'NDVI', 'NDBI', 'MNDWI', 'GLCM_S1']
        if self.use_alpha_embedding:
            # Filter band names server-side: keep only those starting with 'EMB_'
            all_bands = image.bandNames()
            emb_bands = all_bands.filter(
                ee.Filter.stringStartsWith('item', 'EMB_')
            )
            # Merge base + EMB bands as a server-side ee.List
            feature_bands = ee.List(base_bands).cat(emb_bands)
        else:
            feature_bands = ee.List(base_bands)
        classifier = ee.Classifier.smileRandomForest(self.num_trees).train(
            features=training,
            classProperty='LCZ',
            inputProperties=feature_bands
        )

        # Classify and smooth
        classified = image.classify(classifier).clip(region.geometry())

        oa = None
        if val_samples is not None:
            validated = image.sampleRegions(
                collection=val_samples,
                properties=['LCZ'],
                scale=100,
                tileScale=4
            )
            cm = validated.classify(classifier).errorMatrix('LCZ', 'classification')
            oa = cm.accuracy().getInfo()

        classified = classified.focal_mode(1, 'square', 'pixels', 3)
        return classified, oa

    def evaluate_sampling_strategies(city_id, year, region_fc, all_city_ids):
        """测试不同采样方法的分类精度差异"""
        import geemap
        from geemap import ee_export_vector

        region = region_fc.filter(ee.Filter.eq('id', city_id)).first()

        # 样本获取
        stable = get_stable_samples(city_id, year, region)
        target = get_target_year_samples(city_id, year, region)
        cross = get_cross_city_samples(city_id, year, region_fc, all_city_ids)

        # 分类器评估
        image = ee.Image(f"{Config.GEE_ASSETS['LCZ_CLASSIFICATION']}LCZ_{city_id}_{year}")

        for name, samples in zip(['stable', 'target', 'cross'], [stable, target, cross]):
            print(f"\n\u2728 正在评估采样方法: {name}")
            trained = ee.Classifier.smileRandomForest(numberOfTrees=50).train(
                features=samples,
                classProperty='b1',
                inputProperties=image.bandNames()
            )

            validated = image.classify(trained).sampleRegions(
                collection=samples,
                properties=['b1'],
                scale=30
            )

            # 精度矩阵
            print(ee.ConfusionMatrix(validated.errorMatrix('b1', 'classification')).getInfo())

# === processors/aggregator.py ===
"""Temporal aggregation and consistency correction"""
import ee


class TemporalAggregator:
    LANDCOVER_REMAP_FROM = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    LANDCOVER_REMAP_TO = [14, 11, 14, 14, 17, 17, 14, 8, 16, 17]

    @staticmethod
    def get_lcz_series(city_id, years, sampling_method='stable', use_temp_smooth=False):
        """Load yearly LCZ images as an ImageCollection.

        When ``use_temp_smooth`` is ``True``, images are loaded from
        ``LCZ_TEMP_SMOOTH`` with the same sampling suffix and an additional
        ``_smooth`` marker. Otherwise, yearly classification results are loaded
        from ``LCZ_CLASSIFICATION`` and the optional ``sampling_method`` suffix
        is appended to the asset name.
        """

        suffix = f"_{sampling_method}" if sampling_method and sampling_method != 'stable' else ""
        images = []
        for year in years:
            if use_temp_smooth:
                asset_name = f"LCZ_{city_id}_{year}{suffix}_smooth"
                asset_type = "LCZ_TEMP_SMOOTH"
            else:
                asset_name = f"LCZ_{city_id}_{year}{suffix}"
                asset_type = "LCZ_CLASSIFICATION"

            path = AssetManager.find_asset(asset_name, asset_type)
            if not path:
                raise ValueError(f"找不到分类 {asset_name}")

            img = ee.Image(path).rename(f"LCZ_{year}").set('year', year)
            images.append(img)

        return ee.ImageCollection.fromImages(images)

    @classmethod
    def _load_landcover_from_glc_plus(cls, year, geometry):
        geometry = ee.Geometry(geometry)
        year_int = int(year)

        asset_root = getattr(Config, "FROM_GLC_PLUS_ASSET_ROOT", None)
        if asset_root:
            asset_id = f"{asset_root}/plus_{year_int}"
            landcover = ee.Image(asset_id)
        else:
            module = _import_from_glc_plus_module()
            loader = (
                getattr(module, "get_landcover_image", None)
                or getattr(module, "getLandcoverImage", None)
                or getattr(module, "getLandCoverImage", None)
            )
            if loader is None:
                raise AttributeError(
                    "FROM_GLC_PLUS_ASSET_ROOT 未配置，且外部 FROM-GLC Plus 模块不提供"
                    " get_landcover_image 接口。"
                )
            landcover = ee.Image(loader(year_int))
        remapped = landcover.remap(
            cls.LANDCOVER_REMAP_FROM,
            cls.LANDCOVER_REMAP_TO,
            0
        )
        smoothed = remapped.focal_mode(1, 'square', 'pixels', 3)
        return smoothed.clip(geometry)

    @classmethod
    def get_landcover_series(
        cls,
        geometry,
        years,
        band_prefix="LANDCOVER",
    ):
        """Load remapped FROM-GLC Plus land-cover images for each year.

        Parameters
        ----------
        geometry: GeoJSON-like or ``ee.Geometry``
            Region to clip the land-cover images to.
        years: Iterable[int]
            Sequence of years to load.
        band_prefix: str, optional
            Prefix used when renaming the yearly band. Defaults to
            ``"LANDCOVER"``.

        Returns
        -------
        ee.ImageCollection
            Collection where each image contains a single band representing the
            remapped FROM-GLC Plus land-cover classes for the requested year.
        """

        geometry = ee.Geometry(geometry)
        images = []

        for year in years:
            base = cls._load_landcover_from_glc_plus(year, geometry)
            band_name = f"{band_prefix}_{year}" if band_prefix else str(year)
            remapped = base.rename(band_name)
            band_type = ee.Dictionary(remapped.bandTypes()).get(band_name)
            time_start = ee.Date.fromYMD(year, 1, 1).millis()

            images.append(
                remapped.cast({band_name: band_type})
                .set("year", year)
                .set("system:time_start", time_start)
            )

        return ee.ImageCollection.fromImages(images)

    @classmethod
    def replace_with_landcover(cls, lcz_collection, geometry, years):
        """Replace LCZ bands with remapped FROM-GLC Plus land-cover classes."""

        geometry = ee.Geometry(geometry)
        fused_images = []

        for year in years:
            band_name = f"LCZ_{year}"
            fused = cls._load_landcover_from_glc_plus(year, geometry).rename(band_name)
            band_type = ee.Dictionary(fused.bandTypes()).get(band_name)
            default_time = ee.Date.fromYMD(year, 1, 1).millis()
            original = lcz_collection.filter(ee.Filter.eq('year', year)).first()
            original_band = ee.Image(
                ee.Algorithms.If(
                    original,
                    ee.Image(original).select(band_name),
                    fused,
                )
            ).cast({band_name: band_type})
            fused = fused.where(fused.eq(8), original_band)
            fused = fused.cast({band_name: band_type})
            time_start = ee.Algorithms.If(
                original,
                ee.Algorithms.If(
                    ee.Image(original).get('system:time_start'),
                    ee.Image(original).get('system:time_start'),
                    default_time,
                ),
                default_time,
            )

            fused_images.append(
                fused
                .set('year', year)
                .set('system:time_start', time_start)
            )

        return ee.ImageCollection.fromImages(fused_images)

    @staticmethod
    def stack_images(image_collection):
        band_names = image_collection.aggregate_array('year').map(
            lambda y: ee.String('LCZ_').cat(ee.Number(y).format())
        )
        return image_collection.toBands().rename(band_names)

    @staticmethod
    def temporal_smoothing(collection, interval=1, rounds=1):
        """Apply temporal smoothing to an ImageCollection of LCZ images."""

        def _to_lcz(img):
            b = ee.String(img.bandNames().get(0))
            return img.select(b).rename('lcz')

        coll = collection.map(lambda img: _to_lcz(img))

        def _smoothing_once(coll, interval):
            join = ee.Join.saveAll('images')
            filt = ee.Filter.maxDifference(
                difference=interval,
                leftField='year',
                rightField='year'
            )
            joined = join.apply(coll, coll, filt)

            def _map(f):
                f = ee.Feature(f)
                year = ee.Number(f.get('year'))
                images = ee.List(f.get('images'))
                group = ee.ImageCollection.fromImages(images)
                current = group.filter(ee.Filter.eq('year', year)).first()
                distinct = group.reduce(ee.Reducer.countDistinct())
                mode = group.mode()
                mode = mode.where(distinct.eq(3), current)
                mode = mode.where(distinct.eq(4), current)
                mode = mode.where(distinct.eq(5), current)
                return (mode
                        .set('year', year)
                        .set('system:time_start', f.get('system:time_start'))
                        .rename('lcz'))

            return ee.ImageCollection(joined.map(_map)).sort('year')

        smoothed = coll
        for _ in range(rounds):
            smoothed = _smoothing_once(smoothed, interval)
        return smoothed

    @staticmethod
    def correct_temporal_consistency(img, years):
        """Apply temporal consistency rules using backward search."""

        rules_dict = {
            "1":  [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17],
            "2":  [2,3,5,6,7,8,9,10,11,12,13,14,15,16,17],
            "3":  [3,6,7,8,9,10,11,12,13,14,15,16,17],
            "4":  [2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17],
            "5":  [3,5,6,7,8,9,10,11,12,13,14,15,16,17],
            "6":  [6,7,8,9,10,11,12,13,14,15,16,17],
            "7":  [7,11,12,13,14,16,17],
            "8":  [7,8,9,13,14,15,16,17],
            "9":  [9,13,14,15,16,17],
            "10": [7,8,9,10,11,12,13,14,15,16,17],
            "11": [3,6,11,12,13,14,16,17],
            "12": [3,6,11,12,13,14,16,17],
            "13": [3,6,11,12,13,14,16,17],
            "14": [3,6,11,12,13,14,16,17],
            "15": [3,6,7,8,9,10,11,12,13,14,15,16,17],
            "16": [3,6,7,11,12,13,14,16,17],
            "17": [3,6,7,8,9,10,11,12,13,14,16,17]
        }

        all_lcz = ee.List.sequence(1, 17)
        year_list = list(years)

        # Start from the last year
        result = img.select(f'LCZ_{year_list[-1]}').rename(f'LCZ_{year_list[-1]}')

        for i in range(len(year_list) - 2, -1, -1):
            curr_year = year_list[i]
            next_year = year_list[i + 1]
            curr = img.select(f'LCZ_{curr_year}')
            next_band = result.select(f'LCZ_{next_year}')

            mask = ee.Image(0).rename('mask')
            for tgt in range(1, 18):
                allowed = ee.List(rules_dict[str(tgt)])
                allow_remap = all_lcz.map(lambda x: ee.Algorithms.If(allowed.contains(x), 1, 0))
                condition = next_band.eq(tgt).And(curr.remap(all_lcz, allow_remap).eq(0))
                mask = mask.where(condition, 1)

            corrected = curr.where(mask.eq(1), next_band).rename(f'LCZ_{curr_year}')
            result = corrected.addBands(result)

        return result

    @staticmethod
    def integrate_with_change_detection(corrected_img, yod_img, years, landcover_img=None):
        """Integrate corrected LCZ with change detection results.

        Parameters
        ----------
        corrected_img : ee.Image
            Image containing temporally corrected LCZ bands for each year.
        yod_img : ee.Image
            Year-of-disturbance image used to determine which year's LCZ class
            should be adopted at each pixel.
        years : Sequence[int]
            List of years corresponding to the LCZ bands in ``corrected_img``.
        landcover_img : ee.Image, optional
            Stacked FROM-GLC Plus land-cover image with bands named ``LCZ_{year}``.
            When provided, built-up extents (``LCZ`` ≤ 10) are taken from the
            land-cover product and only the within-city classes are updated using
            the YOD information.

        Returns
        -------
        Dict[int, ee.Image]
            Mapping from year to the integrated LCZ image for that year. The
            images are renamed to ``LCZ_integrated_{year}``.
        """

        year_list = list(years)
        latest_year = year_list[-1]
        base = corrected_img.select(f'LCZ_{latest_year}')

        landcover_stack = landcover_img
        integrated = {}

        for index in range(len(year_list) - 1, -1, -1):
            year = year_list[index]

            if landcover_stack is not None:
                landcover_band = landcover_stack.select(f'LCZ_{year}')
                city_mask = landcover_band.lte(10)
                final = landcover_band.where(city_mask, base)
            else:
                final = base

            integrated[year] = final.rename(f'LCZ_integrated_{year}')

            if index == 0:
                break

            prev_year = year_list[index - 1]
            yod_mask = yod_img.eq(prev_year)
            if landcover_stack is not None:
                prev_mask = landcover_stack.select(f'LCZ_{prev_year}').lte(10)
                yod_mask = yod_mask.And(prev_mask)
            lcz_prev = corrected_img.select(f'LCZ_{prev_year}')
            base = base.where(yod_mask, lcz_prev)

        return integrated


# ---------------------------------------------------------------------------
# Backward-compatible re-export
# ---------------------------------------------------------------------------
# LCZTimeSeriesScenarios was previously defined in this file.  It has been
# moved to utils.time_series_scenarios for clarity.  The import below keeps
# any existing code that imports it from geemodules working without changes.
from utils.time_series_scenarios import LCZTimeSeriesScenarios  # noqa: E402, F401
