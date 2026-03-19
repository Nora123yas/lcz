import unittest
from pathlib import Path

try:
    import pandas as pd
    _ = pd.DataFrame
except Exception:
    pd = None
    raise unittest.SkipTest("pandas not installed")

from utils import lcz_tools

@unittest.skipIf(pd is None, "pandas not installed")
class TestLCZTools(unittest.TestCase):
    def test_compute_city_class_percent(self):
        with self.subTest("aggregate one city"):
            tmp = Path('temp_test')
            csv_dir = tmp / '0001' / 'output'
            csv_dir.mkdir(parents=True, exist_ok=True)
            df = pd.DataFrame({
                'from': [1, 2],
                'to': [2, 3],
                'code': [102, 203],
                'area_m2': [100.0, 200.0],
                'percentage': [33.3, 66.7],
            })
            df.to_csv(csv_dir / 'LCZ_transition_0001_2003to2024_100m.csv', index=False)

            change = pd.DataFrame({'change': [102, 203], 'class': ['Expansion', 'Stable']})
            series = lcz_tools.compute_city_class_percent('0001', tmp, change.rename(columns={'change':'code'}), '2003to2024')
            self.assertIsNotNone(series)
            self.assertAlmostEqual(series['Expansion'], 33.3)
            self.assertAlmostEqual(series['Stable'], 66.7)

            import shutil
            shutil.rmtree(tmp)

