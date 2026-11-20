# Dependency cycles: rules_py 2.0.0-alpha.11

The shared project ([`project/`](../project)) locks `unishell==2.3.3`, `unishell-unix==2.2.4`,
and `unishell-win==2.3.3`, with
[rules_py](https://github.com/aspect-build/rules_py) 2.0.0-alpha.11, Bazel 9.3.2, Python 3.12.

- `unishell` depends on `unishell-unix` on Linux/macOS (`sys_platform == 'darwin' or sys_platform == 'linux'`)
  and on `unishell-win` on Windows (`sys_platform == 'win32'`).
- Both `unishell-unix` and `unishell-win` depend back on `unishell` unconditionally.

## Setup

rules_py detects strongly connected components (SCCs) in `uv.lock` automatically and collapses
all three packages into one `py_library` target
(`//private/sccs:cycle__unishell__unishell_unix__unishell_win`). Every member alias in the hub
points at that single SCC target.

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

Run:

```sh
bazel test //...                   # passes for unishell and unishell_unix
bazel test //:unishell_win_test    # reproduces the dropped direct-dep bug
```

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:unishell_test` | pass | `unishell=True unishell_unix=True unishell_win=False` |
| `bazel test //...` | `//:unishell_unix_test` | pass | `unishell=True unishell_unix=True unishell_win=False` |
| `bazel test //:unishell_win_test` | `//:unishell_win_test` | **fail** | `unishell=True unishell_unix=True unishell_win=False` (`AssertionError: missing unishell_win (direct dep!)`) |

## What fails on marker-gated cycles

In `uv/private/extension/graph_utils.bzl` (`collect_sccs`), rules_py computes SCCs without looking
at environment markers, collapses `{unishell, unishell-unix, unishell-win}` into a single
`py_library`, and gates each member inside that SCC on the union of its **inbound intra-SCC edge
markers**:

- `unishell` has unconditional inbound edges from both platform packages, so it is always included.
- `unishell-unix` has inbound edge marker `sys_platform == 'darwin' or sys_platform == 'linux'`.
- `unishell-win` has only one inbound intra-SCC edge: `unishell -> unishell-win; sys_platform == 'win32'`.

Because `@pypi//unishell_win` aliases into the same shared SCC target, rules_py replaces
`unishell-win`'s own wheel with `:empty` on Linux even when a target depends directly on
`@pypi//unishell_win`. The build succeeds silently and fails at runtime when importing
`unishell_win`. (`//:unishell_win_test` is tagged `manual` so `bazel test //...` passes.)

## Friction / limitations

- **Marker-gated cycles silently drop direct dependencies.** Any cycle member whose inbound
  intra-SCC edges are inactive on the current platform or Python version disappears even when
  depended on directly.
- **No `MODULE.bazel` workaround on the shared lock.** Because SCC grouping happens automatically
  in the `uv` extension, there is no flag or override to keep per-entry reachability without
  editing `uv.lock`.
- Like other `rules_py` projects, targets must specify `dep_group = "cycle-app"` (or set a default
  in `.bazelrc`).
