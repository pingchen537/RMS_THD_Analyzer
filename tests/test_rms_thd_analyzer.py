import importlib.util
import os
import sys
import tempfile
import textwrap
import unittest
from datetime import datetime
from pathlib import Path


os.environ.setdefault("MPLBACKEND", "Agg")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY_ROOT / "RMS_THD_Analyzer.py"
SPEC = importlib.util.spec_from_file_location("rms_thd_analyzer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
analyzer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analyzer
SPEC.loader.exec_module(analyzer)


class AnalyzerTests(unittest.TestCase):
    def _write_input(self, directory: Path, content: str) -> Path:
        path = directory / "input.csv"
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

    def test_repository_demo_loads_three_duts(self) -> None:
        sample = REPOSITORY_ROOT / "sample_data" / "RMS_THD_sample.csv"
        rms, distortion, _warnings, rms_unit, metric = analyzer.load_measurements(sample)
        self.assertEqual(list(rms), ["DUT_WA001", "DUT_WA002", "DUT_WA003"])
        self.assertEqual(list(distortion), list(rms))
        self.assertEqual(rms_unit, "dBSPL")
        self.assertEqual(metric, "THD")

    def test_thdn_and_dbfs_are_detected_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._write_input(
                Path(temporary),
                """
                thd + n -> Specify Data Points
                DUT_A
                Hz,%
                100,1.2
                1000,0.4

                rMs LeVeL -> Specify Data Points
                DUT_A
                Hz,dBFS
                100,-30
                1000,-12
                """,
            )
            _rms, _distortion, _warnings, rms_unit, metric = analyzer.load_measurements(path)
            self.assertEqual(rms_unit, "dBFS")
            self.assertEqual(metric, "THD+N")

    def test_distortion_db_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._write_input(
                Path(temporary),
                """
                THD+N
                DUT_A
                Hz,dB
                100,-40

                RMS Level
                DUT_A
                Hz,dBSPL
                100,60
                """,
            )
            with self.assertRaisesRegex(ValueError, "must use percent"):
                analyzer.load_measurements(path)

    def test_filename_stems_remain_unique(self) -> None:
        names = ["DUT/A", "DUT:A", "樣品一", "樣品二", "dut_a"]
        stems = analyzer._unique_filename_stems(names)
        self.assertEqual(len({stem.casefold() for stem in stems.values()}), len(names))
        self.assertIn("樣品一", stems["樣品一"])
        self.assertIn("樣品二", stems["樣品二"])

    def test_output_directory_is_never_reused(self) -> None:
        fixed_time = datetime(2026, 8, 25, 17, 47, 1, 0)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "output"
            first = analyzer.create_unique_output_dir(base, now=fixed_time)
            second = analyzer.create_unique_output_dir(base, now=fixed_time)
            self.assertNotEqual(first, second)
            self.assertTrue(second.name.endswith("_001"))


if __name__ == "__main__":
    unittest.main()
