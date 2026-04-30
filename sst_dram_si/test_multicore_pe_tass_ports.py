import unittest
from pathlib import Path


HEADER = Path("/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h")


class MultiCorePeTassPortDocsTests(unittest.TestCase):
    def test_header_declares_naive_tass_response_ports_and_events(self):
        text = HEADER.read_text(encoding="utf-8")
        self.assertIn("tass_p0_rsp_out0", text)
        self.assertIn("SnnDL.TassNaiveResponseEvent", text)
        self.assertIn("SnnDL.TassNaiveWindowRequestEvent", text)


if __name__ == "__main__":
    unittest.main()
