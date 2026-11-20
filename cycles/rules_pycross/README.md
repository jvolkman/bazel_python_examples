# Dependency cycles: rules_pycross (`main`)

The shared project ([`project/`](../project)) locks `unishell==2.3.3`, `unishell-unix==2.2.4`,
and `unishell-win==2.3.3`, with
[rules_pycross](https://github.com/jvolkman/rules_pycross) pinned to `main` (`bd4800c5`) and
rules_python 2.5.1 (toolchain and `py_test`), Bazel 9.3.2, Python 3.12.

- `unishell` depends on `unishell-unix` on Linux/macOS (`sys_platform == 'darwin' or sys_platform == 'linux'`)
  and on `unishell-win` on Windows (`sys_platform == 'win32'`).
- Both `unishell-unix` and `unishell-win` depend back on `unishell` unconditionally.

## Setup

rules_pycross detects strongly connected components (SCCs) in `uv.lock` automatically. Instead of
collapsing the entire SCC into one `py_library`, it emits a `_raw_<pkg>` target per member (with
non-cycle dependencies only) and a `pycross_cycle_member_marker_deps` wrapper that evaluates
reachability from each entry member using the active target platform's markers. No manual cycle
configuration is needed.

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
    name = "unishell_test",
    srcs = ["project/src/check_cycle.py"],
    args = ["unishell"],
    main = "project/src/check_cycle.py",
    deps = ["@pypi//unishell"],
)
# unishell_unix_test: the same with @pypi//unishell_unix and args = ["unishell_unix"].
# unishell_win_test:  the same with @pypi//unishell_win  and args = ["unishell_win"].
```

Run: `bazel test //...`

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:unishell_test` | pass | `unishell=True unishell_unix=True unishell_win=False` |
| `bazel test //...` | `//:unishell_unix_test` | pass | `unishell=True unishell_unix=True unishell_win=False` |
| `bazel test //...` | `//:unishell_win_test` | pass | `unishell=True unishell_unix=True unishell_win=True` |

On Linux, depending on `@pypi//unishell` or `@pypi//unishell_unix` pulls in both Unix-active sides
of the cycle without over-including `unishell_win`. Depending directly on `@pypi//unishell_win`
keeps `unishell_win` itself and follows its unconditional edge to `unishell` (and `unishell_unix`).

## Friction / limitations

- **None for this scenario.** The shared cross-platform `uv.lock` works unchanged, with no manual
  cycle list and no over- or under-inclusion across platforms.
