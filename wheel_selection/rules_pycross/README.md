# Wheel selection across glibc and musl with rules_pycross 2.2.0

This module tests wheel selection for [`project/`](../project) (`bcrypt==5.0.0` and `cbor2==6.3.0`)
using [rules_pycross](https://github.com/jvolkman/rules_pycross) 2.2.0 and
rules_python 2.5.1 (toolchain and `py_test`), on Bazel 9.3.2 and Python 3.14. See
[`wheel_selection/README.md`](../README.md) for the scenario overview.

## Setup

rules_pycross performs PEP 425 wheel selection at **analysis time** (`pycross_wheel_chooser`,
backed by `@pypackaging.bzl`'s port of `packaging.tags`), using:

- `@rules_pycross//pycross/settings:glibc_version` (defaults to `2.28`, deterministic across hosts)
- `@rules_pycross//pycross/settings:musl_version` (defaults to `1.2`)
- `@rules_python//python/config_settings:py_linux_libc` (`glibc` or `musl`)

One `uv.workspace` and `uv.repo` handles every combination without changing `MODULE.bazel`.

[`MODULE.bazel`](MODULE.bazel):

```starlark
bazel_dep(name = "rules_pycross", version = "2.2.0")
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.14")

uv = use_extension("@rules_pycross//pycross/extensions:uv.bzl", "uv")
uv.workspace(name = "pypi", lock_file = "//:project/uv.lock")
uv.package(name = "*", build_mode = "never", workspace = "pypi")
uv.repo(name = "pypi", workspace = "pypi")
use_repo(uv, "pypi")
```

[`BUILD.bazel`](BUILD.bazel) runs `bcrypt_default_test` and `cbor2_default_test` directly, and uses
a small Starlark transition ([`transition.bzl`](transition.bzl)) to inspect `@pypi//bcrypt:wheel`
and `@pypi//cbor2:wheel` under glibc `2.17`, glibc `2.34`, musl `1.2`, and musl `1.1` in a single
`bazel test //...` run.

Run:

```sh
bazel test //...
bazel build //:cbor2_glibc_2_17_whl
bazel build //:cbor2_glibc_2_17_whl --@rules_pycross//pycross/settings:unavailable_package_mode=fail_at_execution
```

## Result

| Target | Configuration | Selected wheel tag |
| --- | --- | --- |
| `//:bcrypt_default_test` | Default (`glibc 2.28`) | `cp39-abi3-manylinux_2_28_x86_64` |
| `//:cbor2_default_test` | Default (`glibc 2.28`) | `cp314-cp314-manylinux_2_28_x86_64` |
| `//:bcrypt_glibc_2_17_test` | `glibc_version=2.17` | `cp39-abi3-manylinux_2_17_x86_64` |
| `//:bcrypt_glibc_2_34_test` | `glibc_version=2.34` | `cp39-abi3-manylinux_2_34_x86_64` |
| `//:bcrypt_musl_1_2_test` | `py_linux_libc=musl`, `musl_version=1.2` | `cp39-abi3-musllinux_1_2_x86_64` |
| `//:bcrypt_musl_1_1_test` | `py_linux_libc=musl`, `musl_version=1.1` | `cp39-abi3-musllinux_1_1_x86_64` |
| `//:cbor2_musl_1_2_test` | `py_linux_libc=musl`, `musl_version=1.2` | `cp314-cp314-musllinux_1_2_x86_64` |
| `//:cbor2_glibc_2_17_whl` (`manual`) | `glibc_version=2.17`, `build_mode="never"` | Rejected cleanly (`@platforms//:incompatible`, or execution error under `fail_at_execution`) |

All 7 tests pass in one `bazel test //...` invocation.

## Behavior when no wheel fits the glibc cap

`cbor2==6.3.0` publishes only `manylinux_2_28` and `musllinux_1_2` wheels (no `manylinux_2_17`).
Under `glibc_version=2.17` with `build_mode = "never"`, `bazel build //:cbor2_glibc_2_17_whl`
rejects `cbor2` cleanly instead of silently shipping a `manylinux_2_28` wheel:

- Default (`unavailable_package_mode=incompatible`): marked `@platforms//:incompatible`.
- With `--@rules_pycross//pycross/settings:unavailable_package_mode=fail_at_execution`: fails with
  `No compatible wheel is available for cbor2@6.3.0 in the selected target environment.`

Without `build_mode = "never"` (the default `build_mode = "auto"`), rules_pycross automatically
falls back to building `cbor2` from its sdist using Bazel's CC toolchain.

## Friction / limitations

- Default `glibc_version` is `2.28` (`DEFAULT_GLIBC_VERSION`), which is deterministic across build
  hosts. If you want `manylinux_2_34` wheels by default, set `pycross.configure_toolchains(glibc_version = "2.34")`
  in `MODULE.bazel` or pass `--@rules_pycross//pycross/settings:glibc_version=2.34`.
