import importlib
import sys
import types
import unittest
from unittest import mock

if 'ee' not in sys.modules:
    sys.modules['ee'] = types.ModuleType('ee')
if 'numpy' not in sys.modules:
    sys.modules['numpy'] = types.ModuleType('numpy')
if 'pandas' not in sys.modules:
    sys.modules['pandas'] = types.ModuleType('pandas')
if 'rasterio' not in sys.modules:
    sys.modules['rasterio'] = types.ModuleType('rasterio')
if 'matplotlib' not in sys.modules:
    matplotlib_module = types.ModuleType('matplotlib')
    matplotlib_module.pyplot = types.ModuleType('matplotlib.pyplot')
    sys.modules['matplotlib'] = matplotlib_module
    sys.modules['matplotlib.pyplot'] = matplotlib_module.pyplot

from utils import config as Config


class TestImportFromGlcPlusModule(unittest.TestCase):
    def setUp(self):
        sys.modules.pop('utils.geemodules', None)
        sys.modules['ee'] = types.ModuleType('ee')

    def tearDown(self):
        sys.modules.pop('utils.geemodules', None)
        sys.modules['ee'] = types.ModuleType('ee')

    def _import_with_ee(self, **ee_attrs):
        ee_module = types.ModuleType('ee')
        for name, value in ee_attrs.items():
            setattr(ee_module, name, value)
        sys.modules['ee'] = ee_module
        sys.modules.pop('utils.geemodules', None)
        return importlib.import_module('utils.geemodules')

    def test_uses_imported_module_when_available(self):
        def fake_imported_module(module_id):
            return ('ImportedModule', module_id)

        geemodules = self._import_with_ee(ImportedModule=fake_imported_module)
        module = geemodules._import_from_glc_plus_module()
        self.assertEqual(
            module,
            ('ImportedModule', Config.FROM_GLC_PLUS_MODULE_ID)
        )

    def test_uses_module_import_when_available(self):
        class DummyModule:
            @staticmethod
            def import_(module_id):
                return ('Module.import_', module_id)

        geemodules = self._import_with_ee(Module=DummyModule)
        module = geemodules._import_from_glc_plus_module()
        self.assertEqual(
            module,
            ('Module.import_', Config.FROM_GLC_PLUS_MODULE_ID)
        )

    def test_uses_script_import_when_available(self):
        class DummyScript:
            @staticmethod
            def import_(module_id):
                return ('Script.import_', module_id)

        geemodules = self._import_with_ee(Script=DummyScript)
        module = geemodules._import_from_glc_plus_module()
        self.assertEqual(
            module,
            ('Script.import_', Config.FROM_GLC_PLUS_MODULE_ID)
        )

    def test_raises_attribute_error_when_no_import_mechanism(self):
        geemodules = self._import_with_ee()
        with self.assertRaisesRegex(
            AttributeError,
            r"ImportedModule, Module\.import_, or Script\.import_"
        ):
            geemodules._import_from_glc_plus_module()


class TestLoadLandcoverFromGlcPlus(unittest.TestCase):
    def setUp(self):
        sys.modules.pop('utils.geemodules', None)

        self.fake_image_calls = []

        class FakeImage:
            def __init__(self, asset_id=None):
                self.asset_id = asset_id

            def remap(self, *args, **kwargs):
                return self

            def clip(self, geometry):
                return ('clip', self.asset_id, geometry)

        def fake_image(asset_id=None):
            self.fake_image_calls.append(asset_id)
            return FakeImage(asset_id)

        ee_module = types.ModuleType('ee')
        ee_module.Geometry = lambda geom: ('geometry', geom)
        ee_module.Image = fake_image
        sys.modules['ee'] = ee_module

        self.geemodules = importlib.import_module('utils.geemodules')
        self.geemodules.Config.FROM_GLC_PLUS_ASSET_ROOT = (
            'projects/globallcz/assets/fromglc_plus'
        )

    def tearDown(self):
        sys.modules.pop('utils.geemodules', None)
        sys.modules['ee'] = types.ModuleType('ee')

    def test_loads_asset_without_script_module(self):
        geometry = {'type': 'Polygon'}
        with mock.patch('utils.geemodules._import_from_glc_plus_module') as import_mock:
            result = self.geemodules.TemporalAggregator._load_landcover_from_glc_plus(
                2020, geometry
            )

        expected_asset = 'projects/globallcz/assets/fromglc_plus/plus_2020'
        self.assertEqual(self.fake_image_calls, [expected_asset])
        self.assertEqual(
            result,
            ('clip', expected_asset, ('geometry', geometry))
        )
        import_mock.assert_not_called()


