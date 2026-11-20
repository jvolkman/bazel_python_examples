# Building C-extension sdists with rules_pycross 2.2.0

This module builds the two sdist-only C extensions in [`project/`](../project) (`crcmod==1.7` and
`datrie==0.8.3`) using [rules_pycross](https://github.com/jvolkman/rules_pycross) 2.2.0 and
rules_python 2.5.1 (toolchain and `py_test`), on Bazel 9.3.2 and Python 3.12. See
[`sdists/README.md`](../README.md) for the scenario overview.

## Setup

rules_pycross builds sdists hermetically in sandboxed Bazel build actions (`PycrossPep517Build`)
using Bazel's CC toolchain, then repairs the resulting wheels (`manylinux`). Because `uv.lock`
does not lock `[build-system].requires`, PEP 517 backends (`setuptools`, `wheel`, `cython`) must
come from a lockfile. rules_pycross ships the PyPA `build` frontend internally, and resolves build
backends in either of two ways:

- **Same lockfile (no separate lock needed):** add `setuptools`, `wheel`, and `cython` to a
  `[dependency-groups]` group (for example `build`) in your main `pyproject.toml` and lock it into
  `uv.lock`. rules_pycross's auto-generated `<workspace>__build` repo picks them up automatically
  while keeping them out of `@pypi` (which only exposes `default` dependencies).
- **Optional separate `build_tools_repo` (used below):** point
  `uv.package(name = "*", build_tools_repo = "build_tools")` at a separate, reusable
  [`build_tools/uv.lock`](build_tools/uv.lock). This module uses `build_tools_repo` so the shared
  `project/uv.lock` stays completely untouched across all three rulesets.

[`MODULE.bazel`](MODULE.bazel) (trimmed):

```starlark
bazel_dep(name = "rules_pycross", version = "2.2.0")
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.12")

uv = use_extension("@rules_pycross//pycross/extensions:uv.bzl", "uv")

uv.workspace(name = "build_tools", lock_file = "//build_tools:uv.lock")
uv.repo(name = "build_tools", workspace = "build_tools")

uv.workspace(name = "pypi", lock_file = "//:project/uv.lock")
uv.repo(name = "pypi", workspace = "pypi")
uv.package(
    name = "*",
    build_tools_repo = "build_tools",
    workspace = "pypi",
)
use_repo(uv, "build_tools", "pypi")
```

[`BUILD.bazel`](BUILD.bazel):

```starlark
py_test(
    name = "sdist_test",
    srcs = ["project/src/check_sdists.py"],
    main = "project/src/check_sdists.py",
    deps = [
        "@pypi//crcmod",
        "@pypi//datrie",
    ],
)
```

Run:

```sh
bazel test //...
bazel build //naive:sdist_test   # reproduces missing build-tools error
```

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:sdist_test` | pass | Both `crcmod._crcfunext` and `datrie` compiled as `.so` extensions via Bazel's CC toolchain and repaired (`manylinux1_x86_64` / `manylinux2014_x86_64`) |
| `bazel build //naive:sdist_test` | `//naive:sdist_test` | build error | `build._exceptions.BuildBackendException: Backend 'setuptools.build_meta:__legacy__' is not available.` |

## What happened with the naive approach

Without `build_tools_repo` (reproduced by [`naive/BUILD.bazel`](naive/BUILD.bazel)), rules_pycross
looks for `setuptools`, `wheel`, and `cython` in the auto-generated `pypi_naive__build` repo,
which only contains packages from `project/uv.lock`. Because `project/uv.lock` has only `crcmod`
and `datrie`, the sandboxed PEP 517 build action fails cleanly without reaching out to PyPI:

```text
build._exceptions.BuildBackendException: Backend 'setuptools.build_meta:__legacy__' is not available.
```

## Friction / limitations

- **Requires locking build backends.** Because `uv.lock` omits `[build-system].requires` and
  rules_pycross intentionally does not download unpinned build tools from PyPI during builds, you
  need to lock `setuptools`, `wheel`, and `cython` either in a separate `build_tools` lockfile (as
  shown here) or in a `build` dependency group inside your main project (which stays out of `@pypi`
  while `<workspace>__build` picks it up automatically).
- **Bug found and fixed while writing this example.** `datrie` uses `setuptools` `build_clib` to
  archive `libdatrie.a` with `ar`. Prior to rules_pycross 2.2.0 (PR #402), `extract_cc_layer` passed
  `output_file = None` to `cc_common.create_link_variables`, so `rules_cc` omitted `archiver_flags`
  and `rules_pycross` exported `ARFLAGS=""`, failing with `/usr/bin/ar: invalid option -- '/'`.
