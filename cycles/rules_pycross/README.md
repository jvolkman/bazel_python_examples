# Dependency cycles with rules_pycross (`main`)

This module tests the Apache Airflow lock in [`project/`](../project) (`apache-airflow[apache-tinkerpop]==3.4.0` and `apache-airflow-providers-apache-tinkerpop==1.2.2`) using [rules_pycross](https://github.com/jvolkman/rules_pycross) pinned to `main` (`8d788096`) and rules_python 2.5.1 (toolchain and `py_test`), on Bazel 9.3.2 and Python 3.14. See [`cycles/README.md`](../README.md) for the scenario overview.

## Setup

rules_pycross finds strongly connected components (SCCs) in `uv.lock` automatically. Instead of collapsing the whole SCC into one `py_library`, it emits a `_raw_<pkg>` target per member (with non-cycle dependencies only) and a `pycross_cycle_member_marker_deps` wrapper that evaluates reachability from each entry member against the active Python version and platform markers. You do not need to list cycles in `MODULE.bazel`.

[`MODULE.bazel`](MODULE.bazel):

```starlark
bazel_dep(name = "rules_pycross")
git_override(
    module_name = "rules_pycross",
    commit = "8d78809639063b1582dfda0bd78a39dc8b967ff8",
    remote = "https://github.com/jvolkman/rules_pycross.git",
)
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.14")

uv = use_extension("@rules_pycross//pycross/extensions:uv.bzl", "uv")
uv.workspace(name = "pypi", lock_file = "//:project/uv.lock")
use_repo(uv, "pypi")
```

[`BUILD.bazel`](BUILD.bazel):

```starlark
py_test(
    name = "airflow_test",
    srcs = ["project/src/check_cycle.py"],
    args = ["airflow"],
    main = "project/src/check_cycle.py",
    deps = ["@pypi//apache_airflow"],
)
# tinkerpop_test: the same with @pypi//apache_airflow_providers_apache_tinkerpop and args = ["tinkerpop"].
```

Run: `bazel test //...`

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:airflow_test` | pass | `airflow=True standard=True tinkerpop=False gremlin=False` |
| `bazel test //...` | `//:tinkerpop_test` | pass | `airflow=True standard=True tinkerpop=True gremlin=True` |

On Python 3.14, `@pypi//apache_airflow` brings in the active 8-package Airflow cycle without pulling in `tinkerpop` or `gremlin_python`. Depending directly on `@pypi//apache_airflow_providers_apache_tinkerpop` keeps `tinkerpop`, `gremlin_python`, and the Airflow cycle it depends on.

## Friction and limitations

The shared `uv.lock` works unchanged, without a manual cycle list and without over- or under-inclusion across Python versions.
