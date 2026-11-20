# Dependency cycles with rules_py 2.0.0-alpha.11

This module tests the Apache Airflow lock in [`project/`](../project) (`apache-airflow[apache-tinkerpop]==3.4.0` and `apache-airflow-providers-apache-tinkerpop==1.2.2`) using [rules_py](https://github.com/aspect-build/rules_py) 2.0.0-alpha.11, Bazel 9.3.2, and Python 3.14. See [`cycles/README.md`](../README.md) for the scenario overview.

## Setup

rules_py detects strongly connected components (SCCs) in `uv.lock` automatically and collapses all 9 cycle packages into a single `py_library` target under `//private/sccs:`. Every member alias in the hub points at that shared target.

[`MODULE.bazel`](MODULE.bazel):

```starlark
bazel_dep(name = "rules_py", version = "2.0.0-alpha.11")

interpreters = use_extension("@rules_py//py:extensions.bzl", "python_interpreters")
interpreters.toolchain(python_version = "3.14")
use_repo(interpreters, "python_interpreters")
register_toolchains("@python_interpreters//:all")

uv = use_extension("@rules_py//uv:extensions.bzl", "uv")
uv.declare_hub(hub_name = "pypi")
uv.project(
    hub_name = "pypi",
    lock = "//:project/uv.lock",
    pyproject = "//:project/pyproject.toml",
)
use_repo(uv, "pypi")
```

Run:

```sh
bazel test //...                                # airflow_imports_test only (checks airflow + standard import)
bazel test //:airflow_test //:tinkerpop_test    # reproduces both SCC bugs on Python 3.14
```

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:airflow_imports_test` | pass | `airflow=True standard=True tinkerpop=False gremlin=True` |
| `bazel test //:airflow_test` | `//:airflow_test` | fail | `airflow=True standard=True tinkerpop=False gremlin=True` (`AssertionError: unexpected gremlin_python on Python 3.14`) |
| `bazel test //:tinkerpop_test` | `//:tinkerpop_test` | fail | `airflow=True standard=True tinkerpop=False gremlin=True` (`AssertionError: missing tinkerpop (direct dep!)`) |

## Why both strict tests fail

In `uv/private/extension/graph_utils.bzl` (`collect_sccs`), rules_py computes SCCs without evaluating environment markers and collapses all 9 packages into one shared `py_library`. On Python 3.14, that causes both over-inclusion and under-inclusion:

1. `//:airflow_test` leaks `gremlin_python`. rules_py unions every SCC member's external dependencies into the shared target using their raw edge markers. Because `tinkerpop -> gremlinpython` has no Python 3.14 restriction, `gremlin_python` ends up in `@pypi//apache_airflow` even though `tinkerpop` itself is inactive on Python 3.14.
2. `//:tinkerpop_test` drops `tinkerpop` itself. rules_py gates each member's wheel on the union of its inbound intra-SCC edge markers. Because `tinkerpop`'s only inbound edge inside the SCC is `apache-airflow -> tinkerpop; python_full_version < '3.14'`, rules_py replaces `tinkerpop`'s wheel with `:empty` on Python 3.14 even when a target depends directly on `@pypi//apache_airflow_providers_apache_tinkerpop` (while still leaving `gremlin_python` in the venv).

Both `//:airflow_test` and `//:tinkerpop_test` are tagged `manual` so `bazel test //...` passes via `//:airflow_imports_test`.

## Friction and limitations

- Marker-gated cycles leak external dependencies of inactive members and drop direct dependencies whose inbound cycle edges are inactive.
- There is no `MODULE.bazel` setting to preserve per-entry reachability on the shared lock; fixing it requires editing `uv.lock`.
- As in other rules_py modules, targets must set `dep_group = "cycle-app"` (or configure a default in `.bazelrc`).
