import json
import tempfile
import unittest
from pathlib import Path

from sst_workloads.tensor_si.tools.validate_tensor_m16_wavefront_trends import main


def _write_summary(path: Path, tensor: dict) -> None:
    path.write_text(json.dumps({"tensor": tensor}, indent=2), encoding="utf-8")


class TestValidateTensorM16WavefrontTrends(unittest.TestCase):
    def test_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            off = d / "off.json"
            on = d / "on.json"

            _write_summary(
                off,
                {
                    "tensor_mac_ops_total": 1,
                    "tensor_mxu_wavefront_cycles_total": 0,
                    "tensor_compute_cycles_total": 10,
                },
            )
            _write_summary(
                on,
                {
                    "tensor_mac_ops_total": 1,
                    "tensor_mxu_wavefront_cycles_total": 3,
                    "tensor_compute_cycles_total": 13,
                },
            )

            rc = main(["--off", str(off), "--on", str(on), "--label", "unit"])
            self.assertEqual(rc, 0)

    def test_fail_when_not_increasing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            off = d / "off.json"
            on = d / "on.json"

            _write_summary(
                off,
                {
                    "tensor_mac_ops_total": 1,
                    "tensor_mxu_wavefront_cycles_total": 0,
                    "tensor_compute_cycles_total": 10,
                },
            )
            _write_summary(
                on,
                {
                    "tensor_mac_ops_total": 1,
                    "tensor_mxu_wavefront_cycles_total": 1,
                    "tensor_compute_cycles_total": 10,
                },
            )

            rc = main(["--off", str(off), "--on", str(on)])
            self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()

