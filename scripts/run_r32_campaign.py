#!/usr/bin/env python3
"""Launch the R=32 campaign with three parallel 2-thread jobs."""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    cmd = [
        sys.executable,
        "-u",
        os.path.join(HERE, "scripts", "run_campaign.py"),
        "--R",
        "32",
        "--jobs",
        "3",
        "--threads-per-job",
        "2",
        "--reserve-vcpus",
        "4",
        "--campaign-dir",
        os.path.join(HERE, "campaigns", "R32"),
    ]
    raise SystemExit(subprocess.call(cmd))
