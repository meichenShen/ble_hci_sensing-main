import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ble_analysis.chfusion import ChFusionConfig
from ble_analysis.liu_2016 import (
    Liu2016PaperConfig,
    estimate_fft_phase_slope_bpm,
    estimate_liu_2016_paper_window,
    estimate_liu_eta_rho_adapted_window_bpms,
    modified_z_score_filter,
    score_sinusoid_periodicity,
    weighted_median_frequency,
)


class Liu2016Test(unittest.TestCase):
    def test_eta_rho_adapted_window_bpms_prefers_dominant_tone(self) -> None:
        """The historical eta/rho BLE adapted baseline is not strict Liu 2016."""
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

        bpm, bpm_per_tone, weights = estimate_liu_eta_rho_adapted_window_bpms(window_data, fs, cfg=cfg)

        self.assertTrue(np.isfinite(bpm))
        self.assertGreaterEqual(len(bpm_per_tone), 3)
        self.assertAlmostEqual(bpm, 12.0, delta=2.0)
        self.assertEqual(weights.shape[0], window_data.shape[1])

    def test_fft_phase_slope_estimator_recovers_02hz(self) -> None:
        fs = 20.0
        cfg = Liu2016PaperConfig(breath_freq_low=0.1, breath_freq_high=0.35)
        t = np.arange(0.0, 40.0, 1.0 / fs)
        signal = np.sin(2.0 * np.pi * 0.2 * t)

        out = estimate_fft_phase_slope_bpm(signal, fs, cfg)

        self.assertTrue(out["valid"])
        self.assertAlmostEqual(out["bpm"], 12.0, delta=0.5)

    def test_periodicity_pr_higher_for_sinusoid_than_noise(self) -> None:
        rng = np.random.default_rng(7)
        fs = 20.0
        cfg = Liu2016PaperConfig()
        t = np.arange(0.0, 20.0, 1.0 / fs)
        clean = np.sin(2.0 * np.pi * 0.2 * t) + 0.05 * rng.normal(size=len(t))
        noise = rng.normal(size=len(t))

        clean_score = score_sinusoid_periodicity(clean, fs, 0.2, cfg)
        noise_score = score_sinusoid_periodicity(noise, fs, 0.2, cfg)

        self.assertGreater(clean_score["pr"], noise_score["pr"])

    def test_modified_z_score_removes_obvious_outlier(self) -> None:
        cfg = Liu2016PaperConfig()
        freqs = np.array([0.198, 0.2, 0.202, 0.199, 0.32])

        out = modified_z_score_filter(freqs, cfg)

        self.assertEqual(out["zscore_scale"], 0.7645)
        self.assertEqual(out["mask"].tolist(), [True, True, True, True, False])

    def test_weighted_median_frequency_is_not_max_weight_fallback(self) -> None:
        cfg = Liu2016PaperConfig()
        freqs = np.array([0.10, 0.20, 0.30])
        weights = np.array([0.49, 0.02, 0.49])
        mask = np.array([True, True, True])

        fused = weighted_median_frequency(freqs, weights, mask, cfg)

        self.assertAlmostEqual(fused, 0.20)

    def test_paper_window_estimator_rejects_outlier_tone(self) -> None:
        fs = 20.0
        cfg = Liu2016PaperConfig(breath_freq_low=0.1, breath_freq_high=0.35)
        t = np.arange(0.0, 40.0, 1.0 / fs)
        good_a = np.sin(2.0 * np.pi * 0.2 * t)
        good_b = 0.8 * np.sin(2.0 * np.pi * 0.202 * t + 0.4)
        good_c = 0.9 * np.sin(2.0 * np.pi * 0.198 * t + 1.1)
        outlier = np.sin(2.0 * np.pi * 0.32 * t)
        window = np.column_stack([good_a, good_b, good_c, outlier])

        out = estimate_liu_2016_paper_window(window, fs, cfg)

        self.assertTrue(out["valid"])
        self.assertLess(out["n_kept"], out["n_tones"])
        self.assertAlmostEqual(out["bpm"], 12.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
