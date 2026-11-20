# Dependency cycles: rules_pycross (`main`)

The shared project ([`project/`](../project)) depends on `kedro==1.8.0` and
`kedro-telemetry==0.9.0`, which depend on each other in PyPI metadata and in `uv.lock`, with
[rules_pycross](https://github.com/jvolkman/rules_pycross) pinned to `main` (`bd4800c5`) and
rules_python 2.5.1 (toolchain and `py_test`), Bazel 9.3.2, Python 3.12.

## Setup

rules_pycross detects strongly connected components (SCCs) in `uv.lock` automatically. For each
member of a cycle, it emits a `_raw_<pkg>` target holding only non-cycle dependencies and a
`pycross_cycle_member_marker_deps` wrapper that resolves intra-cycle edges per target
configuration. No `MODULE.bazel` cycle declarations are needed.

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
python.toolchain(is_default = True, python_version = "3.12")

uv = use_extension("@rules_pycross//pycross/extensions:uv.bzl", "uv")
uv.workspace(name = "pypi", lock_file = "//:project/uv.lock")
use_repo(uv, "pypi")
```

[`BUILD.bazel`](BUILD.bazel):

```starlark
py_test(
    name = "kedro_test",
    srcs = ["project/src/check_cycle.py"],
    args = ["kedro"],
    main = "project/src/check_cycle.py",
    deps = ["@pypi//kedro"],
)
# telemetry_test: the same with @pypi//kedro_telemetry and args = ["kedro_telemetry"].
```

Run: `bazel test //...`

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:kedro_test` | pass | `entry=kedro kedro=1.8.0 kedro_telemetry=0.9.0` |
| `bazel test //...` | `//:telemetry_test` | pass | `entry=kedro_telemetry kedro=1.8.0 kedro_telemetry=0.9.0` |

Both tests verify that `kedro`, `kedro_telemetry`, `dynaconf` (unique to `kedro`), and `requests`
(unique to `kedro-telemetry`) are all importable when depending on either side of the cycle alone.

## Friction / limitations

- **None for this scenario.** The shared `uv.lock` works unchanged with no manual cycle list.
- Because intra-cycle edges stay marker-aware inside `pycross_cycle_member_marker_deps`, a
  marker-gated back-edge only pulls in the rest of the cycle on platforms/Python versions where
  that marker actually matches.
