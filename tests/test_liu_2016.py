import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ble_analysis.chfusion import ChFusionConfig
from ble_analysis.liu_2016 import estimate_liu_style_window_bpms


class Liu2016Test(unittest.TestCase):
    def test_estimate_liu_style_window_bpms_prefers_dominant_tone(self) -> None:
        fs = 20.0
        t = np.arange(0.0, 12.0, 1.0 / fs)
        breath = np.sin(2.0 * np.pi * 0.2 * t)
        noise = 0.5 * np.sin(2.0 * np.pi * 0.3 * t)

        window_data = np.column_stack([
            breath + 0.05 * noise,
            0.2 * noise,
            0.2 * noise,
        ])
        cfg = ChFusionConfig(breath_freq_low=0.1, breath_freq_high=0.35)

        bpm, bpm_per_tone, weights = estimate_liu_style_window_bpms(window_data, fs, cfg=cfg)

        self.assertTrue(np.isfinite(bpm))
        self.assertGreaterEqual(len(bpm_per_tone), 3)
        self.assertAlmostEqual(bpm, 12.0, delta=2.0)
        self.assertEqual(weights.shape[0], window_data.shape[1])


if __name__ == "__main__":
    unittest.main()
