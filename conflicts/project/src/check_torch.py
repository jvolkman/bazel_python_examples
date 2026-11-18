"""Checks which torch build is on sys.path.

Usage: check_torch.py cpu|cu132
"""

import sys

import numpy
import torch

expected = sys.argv[1]
print(f"torch {torch.__version__} (cuda={torch.version.cuda}), numpy {numpy.__version__}")

local = torch.__version__.partition("+")[2]
if local != expected:
    sys.exit(f"expected the +{expected} torch build, got {torch.__version__}")
if expected == "cpu" and torch.version.cuda is not None:
    sys.exit("the CPU build reports a CUDA version")
if expected.startswith("cu") and not torch.version.cuda:
    sys.exit("the CUDA build reports no CUDA version")

# Exercise the native library and a shared dependency.
print(torch.from_numpy(numpy.arange(4)).sum().item())
