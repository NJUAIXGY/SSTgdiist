from __future__ import annotations

from typing import Any


def enable_default_statistics(sst_module: Any) -> None:
    """
    Enable default statistics types used by the 4x4 mesh template.

    Must be called before component creation, to preserve legacy behavior.
    """

    sst_module.enableAllStatisticsForComponentType("SnnDL.MultiCorePE", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForComponentType("SnnDL.SpikeSource", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForComponentType("merlin.hr_router", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForComponentType("SnnDL.SnnPESubComponent", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForComponentType("memHierarchy.Cache", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForComponentType("memHierarchy.MemController", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForComponentType("SnnDL.SnnNIC", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForAllComponents({"type": "sst.AccumulatorStatistic"})
