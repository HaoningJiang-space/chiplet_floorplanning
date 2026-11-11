"""Independent analytic waveforms and deliberately incomplete circuit inputs."""

import unittest
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np

from tools.validation.pad_sources import selected_member
from tools.validation.pad_spice import (
    closure,
    conversion_audit,
    differences,
    measure_waveform,
    subcircuits,
)
from tools.validation.sources import git_revision


class PadSpiceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "requires Git")
    def test_revision_uses_explicit_checkout_not_installed_package(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(git_revision(root), {"commit": None, "dirty": None})
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "--allow-empty",
                    "-qm",
                    "fixture",
                ],
                cwd=root,
                check=True,
            )
            revision = git_revision(root)
            self.assertEqual(len(revision["commit"]), 40)
            self.assertFalse(revision["dirty"])
            (root / "untracked.txt").write_text("dirty fixture")
            self.assertEqual(git_revision(root), {**revision, "dirty": True})

    def waveform(self):
        t = np.linspace(0, 70, 7001)
        vin = np.interp(t, [0, 10, 11, 40, 41, 70], [0, 0, 3.3, 3.3, 0, 0])
        vout = np.interp(t, [0, 12, 14, 42, 44, 70], [0, 0, 1.8, 1.8, 0, 0])
        return np.column_stack((t * 1e-9, vin, vout))

    def test_independent_delayed_ramp_and_threshold_conventions(self):
        result = measure_waveform(self.waveform(), 1.8, (0.2, 0.8))
        self.assertTrue(result["waveform_gate_passed"])
        for edge in ("rise", "fall"):
            self.assertAlmostEqual(result["metrics"][edge + "_delay_ns"], 2.5)
            self.assertAlmostEqual(result["metrics"][edge + "_slew_ns"], 1.2)
            self.assertAlmostEqual(result["metrics"][edge + "_input_slew_ns"], 0.6)

    def test_ringing_missing_edge_and_missing_settling_are_rejected(self):
        ring = self.waveform()
        ring[2000:2100, 2] = 0
        with self.assertRaisesRegex(ValueError, "crossing"):
            measure_waveform(ring, 1.8, (0.2, 0.8))
        flat = self.waveform()
        flat[:, 2] = 0
        with self.assertRaisesRegex(ValueError, "crossing"):
            measure_waveform(flat, 1.8, (0.2, 0.8))
        bad_rail = self.waveform()
        bad_rail[3500:3900, 2] = 1.6
        self.assertFalse(
            measure_waveform(bad_rail, 1.8, (0.2, 0.8))["waveform_gate_passed"]
        )

    def test_corrupt_samples_fail_closed(self):
        for fault in ("nan", "time", "duration"):
            wave = self.waveform()
            if fault == "nan":
                wave[100, 2] = np.nan
            elif fault == "time":
                wave[100, 0] = wave[99, 0]
            else:
                wave = wave[:-1000]
            with self.assertRaises(ValueError):
                measure_waveform(wave, 1.8, (0.2, 0.8))

    def test_hierarchy_distinguishes_empty_unresolved_and_external(self):
        text = ".SUBCKT top a b\nX1 a b\n+ empty\nX2 a b missing\nX3 a b primitive w=1\n.ENDS\n.SUBCKT empty a b\n.ENDS\n"
        result = closure(subcircuits(text), "top", {"primitive"})
        self.assertEqual(result["empty_subcircuits"], ["empty"])
        self.assertEqual(result["unresolved_subcircuits"], ["missing"])
        self.assertEqual(result["declared_external_primitives"], ["primitive"])
        self.assertFalse(result["structural_gate_passed"])

    def test_bad_ports_and_recursive_circuits_fail(self):
        for text in (
            ".subckt top a b\nX1 a leaf\n.ends\n.subckt leaf a b\nR1 a b 1k\n.ends",
            ".subckt top a b\nX1 a b top\n.ends",
        ):
            with self.assertRaises(ValueError):
                closure(subcircuits(text), "top")

    def test_conversion_cannot_drop_devices_or_change_geometry(self):
        cdl = ".SUBCKT pad a b\nM1 a a b b fet w=2 l=1\nR2 a b 100 $SUB=b $[poly] $W=2 $L=3\n.ENDS\n"
        converted = ".SUBCKT pad a b\nX1 a a b b fet w=2 l=1\nX2 a b 100 b poly r_width=2 r_length=3\n.ENDS\n"
        self.assertEqual(conversion_audit(cdl, converted)["element_count"], 2)
        for bad in (
            converted.replace("w=2", "w=3"),
            converted.replace("X1 a a b b fet w=2 l=1\n", ""),
        ):
            with self.assertRaises(ValueError):
                conversion_audit(cdl, bad)

    def test_gate_does_not_turn_a_model_mismatch_into_a_pass(self):
        ref = dict(rise_delay_ns=2, fall_delay_ns=3, rise_slew_ns=0.2, fall_slew_ns=0.1)
        wrong = {**ref, "fall_delay_ns": 2.4}
        self.assertFalse(differences(wrong, ref, 0.02, 0.1)["passed"])
        self.assertTrue(differences(ref, ref, 0.02, 0.1)["passed"])

    def test_archive_extraction_is_bounded(self):
        self.assertTrue(selected_member("sky130A/libs.ref/io/spice/io.spice"))
        self.assertFalse(selected_member("sky130B/libs.ref/io/spice/io.spice"))
        self.assertFalse(selected_member("sky130A/libs.ref/io/gds/io.gds"))
        for path in ("/etc/spice/model", "sky130A/../outside/spice/model"):
            with self.assertRaises(ValueError):
                selected_member(path)


if __name__ == "__main__":
    unittest.main()
