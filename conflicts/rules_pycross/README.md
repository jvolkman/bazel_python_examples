# Conflicts: rules_pycross (`main`)

uv `conflicts` between the `cpu` and `cu132` extras of the shared
[`project/`](../project) (one `uv.lock`, two torch builds), with
[rules_pycross](https://github.com/jvolkman/rules_pycross) pinned to `main` (`bd4800c5`) and
rules_python 2.5.1 (toolchain only), Bazel 9.3.2, Python 3.12.

## Setup

rules_pycross reads the uv lock's `conflicts` table itself. Each conflicting item becomes a
`bool_flag` in the generated repo (`@<repo>//_variants:extra_cpu`, `...:extra_cu132`), and the
lock's conflict markers (`extra == 'extra-9-torch-app-cpu'`) select on those flags. When a
`uv.repo` requests only one item from a conflict set (`optional:cpu` or `optional:cu132`),
rules_pycross selects it automatically with a repo transition, so no `flags` attribute is needed.
Two repos over the same workspace give one CPU view and one CUDA view, and both build in one
invocation. All repos share one backing package repo (`@<workspace>__pkgs`), so
variant-independent packages like numpy are fetched and installed once.

[`MODULE.bazel`](MODULE.bazel) (trimmed):

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
uv.workspace(name = "torch", lock_file = "//:project/uv.lock")

# Per-variant views: each requests one extra, so the variant is selected automatically.
uv.repo(
    name = "torch_cpu",
    dependency_groups = ["default", "optional:cpu"],
    workspace = "torch",
)
uv.repo(
    name = "torch_cu132",
    dependency_groups = ["default", "optional:cu132"],
    workspace = "torch",
)
use_repo(uv, "torch_cpu", "torch_cu132")
```

[`BUILD.bazel`](BUILD.bazel) (plain rules_python `py_test`):

```starlark
py_test(
    name = "torch_cpu_test",
    srcs = ["project/src/check_torch.py"],
    args = ["cpu"],
    main = "project/src/check_torch.py",
    deps = ["@torch_cpu//numpy", "@torch_cpu//torch"],
)
# torch_cu132_test: the same with @torch_cu132 and args = ["cu132"].
```

There is no pycross-specific toolchain setup. rules_pycross picks up the registered rules_python
toolchain (3.12) and registers its own toolchains automatically. The MODULE.bazel also keeps the
unpinned `@pypi` repo used by [`naive/`](naive/BUILD.bazel).

Run:

```sh
bazel test //...                      # both variants, no flags
bazel test //naive:torch_test --@pypi//_variants:extra_cpu=True --test_arg=cpu
bazel test //naive:torch_test --@pypi//_variants:extra_cu132=True --test_arg=cu132
```

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:torch_cpu_test` | pass | `torch 2.15.0+cpu (cuda=None), numpy 2.5.5` |
| `bazel test //...` | `//:torch_cu132_test` | pass | `torch 2.15.0+cu132 (cuda=13.2), numpy 2.5.5` |
| `bazel build //naive:torch_test` (no flag) | `//naive:torch_test` | analysis error | `No uv conflict variant selected` (see below) |
| `... --@pypi//_variants:extra_cpu=True --test_arg=cpu` | `//naive:torch_test` | pass | `torch 2.15.0+cpu` |
| `... --@pypi//_variants:extra_cu132=True --test_arg=cu132` | `//naive:torch_test` | pass | `torch 2.15.0+cu132 (cuda=13.2)` |
| both flags set | `//naive:torch_test` | analysis error | `Conflicting variants are active simultaneously` |

I checked the transitive closure with `bazel cquery 'deps(...)'`. The CPU test gets the full torch
closure, including the edges that uv gates on conflict markers (`jinja2 -> markupsafe`,
`sympy -> mpmath`, plus `filelock`, `fsspec`, `networkx` and `typing-extensions`). The CUDA test
also gets the nvidia-\*/cuda-\* wheels, and importing the CUDA torch build works on a machine
without a GPU. The first `bazel test //...` took ~80 s on this machine, including the CUDA wheel downloads.

## What happened with the naive approach

The README's way of using extras is `uv.repo(dependency_groups = ["default", "optional:cpu", "optional:cu132"])`
and depending on `@pypi//torch`. It doesn't fail silently: a build with no variant selected stops
at analysis time:

```
ERROR: .../external/rules_pycross++uv+torch__pkgs/_lock/BUILD.bazel:37:28: in pycross_no_variant_selected rule
  @@rules_pycross++uv+torch__pkgs//_lock:_no_variant_extra_cpu_extra_cu132:
Error in fail: No uv conflict variant selected. Set one of the _variants flags on your pycross repo:
  extra_cpu, extra_cu132 (e.g. --@<repo>//_variants:extra_cpu=True)
```

With `--@pypi//_variants:extra_cpu=True` (or `extra_cu132`), the naive target builds the right
torch and the full closure. Setting both flags is rejected:

```
Error in fail: Conflicting variants are active simultaneously: --extra_cpu and --extra_cu132.
  Only one variant from each conflict set may be enabled at a time.
```

The flag is global to the build, so with only the naive repo, one `bazel test //...` can't cover
both variants. That's why the naive target is tagged `manual`. The pinned repos above fix this
without touching the lock or pyproject.toml.

## Friction / limitations

- **One repo per variant.** Selection works per repo, not per target. A
  binary that needs both variants (e.g. a CPU tool and a CUDA trainer) depends on two different
  repo names (`@torch_cpu//torch`, `@torch_cu132//torch`). There is no single `@pypi//torch` whose
  variant follows the consuming target. You can still use the global flag with a single repo, but
  then all targets in the build get the same variant.
- **Extras have no default.** A conflict between extras has no default variant, so anything that
  reaches the unpinned repo without a flag fails analysis. That includes `bazel build //...` if a
  non-manual target uses it. uv's `default-groups` gives *group* conflicts a default; extras have
  no equivalent.
- **Variant flags are per repo** (`extra_<name>`, `group_<name>`). In a multi-project repo,
  `extra_<project>_<name>` picks one project's item when names repeat. The workspace example uses
  this.
