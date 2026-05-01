#!/usr/bin/env python3
import re
import unittest
from pathlib import Path


def _registered_stats(cc_text: str) -> set[str]:
    return set(re.findall(r'registerStatistic<[^>]+>\("([^"]+)"\)', cc_text))


def _eli_stats(header_text: str) -> set[str]:
    return set(re.findall(r'\{"([^"]+)",\s*"[^"]*",\s*"[^"]*",\s*1\}', header_text))


class MultiCorePEStatisticsContractTest(unittest.TestCase):
    def test_all_registered_stats_are_documented_in_eli(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cc_path = root / "components" / "MultiCorePE.cc"
        header_path = root / "components" / "MultiCorePE.h"

        registered = _registered_stats(cc_path.read_text(encoding="utf-8"))
        documented = _eli_stats(header_path.read_text(encoding="utf-8"))
        missing = sorted(registered - documented)

        self.assertEqual(
            missing,
            [],
            msg=(
                "MultiCorePE registers statistics that are missing from "
                f"SST_ELI_DOCUMENT_STATISTICS: {missing}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
