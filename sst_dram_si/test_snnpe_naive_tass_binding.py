import re
import unittest
from pathlib import Path


SOURCE = Path("/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc")


class SnnPeNaiveTassBindingTests(unittest.TestCase):
    def test_set_parent_interface_rebinds_naive_tass_callback(self):
        text = SOURCE.read_text(encoding="utf-8")
        m = re.search(r"void SnnPESubComponent::setParentInterface\(IPeAggregation\* parent\) \{(?P<body>.*?)\n\}", text, re.S)
        self.assertIsNotNone(m)
        body = m.group("body")
        self.assertIn("setSubmitTassNaiveWindowRequestFn", body)


if __name__ == "__main__":
    unittest.main()
