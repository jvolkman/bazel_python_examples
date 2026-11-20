# Conflicts: rules_pycross 2.2.0

uv `conflicts` between the `cpu` and `cu132` extras of the shared
[`project/`](../project) (one `uv.lock`, two torch builds), with
[rules_pycross](https://github.com/jvolkman/rules_pycross) 2.2.0 and
rules_python 2.5.1 (toolchain, `py_test`, and `config_settings` transition), Bazel 9.3.2, Python 3.12.

## Setup

rules_pycross reads the uv lock's `conflicts` table itself. Each conflicting item gets a
`bool_flag` (`@pypi//_variants:extra_cpu`, `@pypi//_variants:extra_cu132`), and the repo also
exposes a single `@pypi//_variants` `string_flag` accepting a variant name (or comma-separated list
across conflict sets). Registering `@pypi//_variants` with `rules_python`'s
`config.add_transition_setting` lets `py_test` and `py_binary` targets pick their variant through
`config_settings` against one `@pypi` repo, so both variants run in one `bazel test //...`.
Variant-independent packages like `numpy` reset the variant flags and install once across both
configurations.

[`MODULE.bazel`](MODULE.bazel) (trimmed):

```starlark
bazel_dep(name = "rules_pycross", version = "2.2.0")
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.12")

config = use_extension("@rules_python//python/extensions:config.bzl", "config")
config.add_transition_setting(setting = "@pypi//_variants")

uv = use_extension("@rules_pycross//pycross/extensions:uv.bzl", "uv")
uv.workspace(name = "torch", lock_file = "//:project/uv.lock")
uv.repo(
    name = "pypi",
    dependency_groups = ["default", "optional:cpu", "optional:cu132"],
    workspace = "torch",
)
use_repo(uv, "pypi")
```

[`BUILD.bazel`](BUILD.bazel) (plain rules_python `py_test`):

```starlark
py_test(
    name = "torch_cpu_test",
    srcs = ["project/src/check_torch.py"],
    args = ["cpu"],
    config_settings = {"@pypi//_variants": "extra_cpu"},
    main = "project/src/check_torch.py",
    deps = ["@pypi//numpy", "@pypi//torch"],
)
# torch_cu132_test: the same with config_settings = {"@pypi//_variants": "extra_cu132"} and args = ["cu132"].
```

There is no pycross-specific toolchain setup. rules_pycross picks up the registered rules_python
toolchain (3.12) and registers its own toolchains automatically. [`naive/`](naive/BUILD.bazel)
keeps a `manual` target without `config_settings` to show what happens when no variant is selected.

Run:

```sh
bazel test //...                      # both variants, no flags
bazel test //naive:torch_test --@pypi//_variants=extra_cpu --test_arg=cpu
bazel test //naive:torch_test --@pypi//_variants=extra_cu132 --test_arg=cu132
```

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:torch_cpu_test` | pass | `torch 2.15.0+cpu (cuda=None), numpy 2.5.5` |
| `bazel test //...` | `//:torch_cu132_test` | pass | `torch 2.15.0+cu132 (cuda=13.2), numpy 2.5.5` |
| `bazel build //naive:torch_test` (no flag) | `//naive:torch_test` | analysis error | `No uv conflict variant selected` (see below) |
| `... --@pypi//_variants=extra_cpu --test_arg=cpu` | `//naive:torch_test` | pass | `torch 2.15.0+cpu` |
| `... --@pypi//_variants=extra_cu132 --test_arg=cu132` | `//naive:torch_test` | pass | `torch 2.15.0+cu132 (cuda=13.2)` |
| both flags set | `//naive:torch_test` | analysis error | `Conflicting variants are active simultaneously` |

The CPU test gets the full torch closure, including the edges that uv gates on conflict markers
(`jinja2 -> markupsafe`, `sympy -> mpmath`, plus `filelock`, `fsspec`, `networkx`, and
`typing-extensions`). The CUDA test also gets the `nvidia-*`/`cuda-*` wheels, and importing the
CUDA torch build works on a machine without a GPU. `bazel aquery` across both tests shows
`numpy@2.5.5` installing once (`_reset_numpy@2.5.5`) under both configurations.

## What happened with the naive approach

Depending on `@pypi//torch` without `config_settings` or a command-line flag does not fail
silently; it stops at analysis time:

```text
Error in fail: No uv conflict variant selected. Set one of the _variants flags on your pycross repo:
  extra_cpu, extra_cu132 (e.g. --@pypi//_variants:extra_cpu=True or --@pypi//_variants=extra_cpu)
```

Passing `--@pypi//_variants=extra_cpu` (or `--@pypi//_variants:extra_cpu=True`) builds the right
torch and the full closure. Setting both variants (`--@pypi//_variants=extra_cpu,extra_cu132`) is
rejected with `Conflicting variants are active simultaneously`.

## Friction / limitations

- **Extras have no default.** A conflict between extras has no default variant, so any non-manual
  target that reaches `@pypi//torch` without `config_settings` or a command-line flag fails
  analysis. (uv's `default-groups` gives *group* conflicts a default; extras have no equivalent.)
- **Pairing defaults with `config_settings`.** If you also set a default variant in `.bazelrc` or
  on the command line, use `--@pypi//_variants=<flag>` rather than `--@pypi//_variants:<flag>=True`
  so a target's `config_settings` replaces the default instead of conflicting with the `bool_flag`.
- **Per-variant repos remain an option.** If a single target needs both variants in its own
  dependency graph, or you prefer selecting by repo name instead of `config_settings`, you can
  define separate `uv.repo` views (`dependency_groups = ["default", "optional:cpu"]` and
  `["default", "optional:cu132"]`); each selects its only requested extra automatically.
