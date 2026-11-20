# Dependency cycles: rules_python 2.5.1

The shared project ([`project/`](../project)) locks `unishell==2.3.3`, `unishell-unix==2.2.4`,
and `unishell-win==2.3.3`.

- `unishell` depends on `unishell-unix` on Linux/macOS (`sys_platform == 'darwin' or sys_platform == 'linux'`)
  and on `unishell-win` on Windows (`sys_platform == 'win32'`).
- Both `unishell-unix` and `unishell-win` depend back on `unishell` unconditionally.

**Summary:** `pip.parse(uv_lock = ...)` reads the shared `uv.lock`, but fails at analysis with
`cycle in dependency graph` unless cycles are listed by hand in `experimental_requirement_cycles`.
For a cross-platform cycle like `unishell`, listing all three packages causes Linux targets to
over-include `unishell_win`, while listing only `["unishell", "unishell-unix"]` passes on Linux
but leaves the Windows cycle broken.

## Setup

[`MODULE.bazel`](MODULE.bazel) (trimmed):

```starlark
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.12")

pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")
pip.parse(
    experimental_requirement_cycles = {
        "unishell": [
            "unishell",
            "unishell-unix",
        ],
    },
    hub_name = "pypi_cycles",
    python_version = "3.12",
    uv_lock = "//:project/uv.lock",
)
use_repo(pip, "pypi_cycles")
```

`MODULE.bazel` also defines:
- `@pypi_naive` (no `experimental_requirement_cycles`) for [`naive/BUILD.bazel`](naive/BUILD.bazel).
- `@pypi_cross_platform` (`["unishell", "unishell-unix", "unishell-win"]`) for
  [`cross_platform/BUILD.bazel`](cross_platform/BUILD.bazel).

Run:

```sh
bazel test //...                            # passes on Linux (only Unix cycle declared)
bazel build //naive:unishell_test           # reproduces the analysis cycle error
bazel test //cross_platform:unishell_test   # reproduces unishell_win over-inclusion on Linux
```

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:unishell_test` | pass | `unishell=True unishell_unix=True unishell_win=False` |
| `bazel test //...` | `//:unishell_unix_test` | pass | `unishell=True unishell_unix=True unishell_win=False` |
| `bazel test //...` | `//:unishell_win_test` | pass | `unishell=True unishell_unix=True unishell_win=True` |
| `bazel build //naive:unishell_test` | `//naive:unishell_test` | analysis error | `cycle in dependency graph` (`unishell -> unishell_unix -> unishell`) |
| `bazel test //cross_platform:unishell_test` | `//cross_platform:unishell_test` | **fail** | `unishell=True unishell_unix=True unishell_win=True` (`AssertionError: unexpected unishell_win on Linux`) |

## What happened with the naive and cross-platform setups

1. **Naive (`@pypi_naive`):** fails during analysis with `cycle in dependency graph` on
   `unishell -> unishell_unix -> unishell`.
2. **Cross-platform (`@pypi_cross_platform`):** declaring all three packages in
   `experimental_requirement_cycles` avoids a cycle error on both Linux and Windows, but collapses
   all three into one group target unconditionally — so `//cross_platform:unishell_test` pulls
   `unishell_win` into Linux builds even though `unishell` only depends on it under
   `sys_platform == 'win32'`.

## Friction / limitations

- **Cycles must be listed by hand.** Whenever a lock update introduces a new cycle (or adds a
  package to an existing one), builds fail until `experimental_requirement_cycles` is updated.
- **No marker-aware cycles.** `experimental_requirement_cycles` is a static list, so a
  cross-platform cycle forces a tradeoff: omit the Windows package (breaks Windows builds) or
  include it (over-includes it on Linux/macOS).
- **Overlapping cycles must be merged manually.** If `a <-> b` and `a <-> c` both exist, they must
  be collapsed into a single entry by hand.
