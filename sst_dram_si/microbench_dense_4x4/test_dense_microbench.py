#!/usr/bin/env python3

import sst

from microbench_dense.entry import run_dense_microbench


run_dense_microbench(sst_module=sst, script_file=__file__)

