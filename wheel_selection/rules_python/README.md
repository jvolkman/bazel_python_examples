# Wheel selection across glibc and musl with rules_python 2.5.1

This module tests wheel selection for [`project/`](../project) (`bcrypt==5.0.0` and `cbor2==6.3.0`)
using rules_python 2.5.1 on Bazel 9.3.2 and Python 3.12. See
[`wheel_selection/README.md`](../README.md) for the scenario overview.

## Setup

rules_python performs wheel selection at **module-extension time** (`select_whl.bzl`) over a fixed
list of platforms from `default_platforms()` and user `pip.default(...)` calls:

- Built-in Linux platforms are **glibc-only** with an uncapped `manylinux_*` glob.
- `select_whl.bzl` uses **Minimal Version Selection** (`(-major, -minor)`), picking the *lowest*
  matching `manylinux` / `musllinux` version rather than the highest compatible one (opposite of
  `pip` and `uv`).
- Targeting a specific glibc cap (like `2.17`) or musl/Alpine (`musllinux_1_2` / `musllinux_1_1`)
  requires defining custom `pip.default(...)` platforms keyed on custom `config_setting`s and
  listing them in `pip.parse(target_platforms = [...])`.

[`MODULE.bazel`](MODULE.bazel) defines `@pypi_default` (the out-of-the-box `pip.parse(uv_lock = ...)`)
and `@pypi_custom` (four custom `pip.default` platforms for glibc `2.17`, glibc `2.34`, musl `1.2`,
and musl `1.1`, with `download_only = True`).

Run:

```sh
bazel test //...
bazel build //:cbor2_glibc_2_17_whl
```

## Result

| Target | Hub / platform | Selected wheel tag |
| --- | --- | --- |
| `//:bcrypt_default_test` | `@pypi_default` (`linux_x86_64`) | `cp39-abi3-manylinux_2_17_x86_64` (MVS lowest) |
| `//:cbor2_default_test` | `@pypi_default` (`linux_x86_64`) | `cp312-cp312-manylinux_2_28_x86_64` (uncapped `manylinux_*`) |
| `//:bcrypt_glibc_2_17_test` | `@pypi_custom` (`manylinux_2_17_x86_64`) | `cp39-abi3-manylinux_2_17_x86_64` |
| `//:bcrypt_glibc_2_34_test` | `@pypi_custom` (`manylinux_2_34_x86_64`) | `cp39-abi3-manylinux_2_17_x86_64` (MVS still picks `2_17`, not `2_34`) |
| `//:bcrypt_musl_1_2_test` | `@pypi_custom` (`musllinux_1_2_x86_64`) | `cp39-abi3-musllinux_1_1_x86_64` (MVS still picks `1_1`, not `1_2`) |
| `//:bcrypt_musl_1_1_test` | `@pypi_custom` (`musllinux_1_1_x86_64`) | `cp39-abi3-musllinux_1_1_x86_64` |
| `//:cbor2_musl_1_2_test` | `@pypi_custom` (`musllinux_1_2_x86_64`) | `cp312-cp312-musllinux_1_2_x86_64` |
| `//:cbor2_glibc_2_17_whl` (`manual`) | `@pypi_custom` (`manylinux_2_17_x86_64`) | Analysis error (`No matching wheel for current configuration's Python version and platform`) |

All 7 tests pass in one `bazel test //...` invocation.

## Friction / limitations

- **Uncapped default glibc combined with MVS.** Out of the box, `@pypi_default` picks
  `manylinux_2_17` for `bcrypt` while silently picking `manylinux_2_28` for `cbor2`, because
  `manylinux_*` has no upper glibc limit. There is no flag to set a glibc floor without replacing
  `pip.default(...)`.
- **No built-in musl / Alpine platforms.** `default_platforms()` defines glibc-only Linux
  platforms; musl requires hand-authoring `pip.default(platform = ..., whl_platform_tags = ["musllinux_1_2_x86_64"], ...)`
  and setting `target_platforms = [...]` on `pip.parse`.
- **Minimal Version Selection cannot opt into newer wheels when older ones exist.** Even on a
  custom platform configured with `whl_platform_tags = ["manylinux_2_34_x86_64"]` or
  `["musllinux_1_2_x86_64"]`, `select_whl.bzl` treats the tag as an upper bound and prefers the
  lowest compatible wheel (`manylinux_2_17` and `musllinux_1_1` for `bcrypt`).
- **Pre-declared platform matrix.** Every `(os, arch, libc, version)` combination you want to build
  must be declared up front in `MODULE.bazel`.
