import tempfile
import os
import unittest

try:
    from utils.TaskManager import FileManager
except Exception:
    FileManager = None

class TestFileManager(unittest.TestCase):
    @unittest.skipIf(FileManager is None, "ee not installed")
    def test_get_city_files(self):
        city_id = 12345
        with tempfile.TemporaryDirectory() as tmp:
            years = [2020, 2021, 2022]
            expected = {
                2020: {},
                2021: {},
                2022: {
                    'day': os.path.join(tmp, f"day_LST_{city_id}_2022.tif"),
                    'night': os.path.join(tmp, f"night_LST_{city_id}_2022.tif"),
                    'lcz': os.path.join(tmp, f"LCZ_{city_id}_2022.tif"),
                },
            }
            for dn in ['day', 'night']:
                fname = f"{dn}_LST_LCZ_{city_id}_2020-2021.tif"
                path = os.path.join(tmp, fname)
                with open(path, 'w'):
                    pass
                expected[2020][dn] = (path, 0)
                expected[2021][dn] = (path, 2)

            # create separate per-year files for 2022
            for fname in [
                f"day_LST_{city_id}_2022.tif",
                f"night_LST_{city_id}_2022.tif",
                f"LCZ_{city_id}_2022.tif",
            ]:
                path = os.path.join(tmp, fname)
                with open(path, 'w'):
                    pass

            result = FileManager.get_city_files(city_id, tmp)
            self.assertEqual(result, expected)

def load_tests(loader, tests, pattern):
    return unittest.TestSuite([
        loader.loadTestsFromTestCase(TestFileManager)
    ])

if __name__ == '__main__':
    unittest.main()
