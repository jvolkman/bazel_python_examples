# Building C-extension sdists with rules_py 2.0.0-alpha.11

This module builds the two sdist-only C extensions in [`project/`](../project) (`crcmod==1.7` and
`datrie==0.8.3`) using rules_py 2.0.0-alpha.11 on Bazel 9.3.2 and Python 3.14. See
[`sdists/README.md`](../README.md) for the scenario overview.

## Setup

rules_py compiles sdists hermetically in sandboxed Bazel build actions (`pep517_native_whl`,
auto-detected by its `detect_native.py` configure tool) using Bazel's CC toolchain. However, it
has no separate `build_tools_repo` or override lock mechanism: every build dependency (`build`,
`setuptools`, `wheel`, and `cython`) must be locked inside the same `uv.lock`. Auto-discovered
build requirements from `detect_native.py` (`setuptools`, `wheel`, `cython`) resolve from an
internal `private/build_deps` graph independent of `dep_group`, whereas
`default_build_dependencies` (which defaults to `["build"]`) and `uv.annotate_packages` resolve
through surface aliases that must be active in the consuming `dep_group`.

Following rules_py's own sdist e2e tests, [`bazel_project/pyproject.toml`](bazel_project/pyproject.toml)
copies `project/pyproject.toml`, adds `build`, `setuptools`, `wheel`, and `cython` to
`[project].dependencies`, and relocks [`bazel_project/uv.lock`](bazel_project/uv.lock).

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
    lock = "//bazel_project:uv.lock",
    pyproject = "//bazel_project:pyproject.toml",
)
use_repo(uv, "pypi")
```

[`.bazelrc`](.bazelrc) selects Python 3.14 (`common --@rules_py//py:python_version=3.14`), and
[`BUILD.bazel`](BUILD.bazel) sets `dep_group = "sdist-app"` on `py_test`:

```starlark
py_test(
    name = "sdist_test",
    srcs = ["project/src/check_sdists.py"],
    dep_group = "sdist-app",
    main = "project/src/check_sdists.py",
    deps = [
        "@pypi//crcmod",
        "@pypi//datrie",
    ],
)
```

Run: `bazel test //...`

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:sdist_test` | pass | Both `crcmod._crcfunext` and `datrie` compiled hermetically as `.so` extensions via `pep517_native_whl` |

## What happened with the naive approaches

1. **Shared `project/pyproject.toml` + `project/uv.lock`**: fails during module extension
   evaluation because `build` is not in the lock:

```text
Error in fail: Unable to resolve a default version for requirement "build" in @@//:project/uv.lock
```

2. **Putting `build`, `setuptools`, `wheel`, and `cython` in a separate `[dependency-groups] build-tools` group**:
   - Without an `app` group in `[dependency-groups]`, rules_py drops `[project].dependencies`, so
     `@pypi//crcmod` disappears from the hub.
   - With both `app` and `build-tools` groups in `[dependency-groups]`, `py_test(dep_group = "app")`
     fails at analysis time because the generated `//:build` alias only matches `build-tools`:

```text
ERROR: .../@rules_py++uv+project__sdist_app/BUILD.bazel:39:6: configurable attribute "actual" in
  @@rules_py++uv+project__sdist_app//:build doesn't match this configuration.
Conditions checked:
 @@rules_py++uv+project__sdist_app//private/dep_group:build-tools
```

## Friction / limitations

- **Cannot use `project/uv.lock` unmodified.** rules_py has no separate build-tools lock or repo;
  you must lock `build`, `setuptools`, `wheel`, and `cython` in the same lockfile.
- **`default_build_dependencies` (including `build`) must share the runtime `dep_group`.**
  Auto-discovered backends (`setuptools`, `wheel`, `cython`) resolve from `private/build_deps`
  regardless of `dep_group`, but `//:build` (and any `default_build_dependencies` or
  `uv.annotate_packages` build deps) select on the active `dep_group`. Putting `build` only in a
  separate `[dependency-groups]` group makes `//:build` unreachable under the app's `dep_group`.
- **Sdist compilation itself works well once dependencies are locked.** `detect_native.py`
  automatically detected native sources in both `crcmod` and `datrie` (including `datrie`'s
  `build_clib` static library and Cython dependency) and compiled both hermetically with Bazel's
  CC toolchain.
