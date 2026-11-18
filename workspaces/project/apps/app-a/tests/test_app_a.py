import pytest

from app_a import greet


def test_greet():
    assert greet("bazel").message.startswith("hello bazel")


def test_pytest_major():
    # app-a's `test` group pins pytest 7.
    assert pytest.__version__.startswith("7."), pytest.__version__
