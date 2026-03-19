import sys
import types
import unittest

# Provide dummy ee module for imports
sys.modules.setdefault('ee', types.ModuleType('ee'))

from utils.accuracy import calculate_accuracy

class TestAccuracy(unittest.TestCase):
    def test_calculate_accuracy(self):
        y_true = [1, 1, 2, 2, 3, 3]
        y_pred = [1, 2, 2, 2, 3, 1]
        acc, labels, matrix = calculate_accuracy(y_true, y_pred)
        self.assertAlmostEqual(acc, 4/6)
        self.assertEqual(labels, [1,2,3])
        self.assertEqual(matrix, [[1,1,0],[0,2,0],[1,0,1]])

def load_tests(loader, tests, pattern):
    return unittest.TestSuite([
        loader.loadTestsFromTestCase(TestAccuracy)
    ])

if __name__ == '__main__':
    unittest.main()
