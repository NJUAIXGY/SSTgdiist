import json
import tempfile
import unittest
from pathlib import Path

from sst_workloads.tensor_si.tools.validate_tensor_m15_residency_trends import main


def _write_summary(path: Path, tensor: dict) -> None:
    path.write_text(json.dumps({"tensor": tensor}, indent=2), encoding="utf-8")


class TestValidateTensorM15ResidencyTrends(unittest.TestCase):
    def test_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            a_on = d / "a_on.json"
            a_off = d / "a_off.json"
            b_on = d / "b_on.json"
            b_off = d / "b_off.json"

            _write_summary(
                a_on,
                {
                    "tensor_mac_ops_total": 1,
                    "tensor_onchip_a_resident_tiles_max": 1,
                    "tensor_onchip_b_resident_tiles_max": 0,
                },
            )
            _write_summary(
                a_off,
                {
                    "tensor_mac_ops_total": 1,
                    "tensor_onchip_a_resident_tiles_max": 0,
                    "tensor_onchip_b_resident_tiles_max": 0,
                },
            )
            _write_summary(
                b_on,
                {
                    "tensor_mac_ops_total": 1,
                    "tensor_onchip_a_resident_tiles_max": 0,
                    "tensor_onchip_b_resident_tiles_max": 1,
                },
            )
            _write_summary(
                b_off,
                {
                    "tensor_mac_ops_total": 1,
                    "tensor_onchip_a_resident_tiles_max": 0,
                    "tensor_onchip_b_resident_tiles_max": 0,
                },
            )

            rc = main(
                [
                    "--keep-a-on",
                    str(a_on),
                    "--keep-a-off",
                    str(a_off),
                    "--keep-b-on",
                    str(b_on),
                    "--keep-b-off",
                    str(b_off),
                    "--label",
                    "unit",
                ]
            )
            self.assertEqual(rc, 0)

    def test_fail_on_keep_off_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            a_on = d / "a_on.json"
            a_off = d / "a_off.json"
            b_on = d / "b_on.json"
            b_off = d / "b_off.json"

            _write_summary(a_on, {"tensor_mac_ops_total": 1, "tensor_onchip_a_resident_tiles_max": 1})
            _write_summary(a_off, {"tensor_mac_ops_total": 1, "tensor_onchip_a_resident_tiles_max": 1})
            _write_summary(b_on, {"tensor_mac_ops_total": 1, "tensor_onchip_b_resident_tiles_max": 1})
            _write_summary(b_off, {"tensor_mac_ops_total": 1, "tensor_onchip_b_resident_tiles_max": 0})

            rc = main(
                [
                    "--keep-a-on",
                    str(a_on),
                    "--keep-a-off",
                    str(a_off),
                    "--keep-b-on",
                    str(b_on),
                    "--keep-b-off",
                    str(b_off),
                ]
            )
            self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()

