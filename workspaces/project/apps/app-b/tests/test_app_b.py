import pytest

from app_b import greet


def test_greet():
    assert greet("bazel").message.startswith("hi bazel")


def test_pytest_major():
    # app-b's `test` group requires pytest 8 or newer.
    assert int(pytest.__version__.split(".")[0]) >= 8, pytest.__version__
