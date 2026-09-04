import unittest

from aqi_site import mask
from aqi_site.config import MASK_PRESETS, MaskConfig


class MaskLevelTests(unittest.TestCase):
    def setUp(self):
        self.thresholds = MaskConfig().thresholds  # asthma preset (51/76/101/201)

    def test_boundaries(self):
        cases = {
            0: "none", 50: "none",
            51: "carry", 75: "carry",
            76: "recommended", 100: "recommended",
            101: "strong", 200: "strong",
            201: "indoors", 500: "indoors",
        }
        for value, expected in cases.items():
            self.assertEqual(mask.level_for(value, self.thresholds), expected, value)

    def test_none_when_unknown(self):
        self.assertEqual(mask.level_for(None, self.thresholds), "none")

    def test_asthma_more_conservative_than_general(self):
        asthma = MaskConfig(sensitivity="asthma").thresholds
        general = MASK_PRESETS["general"]
        for a, g in zip(asthma, general):
            self.assertLess(a, g)

    def test_recommend_payload(self):
        reco = mask.recommend(130, self.thresholds, dominant="pm2_5", trend="worsening")
        self.assertEqual(reco["level"], "strong")
        self.assertIn("N95", reco["mask_type"])
        self.assertEqual(reco["dominant"], "pm2_5")
        self.assertEqual(reco["trend"], "worsening")
        self.assertIn("not medical advice", reco["disclaimer"].lower())

    def test_all_levels_ordered(self):
        levels = [entry["level"] for entry in mask.all_levels()]
        self.assertEqual(levels, mask.LEVELS)


if __name__ == "__main__":
    unittest.main()
