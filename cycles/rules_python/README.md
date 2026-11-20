# Dependency cycles: rules_python 2.5.1

The shared project ([`project/`](../project)) locks `apache-airflow[apache-tinkerpop]==3.4.0` and
`apache-airflow-providers-apache-tinkerpop==1.2.2`.

- `apache-airflow==3.4.0` has an 8-package overlapping base cycle (`apache-airflow`,
  `apache-airflow-core`, `apache-airflow-task-sdk`, and 5 default providers).
- Its `apache-tinkerpop` extra adds a 9th cycle member
  (`apache-airflow-providers-apache-tinkerpop==1.2.2`, which depends on `gremlinpython`) gated on
  `python_full_version < '3.14'`, while `tinkerpop` depends back on `apache-airflow` unconditionally.

**Summary:** `pip.parse(uv_lock = ...)` reads the shared `uv.lock`, but fails analysis with
`cycle in dependency graph` until you manually discover and merge all 8 overlapping Airflow cycle
packages into one `experimental_requirement_cycles` entry. Including the 9th (`tinkerpop`) for
Python 3.12/3.13 support over-includes `tinkerpop` and `gremlin_python` on Python 3.14; omitting it
passes on 3.14 but breaks Python 3.12/3.13.

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

`MODULE.bazel` also defines:
- `@pypi_naive` (no `experimental_requirement_cycles`) for [`naive/BUILD.bazel`](naive/BUILD.bazel).
- `@pypi_all_versions` (all 9 packages, including `apache-airflow-providers-apache-tinkerpop`) for
  [`all_versions/BUILD.bazel`](all_versions/BUILD.bazel).

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
| `bazel test //all_versions:airflow_test` | `//all_versions:airflow_test` | **fail** | `airflow=True standard=True tinkerpop=True gremlin=True` (`AssertionError: unexpected tinkerpop on Python 3.14`) |

## What happened with the naive and multi-version setups

1. **Naive (`@pypi_naive`):** fails during analysis with `cycle in dependency graph` across
   Airflow's overlapping provider cycles.
2. **Multi-version (`@pypi_all_versions`):** listing all 9 packages in
   `experimental_requirement_cycles` keeps Python 3.12, 3.13, and 3.14 building, but collapses all
   9 into one static group target — so `//all_versions:airflow_test` pulls both `tinkerpop` and
   `gremlin_python` into Python 3.14 targets even though the `apache-tinkerpop` extra is gated on
   `python_full_version < '3.14'`.

## Friction / limitations

- **Overlapping cycles must be discovered and merged by hand.** Airflow has 8 interacting packages
  across 6 cycles; `experimental_requirement_cycles` requires listing all of them in a single
  merged group and updating that list whenever Airflow changes its default providers.
- **No marker-aware cycles.** `experimental_requirement_cycles` is a static list, so a
  Python-version-gated cycle forces a tradeoff: omit `tinkerpop` (breaks Python 3.12/3.13) or
  include it (over-includes `tinkerpop` and `gremlin_python` on Python 3.14).
