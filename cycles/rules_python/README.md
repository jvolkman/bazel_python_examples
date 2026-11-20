# Dependency cycles with rules_python 2.5.1

This module tests the Apache Airflow lock in [`project/`](../project) (`apache-airflow[apache-tinkerpop]==3.4.0` and `apache-airflow-providers-apache-tinkerpop==1.2.2`) using rules_python 2.5.1, Bazel 9.3.2, and Python 3.14. See [`cycles/README.md`](../README.md) for the scenario overview.

`pip.parse(uv_lock = ...)` reads the shared `uv.lock`, but fails analysis with `cycle in dependency graph` until you find and merge all 8 overlapping Airflow cycle packages into one `experimental_requirement_cycles` entry. Adding the 9th package (`tinkerpop`) so Python 3.12 and 3.13 keep working causes Python 3.14 targets to pull in `tinkerpop` and `gremlin_python`; leaving it out passes on 3.14 but breaks 3.12 and 3.13.

## Setup

[`MODULE.bazel`](MODULE.bazel) (trimmed):

```starlark
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.14")

pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")
pip.parse(
    experimental_requirement_cycles = {
        "airflow": [
            "apache-airflow",
            "apache-airflow-core",
            "apache-airflow-task-sdk",
            "apache-airflow-providers-common-compat",
            "apache-airflow-providers-common-io",
            "apache-airflow-providers-common-sql",
            "apache-airflow-providers-smtp",
            "apache-airflow-providers-standard",
        ],
    },
    hub_name = "pypi_cycles",
    python_version = "3.14",
    uv_lock = "//:project/uv.lock",
)
use_repo(pip, "pypi_cycles")
```

`MODULE.bazel` also defines `@pypi_naive` (no `experimental_requirement_cycles`, used by [`naive/BUILD.bazel`](naive/BUILD.bazel)) and `@pypi_all_versions` (all 9 packages including `apache-airflow-providers-apache-tinkerpop`, used by [`all_versions/BUILD.bazel`](all_versions/BUILD.bazel)).

Run:

```sh
bazel test //...                           # passes on Python 3.14 (8-package cycle list)
bazel build //naive:airflow_test           # reproduces the analysis cycle error
bazel test //all_versions:airflow_test     # reproduces tinkerpop + gremlin over-inclusion on 3.14
```

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:airflow_test` | pass | `airflow=True standard=True tinkerpop=False gremlin=False` |
| `bazel test //...` | `//:tinkerpop_test` | pass | `airflow=True standard=True tinkerpop=True gremlin=True` |
| `bazel build //naive:airflow_test` | `//naive:airflow_test` | analysis error | `cycle in dependency graph` |
| `bazel test //all_versions:airflow_test` | `//all_versions:airflow_test` | fail | `airflow=True standard=True tinkerpop=True gremlin=True` (`AssertionError: unexpected tinkerpop on Python 3.14`) |

## Naive and multi-version setups

With `@pypi_naive`, `bazel build //naive:airflow_test` fails during analysis with `cycle in dependency graph` across Airflow's overlapping provider cycles.

With `@pypi_all_versions`, listing all 9 packages in `experimental_requirement_cycles` keeps Python 3.12, 3.13, and 3.14 building, but collapses all 9 into one static group target. As a result, `//all_versions:airflow_test` pulls both `tinkerpop` and `gremlin_python` into Python 3.14 builds even though the `apache-tinkerpop` extra has the marker `python_full_version < '3.14'`.

## Friction and limitations

- Overlapping cycles have to be discovered and merged by hand. Airflow has 8 interacting packages across 6 cycles, and the list in `experimental_requirement_cycles` needs to be updated whenever Airflow changes its default providers.
- `experimental_requirement_cycles` is static and does not check markers. For a Python-version-gated cycle, you have to choose between omitting `tinkerpop` (breaking Python 3.12 and 3.13) or including it (over-including `tinkerpop` and `gremlin_python` on Python 3.14).
