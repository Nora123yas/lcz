import sys
import types
import unittest

sys.modules.setdefault('ee', types.ModuleType('ee'))
sys.modules.setdefault('numpy', types.ModuleType('numpy'))
sys.modules.setdefault('pandas', types.ModuleType('pandas'))
sys.modules.setdefault('rasterio', types.ModuleType('rasterio'))

from utils.processors import calculate_contributions

class TestContributions(unittest.TestCase):
    def test_calculate_contributions(self):
        pixel_df = [
            {'change': 1111, 'day_diff': 1.0, 'night_diff': 0.5},
            {'change': 1111, 'day_diff': 2.0, 'night_diff': 0.5},
            {'change': 1122, 'day_diff': 3.0, 'night_diff': 1.0},
            {'change': 1122, 'day_diff': 4.0, 'night_diff': 1.0},
        ]
        slopes = {'day': 0.1, 'night': 0.05}
        result = calculate_contributions(pixel_df, slopes)
        res = {r['change']: r for r in result}
        self.assertAlmostEqual(res[1111]['day_ratio'], 0.3)
        self.assertAlmostEqual(res[1122]['night_extra'], 2/(0.05*22))

def load_tests(loader, tests, pattern):
    return unittest.TestSuite([
        loader.loadTestsFromTestCase(TestContributions),
    ])

if __name__ == '__main__':
    unittest.main()
