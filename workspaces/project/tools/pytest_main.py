"""Runs pytest on the files passed as arguments (for plain py_test rules)."""

import sys

import pytest

if __name__ == "__main__":
    sys.exit(pytest.main(["-p", "no:cacheprovider", *sys.argv[1:]]))
