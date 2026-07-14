import unittest
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ble_analysis.multivariable_fusion import (
    MultivariableFusionConfig,
    best_tone_selection,
    equal_average_fusion,
    geometric_quality,
    hierarchical_quality_fusion,
    liu_weighted_median_channel_fusion,
    normalized_weights,
    snr_mrc_channel_fusion,
    variable_level_fusion,
    weighted_median,
)


class TestMultivariableFusion(unittest.TestCase):
    def setUp(self):
        self.cfg = MultivariableFusionConfig(
            breath_freq_low=0.1,
            breath_freq_high=0.35,
            snr_good=5.0,
            pr_good=3.0,
        )
        self.fs = 10.0
        self.t = np.arange(0.0, 80.0, 1.0 / self.fs)
        self.f0 = 0.2
        self.clean = np.sin(2.0 * np.pi * self.f0 * self.t)

    def test_best_tone_selection_chooses_highest_quality_tone(self):
        rng = np.random.default_rng(42)
        data = np.column_stack(
            [
                self.clean + 0.05 * rng.normal(size=len(self.t)),
                rng.normal(size=len(self.t)),
                0.2 * rng.normal(size=len(self.t)),
            ]
        )
        out = best_tone_selection(data, self.fs, self.cfg)
        self.assertTrue(out["valid"])
        self.assertEqual(out["selected_tone"], 0)
        self.assertAlmostEqual(out["bpm_pred"], 12.0, delta=0.8)

    def test_equal_average_fusion_preserves_main_frequency(self):
        data = np.column_stack([self.clean, self.clean, self.clean])
        out = equal_average_fusion(data, self.fs, self.cfg)
        self.assertTrue(out["valid"])
        self.assertAlmostEqual(out["bpm_pred"], 12.0, delta=0.5)

    def test_liu_weighted_median_is_not_max_weight_selector(self):
        values = [12.0, 12.2, 12.4, 30.0]
        weights = [0.25, 0.25, 0.25, 0.26]
        self.assertEqual(weighted_median(values, weights), 12.4)
        self.assertNotEqual(weighted_median(values, weights), 30.0)

        rng = np.random.default_rng(7)
        tones = [
            np.sin(2 * np.pi * 0.20 * self.t) + 0.03 * rng.normal(size=len(self.t)),
            np.sin(2 * np.pi * 0.205 * self.t) + 0.03 * rng.normal(size=len(self.t)),
            np.sin(2 * np.pi * 0.21 * self.t) + 0.03 * rng.normal(size=len(self.t)),
            np.sin(2 * np.pi * 0.32 * self.t) + 0.01 * rng.normal(size=len(self.t)),
        ]
        out = liu_weighted_median_channel_fusion(np.column_stack(tones), self.fs, self.cfg)
        self.assertTrue(out["valid"])
        self.assertLess(abs(out["bpm_pred"] - 12.3), 2.0)

    def test_mrc_weights_are_normalized_nonnegative_and_quality_ordered(self):
        weights = normalized_weights([0.1, 1.0, 2.0])
        self.assertAlmostEqual(float(np.sum(weights)), 1.0)
        self.assertTrue(np.all(weights >= 0.0))
        self.assertLess(weights[0], weights[1])
        self.assertLess(weights[1], weights[2])

        rng = np.random.default_rng(13)
        data = np.column_stack(
            [
                self.clean + 0.5 * rng.normal(size=len(self.t)),
                self.clean + 0.05 * rng.normal(size=len(self.t)),
            ]
        )
        out = snr_mrc_channel_fusion(data, self.fs, self.cfg)
        self.assertTrue(out["valid"])
        self.assertGreater(out["weights"][1], out["weights"][0])

    def test_quality_score_handles_missing_metrics(self):
        full = geometric_quality(snr=5.0, pr=3.0, stability=1.0, cfg=self.cfg)
        partial = geometric_quality(snr=5.0, pr=None, stability=1.0, cfg=self.cfg)
        empty = geometric_quality(snr=None, pr=None, stability=None, cfg=self.cfg)
        self.assertTrue(full["valid"])
        self.assertTrue(partial["valid"])
        self.assertFalse(empty["valid"])
        self.assertEqual(empty["quality"], 0.0)

    def test_adaptive_selection_changes_with_window_quality(self):
        variable_results_a = {
            "local_amplitudes": {"valid": True, "bpm_pred": 11.0, "quality": 0.9, "fused_waveform": self.clean},
            "remote_amplitudes": {"valid": True, "bpm_pred": 12.0, "quality": 0.2, "fused_waveform": self.clean},
            "phases": {"valid": True, "bpm_pred": 13.0, "quality": 0.1, "fused_waveform": self.clean},
        }
        variable_results_b = {
            "local_amplitudes": {"valid": True, "bpm_pred": 11.0, "quality": 0.1, "fused_waveform": self.clean},
            "remote_amplitudes": {"valid": True, "bpm_pred": 12.0, "quality": 0.2, "fused_waveform": self.clean},
            "phases": {"valid": True, "bpm_pred": 13.0, "quality": 0.95, "fused_waveform": self.clean},
        }
        out_a = variable_level_fusion(variable_results_a, self.fs, self.cfg, methods=("adaptive_selection",))
        out_b = variable_level_fusion(variable_results_b, self.fs, self.cfg, methods=("adaptive_selection",))
        self.assertEqual(out_a["adaptive_selection"]["selected_variable"], "local_amplitudes")
        self.assertEqual(out_b["adaptive_selection"]["selected_variable"], "phases")

    def test_hierarchical_fusion_smoke(self):
        rng = np.random.default_rng(99)
        local = np.column_stack(
            [
                self.clean + 0.05 * rng.normal(size=len(self.t)),
                self.clean + 0.08 * rng.normal(size=len(self.t)),
            ]
        )
        remote = np.column_stack(
            [
                self.clean + 0.04 * rng.normal(size=len(self.t)),
                np.sin(2 * np.pi * 0.28 * self.t) + 0.2 * rng.normal(size=len(self.t)),
            ]
        )
        phase = np.column_stack(
            [
                self.clean + 0.2 * rng.normal(size=len(self.t)),
                rng.normal(size=len(self.t)),
            ]
        )
        out = hierarchical_quality_fusion(
            {
                "local_amplitudes": local,
                "remote_amplitudes": remote,
                "phases": phase,
            },
            self.fs,
            self.cfg,
        )
        self.assertTrue(out["valid"])
        self.assertAlmostEqual(out["bpm_pred"], 12.0, delta=1.5)
        self.assertIn("per_variable", out)
        self.assertIn("local_amplitudes", out["per_variable"])


if __name__ == "__main__":
    unittest.main()
