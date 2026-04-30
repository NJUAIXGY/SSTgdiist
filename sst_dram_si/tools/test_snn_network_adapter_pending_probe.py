import unittest
from pathlib import Path


class SnnNetworkAdapterPendingProbeTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(__file__).resolve().parents[2]
        self.nic_h = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/SnnNetworkAdapter.h"
        self.nic_cc = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/SnnNetworkAdapter.cc"

    def test_pending_probe_fields_and_finish_log_exist(self):
        h_text = self.nic_h.read_text(encoding="utf-8")
        cc_text = self.nic_cc.read_text(encoding="utf-8")

        for key in [
            "pending_send_enqueue_total_",
            "pending_send_dequeue_total_",
            "pending_send_high_watermark_",
            "pending_send_space_block_total_",
            "pending_send_send_fail_total_",
        ]:
            self.assertIn(key, h_text, msg=f"{key} missing from SnnNetworkAdapter.h")

        for key in [
            "pending_send_enqueue_total_",
            "pending_send_dequeue_total_",
            "pending_send_high_watermark_",
            "pending_send_space_block_total_",
            "pending_send_send_fail_total_",
            "[snn-nic-pending]",
            'enq=%" PRIu64',
            'deq=%" PRIu64',
            'hwm=%" PRIu64',
            'space_block=%" PRIu64',
            'send_fail=%" PRIu64',
            'final=%zu',
        ]:
            self.assertIn(key, cc_text, msg=f"{key} missing from SnnNetworkAdapter.cc")


if __name__ == "__main__":
    unittest.main()
