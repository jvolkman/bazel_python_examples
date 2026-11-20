# Wheel selection across glibc and musl with rules_py 2.0.0-alpha.11

This module tests wheel selection for [`project/`](../project) (`bcrypt==5.0.0` and `cbor2==6.3.0`)
using [rules_py](https://github.com/aspect-build/rules_py) 2.0.0-alpha.11 on Bazel 9.3.2 and
Python 3.12. See [`wheel_selection/README.md`](../README.md) for the scenario overview.

## Setup

rules_py expands every wheel's `(python, platform, abi)` triples at **repository-generation time**
and emits a sequential `select_chain` alias ladder ordered by a heuristic `select_key` (preferring
higher matching versions, matching `pip`/`uv`). Its platform flags live under a private package:

- `@rules_py//uv/private/constraints/platform:platform_libc` (defaults to `CURRENT_PLATFORM_LIBC`
  from `@rules_py_uv_host`)
- `@rules_py//uv/private/constraints/platform:platform_version` (defaults to
  `CURRENT_PLATFORM_VERSION` from `@rules_py_uv_host`, probed from the host machine's glibc,
  `2.43` on this machine)

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

[`BUILD.bazel`](BUILD.bazel) runs `bcrypt_default_test` and `cbor2_default_test` directly, and uses
a Starlark transition ([`transition.bzl`](transition.bzl)) setting `@pypi//dep_group`,
`platform_libc`, and `platform_version` to inspect `@pypi//bcrypt:whl` and `@pypi//cbor2:whl`
across glibc `2.17`, `2.28`, `2.34`, and musl `1.2` / `1.1`.

Run:

```sh
bazel test //...
bazel build //:cbor2_glibc_2_17_whl
```

## Result

| Target | Configuration | Selected wheel tag |
| --- | --- | --- |
| `//:bcrypt_default_test` | Default (host-probed `glibc 2.43`) | `cp39-abi3-manylinux_2_34_x86_64` |
| `//:cbor2_default_test` | Default (host-probed `glibc 2.43`) | `cp312-cp312-manylinux_2_28_x86_64` |
| `//:bcrypt_glibc_2_17_test` | `platform_libc=glibc`, `platform_version=2.17` | `cp39-abi3-manylinux_2_17_x86_64` |
| `//:bcrypt_glibc_2_28_test` | `platform_libc=glibc`, `platform_version=2.28` | `cp39-abi3-manylinux_2_28_x86_64` |
| `//:bcrypt_glibc_2_34_test` | `platform_libc=glibc`, `platform_version=2.34` | `cp39-abi3-manylinux_2_34_x86_64` |
| `//:bcrypt_musl_1_2_test` | `platform_libc=musl`, `platform_version=1.2` | `cp39-abi3-musllinux_1_2_x86_64` |
| `//:bcrypt_musl_1_1_test` | `platform_libc=musl`, `platform_version=1.1` | `cp39-abi3-musllinux_1_1_x86_64` |
| `//:cbor2_musl_1_2_test` | `platform_libc=musl`, `platform_version=1.2` | `cp312-cp312-musllinux_1_2_x86_64` |
| `//:cbor2_glibc_2_17_whl` (`manual`) | `platform_libc=glibc`, `platform_version=2.17` | Falls back to sdist build (`No module named build`) |

All 8 tests pass in one `bazel test //...` invocation.

## Friction / limitations

- **Host-dependent defaults.** `@rules_py_uv_host` probes the build host's glibc version (`2.43`
  here) to set the default of `platform_version`. Two machines running different Linux distros
  (e.g. Debian 11 with glibc 2.31 vs Ubuntu 24.04 with glibc 2.39) silently select different
  `bcrypt` wheels (`manylinux_2_28` vs `manylinux_2_34`) from the same lockfile unless you pin
  `platform_version` in `.bazelrc` or `platform(flags = ...)`.
- **Flags live under `//uv/private/...` and are not tied to `--platforms`.** Switching libc or
  glibc version requires passing `@rules_py//uv/private/constraints/platform:platform_libc` and
  `platform_version` explicitly (there are no public flag aliases yet).
- **No `build_mode = "never"` / wheel-only guard.** When `cbor2` has no wheel matching `glibc 2.17`,
  the `select_chain` falls through to `:source_built_wheel`, which fails at build time with
  `No module named build` unless `build` and PEP 517 backends are locked in `[project].dependencies`.