class TestReplaceWithLandcover(unittest.TestCase):
    class FakeImage:
        def __init__(self, data, band_name='LCZ', band_type='int16', properties=None):
            self.data = dict(data)
            self.band_name = band_name
            self.type = band_type
            self.properties = dict(properties or {})

        def clone(self):
            return TestReplaceWithLandcover.FakeImage(
                self.data,
                self.band_name,
                self.type,
                self.properties,
            )

        def rename(self, band_name):
            clone = self.clone()
            clone.band_name = band_name
            return clone

        def bandTypes(self):
            return {self.band_name: self.type}

        def select(self, band_name):
            if isinstance(band_name, (list, tuple)):
                band_name = band_name[0]
            clone = self.clone()
            clone.band_name = band_name
            return clone

        def eq(self, value):
            mask_data = {key: val == value for key, val in self.data.items()}
            mask = self.clone()
            mask.data = mask_data
            mask.type = 'bool'
            return mask

        def where(self, mask, other):
            replaced = self.clone()
            for key, val in self.data.items():
                if mask.data.get(key):
                    replaced.data[key] = other.data.get(key, val)
            return replaced

        def cast(self, band_types):
            clone = self.clone()
            if self.band_name in band_types:
                clone.type = band_types[self.band_name]
            return clone

        def set(self, key, value):
            clone = self.clone()
            clone.properties[key] = value
            return clone

        def get(self, key):
            return self.properties.get(key)

    class FakeCollection:
        def __init__(self, images):
            self.images = list(images)

        def filter(self, condition):
            if isinstance(condition, tuple) and len(condition) == 3 and condition[0] == 'eq':
                field, value = condition[1], condition[2]
                filtered = [img for img in self.images if img.get(field) == value]
                return TestReplaceWithLandcover.FakeCollection(filtered)
            return self

        def first(self):
            return self.images[0] if self.images else None

    class FakeDictionary:
        def __init__(self, mapping):
            self.mapping = dict(mapping)

        def get(self, key):
            return self.mapping[key]

    class FakeDate:
        def __init__(self, millis_value):
            self._millis_value = millis_value

        def millis(self):
            return self._millis_value

    @staticmethod
    def fake_from_ymd(year, month, day):
        return TestReplaceWithLandcover.FakeDate(year * 10000 + month * 100 + day)

    def setUp(self):
        sys.modules.pop('utils.geemodules', None)

        ee_module = types.ModuleType('ee')
        ee_module.Image = lambda img=None: img
        ee_module.ImageCollection = types.SimpleNamespace(
            fromImages=lambda images: TestReplaceWithLandcover.FakeCollection(images)
        )
        ee_module.Filter = types.SimpleNamespace(eq=lambda field, value: ('eq', field, value))
        ee_module.Algorithms = types.SimpleNamespace(
            If=lambda condition, true_case, false_case: true_case if condition else false_case
        )
        ee_module.Date = types.SimpleNamespace(fromYMD=self.fake_from_ymd)
        ee_module.Dictionary = lambda mapping: TestReplaceWithLandcover.FakeDictionary(mapping)
        ee_module.Geometry = lambda geom: geom

        sys.modules['ee'] = ee_module

    def tearDown(self):
        sys.modules.pop('utils.geemodules', None)
        sys.modules['ee'] = types.ModuleType('ee')

    def test_injects_lcz_for_landcover_class_eight(self):
        geemodules = importlib.import_module('utils.geemodules')

        year = 2020
        band_name = f'LCZ_{year}'
        original = self.FakeImage({'a': 1, 'b': 7, 'c': 9}, band_name).set('year', year).set(
            'system:time_start', 123456
        )
        lcz_collection = self.FakeCollection([original])

        remapped = self.FakeImage({'a': 5, 'b': 8, 'c': 8}, band_name)

        with mock.patch.object(
            geemodules.TemporalAggregator,
            '_load_landcover_from_glc_plus',
            return_value=remapped,
        ):
            result = geemodules.TemporalAggregator.replace_with_landcover(
                lcz_collection,
                geometry={'type': 'Polygon'},
                years=[year],
            )

        self.assertIsInstance(result, self.FakeCollection)
        fused_image = result.images[0]

        self.assertEqual(
            fused_image.data,
            {'a': 5, 'b': 7, 'c': 9},
        )
        self.assertEqual(fused_image.get('year'), year)
        self.assertEqual(fused_image.get('system:time_start'), 123456)
        self.assertEqual(fused_image.type, 'int16')

    def test_get_landcover_series_returns_yearly_images(self):
        geemodules = importlib.import_module('utils.geemodules')

        calls = []

        def fake_loader(year, geometry):
            calls.append((year, geometry))
            return self.FakeImage({'a': year}, 'raw', 'int16')

        years = [2019, 2020]

        with mock.patch.object(
            geemodules.TemporalAggregator,
            '_load_landcover_from_glc_plus',
            side_effect=fake_loader,
        ):
            collection = geemodules.TemporalAggregator.get_landcover_series(
                geometry={'type': 'Polygon'},
                years=years,
                band_prefix='LCZ',
            )

        self.assertIsInstance(collection, self.FakeCollection)
        self.assertEqual(calls, [(2019, {'type': 'Polygon'}), (2020, {'type': 'Polygon'})])
        self.assertEqual(
            [img.band_name for img in collection.images],
            ['LCZ_2019', 'LCZ_2020'],
        )
        self.assertEqual(
            [img.get('year') for img in collection.images],
            years,
        )
        self.assertEqual(
            [img.get('system:time_start') for img in collection.images],
            [20190101, 20200101],
        )
        self.assertTrue(all(img.type == 'int16' for img in collection.images))


def load_tests(loader, tests, pattern):
    return unittest.TestSuite([
        loader.loadTestsFromTestCase(TestImportFromGlcPlusModule),
        loader.loadTestsFromTestCase(TestLoadLandcoverFromGlcPlus),
        loader.loadTestsFromTestCase(TestReplaceWithLandcover),
    ])


if __name__ == '__main__':
    unittest.main()
