"""Checks the implicit all-members "prod" group: apps import, dev/test tools don't."""

import importlib.util

import app_a
import app_b

print(app_a.greet("prod").message)
print(app_b.greet("prod").message)

for name in ("pytest", "ruff", "mypy"):
    assert importlib.util.find_spec(name) is None, f"{name} leaked into prod"
