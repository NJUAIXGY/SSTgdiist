#!/usr/bin/env python3

import os
import sys

import sst


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from spiketile_b_v0.entry import run_mesh_4x4


run_mesh_4x4(sst_module=sst, script_file=__file__)

