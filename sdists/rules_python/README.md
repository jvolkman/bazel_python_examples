# Building C-extension sdists with rules_python 2.5.1

This module builds the two sdist-only C extensions in [`project/`](../project) (`crcmod==1.7` and
`datrie==0.8.3`) using rules_python 2.5.1 on Bazel 9.3.2 and Python 3.12. See
[`sdists/README.md`](../README.md) for the scenario overview.

## Setup

rules_python compiles sdists inside repository fetch rules (`pip_archive` -> `pip --isolated wheel`)
using the host compiler and live PyPI network access for `[build-system].requires` (`setuptools`,
`wheel`, `cython`). Because `python-build-standalone` bakes `/tools/llvm/bin/llvm-ar` into
`sysconfig`'s `AR` variable, any `setuptools` `build_clib` package (`datrie`) fails unless you
override `AR` to the host `ar` via `environment = {"AR": "ar"}`.

[`MODULE.bazel`](MODULE.bazel) (trimmed):

```starlark
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.12")

pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")
pip.parse(
    environment = {"AR": "ar"},
    hub_name = "pypi",
    python_version = "3.12",
    uv_lock = "//:project/uv.lock",
)
use_repo(pip, "pypi")
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
bazel build //naive:sdist_test   # reproduces /tools/llvm/bin/llvm-ar failure
```

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:sdist_test` | pass | Both `crcmod._crcfunext` and `datrie` compiled as `.so` extensions during repo fetch |
| `bazel build //naive:sdist_test` | `//naive:sdist_test` | fetch error | `error: [Errno 2] No such file or directory: '/tools/llvm/bin/llvm-ar'` |

## What happened with the naive approach

Without `environment = {"AR": "ar"}` (and with `--no-cache-dir` so host pip wheel cache cannot mask
it, reproduced in [`naive/BUILD.bazel`](naive/BUILD.bazel)), `crcmod` builds with host `clang`,
then `datrie` fails in `build_clib`:

```text
/tools/llvm/bin/llvm-ar rcs build/temp.linux-x86_64-cpython-312/libdatrie.a ...
error: [Errno 2] No such file or directory: '/tools/llvm/bin/llvm-ar'
```

## Friction / limitations

- **Non-hermetic repo-rule builds.** Sdists compile during repository fetch on the host machine
  with host `clang` and `ar`, downloading unpinned `setuptools`, `wheel`, and `cython` from PyPI at
  fetch time. This cannot run on RBE, breaks offline/air-gapped builds, and cannot cross-compile.
- **Host `~/.cache/pip` leakage.** `pip_archive` runs `pip --isolated wheel` without
  `--no-cache-dir`, so wheels built in one hub are written into the host user's `~/.cache/pip/wheels`
  and silently reused by other hubs (even one missing `environment = {"AR": "ar"}`). That is why
  `pypi_naive` passes `extra_pip_args = ["--no-cache-dir"]` to reliably reproduce the clean-machine
  failure.
- **Broken default `AR` for `build_clib`.** `python-build-standalone` records
  `/tools/llvm/bin/llvm-ar` in `sysconfig`, and `pip_archive` does not override `AR` (unlike its
  macOS/Unix `CFLAGS` workarounds in `whl_library.bzl`).
