# Dependency cycles: rules_pycross (`main`)

The shared project ([`project/`](../project)) locks `apache-airflow[apache-tinkerpop]==3.4.0` and
`apache-airflow-providers-apache-tinkerpop==1.2.2`, with
[rules_pycross](https://github.com/jvolkman/rules_pycross) pinned to `main` (`bd4800c5`) and
rules_python 2.5.1 (toolchain and `py_test`), Bazel 9.3.2, Python 3.14.

- `apache-airflow==3.4.0` has an 8-package overlapping base cycle (`apache-airflow`,
  `apache-airflow-core`, `apache-airflow-task-sdk`, `apache-airflow-providers-common-compat`,
  `apache-airflow-providers-common-io`, `apache-airflow-providers-common-sql`,
  `apache-airflow-providers-smtp`, and `apache-airflow-providers-standard`).
- Its `apache-tinkerpop` extra adds a 9th cycle member
  (`apache-airflow-providers-apache-tinkerpop==1.2.2`, which depends on `gremlinpython`) gated on
  `python_full_version < '3.14'`, while `tinkerpop` depends back on `apache-airflow` unconditionally.

## Setup

rules_pycross detects strongly connected components (SCCs) in `uv.lock` automatically. Instead of
collapsing the entire SCC into one `py_library`, it emits a `_raw_<pkg>` target per member (with
non-cycle dependencies only) and a `pycross_cycle_member_marker_deps` wrapper that evaluates
reachability from each entry member using the active Python version and platform markers. No manual
cycle configuration is needed.

[`MODULE.bazel`](MODULE.bazel):

```starlark
bazel_dep(name = "rules_pycross")
git_override(
    module_name = "rules_pycross",
    commit = "bd4800c5abacdfcc2a9053872f82e1bdd19ce22c",
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

On Python 3.14, depending on `@pypi//apache_airflow` brings in the active 8-package Airflow cycle
without pulling in `tinkerpop` or `gremlin_python`. Depending directly on
`@pypi//apache_airflow_providers_apache_tinkerpop` keeps `tinkerpop`, `gremlin_python`, and the
Airflow cycle it depends on.

## Friction / limitations

- **None for this scenario.** The shared `uv.lock` works unchanged, with no manual cycle list and
  no over- or under-inclusion across Python versions.
