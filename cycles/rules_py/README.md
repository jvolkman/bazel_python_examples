# Dependency cycles: rules_py 2.0.0-alpha.11

The shared project ([`project/`](../project)) locks `apache-airflow[apache-tinkerpop]==3.4.0` and
`apache-airflow-providers-apache-tinkerpop==1.2.2`, with
[rules_py](https://github.com/aspect-build/rules_py) 2.0.0-alpha.11, Bazel 9.3.2, Python 3.14.

- `apache-airflow==3.4.0` has an 8-package overlapping base cycle.
- Its `apache-tinkerpop` extra adds a 9th cycle member
  (`apache-airflow-providers-apache-tinkerpop==1.2.2`, which depends on `gremlinpython`) gated on
  `python_full_version < '3.14'`, while `tinkerpop` depends back on `apache-airflow` unconditionally.

## Setup

rules_py detects strongly connected components (SCCs) in `uv.lock` automatically and collapses all
9 packages into a single `py_library` target under `//private/sccs:`. Every member alias in the
hub points at that shared SCC target.

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
bazel test //:airflow_test //:tinkerpop_test    # reproduces BOTH SCC bugs on Python 3.14
```

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:airflow_imports_test` | pass | `airflow=True standard=True tinkerpop=False gremlin=True` |
| `bazel test //:airflow_test` | `//:airflow_test` | **fail** | `airflow=True standard=True tinkerpop=False gremlin=True` (`AssertionError: unexpected gremlin_python on Python 3.14`) |
| `bazel test //:tinkerpop_test` | `//:tinkerpop_test` | **fail** | `airflow=True standard=True tinkerpop=False gremlin=True` (`AssertionError: missing tinkerpop (direct dep!)`) |

## What fails on marker-gated cycles

In `uv/private/extension/graph_utils.bzl` (`collect_sccs`), rules_py computes SCCs without
evaluating environment markers, collapses all 9 packages into one shared `py_library`, and triggers
**both** over-inclusion and under-inclusion on Python 3.14:

1. **Over-inclusion (`//:airflow_test`):** rules_py unions every SCC member's external dependencies
   into the shared SCC target using their raw edge markers. Because `tinkerpop -> gremlinpython` is
   unconditional, `gremlin_python` leaks into `@pypi//apache_airflow` even though `tinkerpop`
   itself is inactive on Python 3.14.
2. **Under-inclusion (`//:tinkerpop_test`):** rules_py gates each SCC member's wheel on the union
   of its **inbound intra-SCC edge markers**. Because `tinkerpop`'s only inbound edge inside the
   SCC is `apache-airflow -> tinkerpop; python_full_version < '3.14'`, rules_py replaces
   `tinkerpop`'s own wheel with `:empty` on Python 3.14 — even when a target depends directly on
   `@pypi//apache_airflow_providers_apache_tinkerpop` (and while still pulling in `gremlin_python`).

Both `//:airflow_test` and `//:tinkerpop_test` are tagged `manual` so `bazel test //...` passes
via `//:airflow_imports_test`.

## Friction / limitations

- **Marker-gated cycles both leak external deps and silently drop direct dependencies.**
- **No `MODULE.bazel` workaround on the shared lock.** SCC grouping happens automatically inside
  the `uv` extension with no way to preserve per-entry reachability without editing `uv.lock`.
- Like other `rules_py` projects, targets must specify `dep_group = "cycle-app"` (or set a default
  in `.bazelrc`).
