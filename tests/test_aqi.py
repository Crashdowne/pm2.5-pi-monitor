import unittest

from pm25 import aqi


class AqiTests(unittest.TestCase):
    def test_pm25_revised_breakpoints(self) -> None:
        self.assertEqual(aqi.aqi("pm2_5", 9.0), 50)
        self.assertEqual(aqi.aqi("pm2_5", 9.1), 51)
        self.assertEqual(aqi.aqi("pm2_5", 35.4), 100)
        self.assertEqual(aqi.aqi("pm2_5", 35.5), 101)

    def test_pm10_truncates_to_whole_units(self) -> None:
        self.assertEqual(aqi.aqi("pm10", 54.9), 50)
        self.assertEqual(aqi.aqi("pm10", 55.0), 51)

    def test_nowcast_weights_recent_values_more_heavily(self) -> None:
        result = aqi.nowcast([5.0, 5.0, 5.0, 50.0])

        self.assertIsNotNone(result)
        self.assertGreater(result or 0, 25)
        self.assertLess(result or 0, 50)

    def test_humidity_correction_is_bounded_at_zero(self) -> None:
        self.assertEqual(aqi.correct_pm25(0, 100), 0.0)
        self.assertEqual(aqi.correct_pm25(20, 50), 11.9)


if __name__ == "__main__":
    unittest.main()