# Dependency cycles: rules_python 2.5.1

The shared project ([`project/`](../project)) depends on `kedro==1.8.0` and
`kedro-telemetry==0.9.0`, which depend on each other in PyPI metadata and in `uv.lock`.

**Summary:** `pip.parse(uv_lock = ...)` reads the shared `uv.lock`, but fails at analysis with
`cycle in dependency graph` unless every cycle is declared by hand in
`experimental_requirement_cycles`. Once declared, both `//:kedro_test` and `//:telemetry_test`
pass in one `bazel test //...`.

## Setup

[`MODULE.bazel`](MODULE.bazel) (trimmed):

```starlark
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.12")

pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")
pip.parse(
    experimental_requirement_cycles = {
        "kedro": [
            "kedro",
            "kedro-telemetry",
        ],
    },
    hub_name = "pypi_cycles",
    python_version = "3.12",
    uv_lock = "//:project/uv.lock",
)
use_repo(pip, "pypi_cycles")
```

[`BUILD.bazel`](BUILD.bazel):

```starlark
py_test(
    name = "kedro_test",
    srcs = ["project/src/check_cycle.py"],
    args = ["kedro"],
    main = "project/src/check_cycle.py",
    deps = ["@pypi_cycles//kedro"],
)
# telemetry_test: the same with @pypi_cycles//kedro_telemetry and args = ["kedro_telemetry"].
```

`MODULE.bazel` also defines `@pypi_naive` (the same `pip.parse` without
`experimental_requirement_cycles`) for [`naive/BUILD.bazel`](naive/BUILD.bazel).

Run:

```sh
bazel test //...                # working setup with experimental_requirement_cycles
bazel build //naive:kedro_test  # reproduces the cycle error
```

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:kedro_test` | pass | `entry=kedro kedro=1.8.0 kedro_telemetry=0.9.0` |
| `bazel test //...` | `//:telemetry_test` | pass | `entry=kedro_telemetry kedro=1.8.0 kedro_telemetry=0.9.0` |
| `bazel build //naive:kedro_test` | `//naive:kedro_test` | analysis error | `cycle in dependency graph` (`kedro -> kedro_telemetry -> kedro`) |

## What happened with the naive approach

Pointing `pip.parse(uv_lock = ...)` at the shared lock without declaring cycles fails during
analysis:

```
ERROR: .../external/rules_python++pip+pypi_naive_312_kedro_py3_none_any_7379554b/BUILD.bazel:7:20:
  in py_library rule @@rules_python++pip+pypi_naive_312_kedro_py3_none_any_7379554b//:pkg: cycle in dependency graph:
.-> @@rules_python++pip+pypi_naive_312_kedro_py3_none_any_7379554b//:pkg
|   @@rules_python++pip+pypi_naive//kedro_telemetry:pkg
|   @@rules_python++pip+pypi_naive_312_kedro_telemetry_py3_none_any_88238665//:pkg
|   @@rules_python++pip+pypi_naive//kedro:pkg
`-- @@rules_python++pip+pypi_naive_312_kedro_py3_none_any_7379554b//:pkg
```

## Friction / limitations

- **Cycles must be listed by hand.** Whenever a lock update introduces a new cycle (or adds a
  package to an existing one), builds fail until you update `experimental_requirement_cycles` in
  `MODULE.bazel`.
- **Overlapping cycles must be merged manually.** As documented on `pip.parse`, if `a <-> b` and
  `a <-> c` both exist, you cannot list them as two separate entries — you must collapse them into
  one group yourself.
- **Uses the shared `uv.lock` as-is.** No `uv export` step is needed here because the lock has no
  `[tool.uv] conflicts` or multi-group selection.
