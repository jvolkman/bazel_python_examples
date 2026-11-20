# Dependency cycles: rules_py 2.0.0-alpha.11

The shared project ([`project/`](../project)) depends on `kedro==1.8.0` and
`kedro-telemetry==0.9.0`, which depend on each other in PyPI metadata and in `uv.lock`, with
[rules_py](https://github.com/aspect-build/rules_py) 2.0.0-alpha.11, Bazel 9.3.2, Python 3.12.

## Setup

rules_py detects strongly connected components (SCCs) in `uv.lock` automatically and collapses
each cycle into a single synthetic `py_library` target (here
`//private/sccs:cycle__kedro__kedro_telemetry`) that unions both wheels and their dependencies.
Both `@pypi//kedro` and `@pypi//kedro_telemetry` alias into that SCC target. No manual cycle
configuration is needed.

[`MODULE.bazel`](MODULE.bazel):

```starlark
bazel_dep(name = "rules_py", version = "2.0.0-alpha.11")

interpreters = use_extension("@rules_py//py:extensions.bzl", "python_interpreters")
interpreters.toolchain(python_version = "3.12")
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

[`BUILD.bazel`](BUILD.bazel):

```starlark
py_test(
    name = "kedro_test",
    srcs = ["project/src/check_cycle.py"],
    args = ["kedro"],
    dep_group = "cycle-app",
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

Both tests verify that `kedro`, `kedro_telemetry`, `dynaconf`, and `requests` are importable when
depending on either side of the cycle alone.

## Friction / limitations

- **Works automatically on the shared `uv.lock`.** No manual cycle declarations are needed.
- Like other `rules_py` projects, targets must specify `dep_group = "cycle-app"` (or set a
  default in `.bazelrc`).
- `WhlInstall` prints a harmless `SyntaxError` while compiling Jinja/cookiecutter template `.py`
  files bundled inside the `kedro` wheel, then succeeds.
