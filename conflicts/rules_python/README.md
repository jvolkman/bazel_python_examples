# Conflicting torch extras with rules_python 2.5.1

The shared project ([`project/`](../project)) has two conflicting extras, `cpu`
and `cu132`. Each one installs a different torch build from a different PyTorch
index. `uv lock` resolves both into one `uv.lock` as two forks.

**Summary:** `pip.parse(uv_lock = ...)` can't read the shared lock because
rules_python enables every extra and has no way to select a conflict variant.
Instead, this module splits the project into two per-variant `uv.lock` files
([`variants/cpu/uv.lock`](variants/cpu/uv.lock) and
[`variants/cu132/uv.lock`](variants/cu132/uv.lock)), parses each directly with
`pip.parse(uv_lock = ...)`, and uses rules_python 2.5.1's unified `@pypi` hub
with `config_settings` on `@rules_python//python/config_settings:venv`. No
`requirements.txt` export, no `experimental_index_url_overrides`, and no
extra-restoring script are needed; the tradeoff is maintaining two separate
`pyproject.toml` and `uv.lock` files instead of using `project/uv.lock`.

## Setup

[`MODULE.bazel`](MODULE.bazel):

```starlark
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(
    is_default = True,
    python_version = "3.14",
)

pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")
pip.default(default_hub = "pypi_cpu")

pip.parse(
    hub_name = "pypi_cpu",
    python_version = "3.14",
    uv_lock = "//variants/cpu:uv.lock",
)
pip.parse(
    hub_name = "pypi_cu132",
    python_version = "3.14",
    uv_lock = "//variants/cu132:uv.lock",
)
use_repo(pip, "pypi")
```

[`BUILD.bazel`](BUILD.bazel):

```starlark
load("@rules_python//python:py_test.bzl", "py_test")

py_test(
    name = "torch_cpu_test",
    srcs = ["project/src/check_torch.py"],
    args = ["cpu"],
    config_settings = {"@rules_python//python/config_settings:venv": "pypi_cpu"},
    main = "project/src/check_torch.py",
    deps = ["@pypi//numpy", "@pypi//torch"],
)

py_test(
    name = "torch_cu132_test",
    srcs = ["project/src/check_torch.py"],
    args = ["cu132"],
    config_settings = {"@rules_python//python/config_settings:venv": "pypi_cu132"},
    main = "project/src/check_torch.py",
    deps = ["@pypi//numpy", "@pypi//torch"],
)
```

`@rules_python//python/config_settings:venv` is already in rules_python's
built-in transition allowlist, so `config.add_transition_setting` is not
needed. You can also depend on `@pypi_cpu//torch` and `@pypi_cu132//torch`
directly if you prefer separate hub names over a transition.

Run everything:

```sh
cd conflicts/rules_python
bazel test //...
```

## Result

| Target | `bazel test //...` | Observed |
| --- | --- | --- |
| `//:torch_cpu_test` | pass | `torch 2.15.0+cpu (cuda=None), numpy 2.5.5` |
| `//:torch_cu132_test` | pass | `torch 2.15.0+cu132 (cuda=13.2), numpy 2.5.5` |

Both torch variants build and run in one invocation. The CUDA test runs on a
machine without a GPU: it imports the CUDA build and checks
`torch.version.cuda`.

Other things verified:

- **Direct wheel URLs and extras work out of the box.** `pip.parse(uv_lock = ...)`
  reads wheel URLs directly from `uv.lock` (so `torch` downloads from the
  PyTorch index without `experimental_index_url_overrides`) and preserves
  transitive extras like `cuda-toolkit[cublas,cudart,...]` (avoiding
  bazel-contrib/rules_python#4168).
- **Shared wheels are still separate spoke repos.** `numpy` becomes two spoke
  repositories (`pypi_cpu_314_numpy_...` and `pypi_cu132_314_numpy_...`)
  because each `pip.parse` hub creates its own spoke repos. Bazel's repository
  cache downloads the wheel once, and it is extracted once per hub.

## What happened with the naive approach

The naive setup is in [`naive/`](naive). It is a separate module, listed in
`.bazelignore`, because the failure breaks the whole `pip` extension. That
setup points `pip.parse(uv_lock = ...)` straight at the shared lock:

```starlark
pip.parse(
    hub_name = "pypi_naive",
    python_version = "3.14",
    uv_lock = "//:project/uv.lock",
)
```

`cd naive && bazel build //...` fails while Bazel evaluates the module
extension:

```text
ERROR: .../external/rules_python+/python/private/pypi/hub_builder.bzl:366:13: Traceback (most recent call last):
  ...
Error in fail: attempting to override an existing repo
'pypi_naive_314_torch_cp314_cp314_manylinux_2_28_x86_64_f089c949_linux_x86_64'
for config setting 'struct(target_platforms = ("cp314_linux_x86_64",), version = "3.14")'
with a new repo
'pypi_naive_314_torch_cp314_cp314_manylinux_2_28_x86_64_593e34d5_linux_x86_64'
ERROR: Analysis of target '//:naive_torch_cpu_test' failed; build aborted:
error evaluating module extension @@rules_python+//python/extensions:pip.bzl%pip
```

The cause is in `python/private/pypi/parse_requirements.bzl`
(`_parse_uv_lock_json` and `_uv_lock_package_platforms`). It walks every
`optional-dependencies` and `dev-dependencies` edge because `uv_lock_extras_map`
enables every extra it finds. uv encodes `[tool.uv] conflicts` as
`extra == 'extra-9-torch-app-...'` markers, which the platform evaluator cannot
evaluate to `False`. Both `torch 2.15.0+cpu` and `torch 2.15.0+cu132` therefore
land on `cp314_linux_x86_64`, and rules_python fails because a hub can only
hold one wheel per package per platform.

## Friction / limitations

1. **Cannot use the shared `project/uv.lock`.** Because `pip.parse(uv_lock = ...)`
   has no way to select a conflict variant or extra, and `uv` cannot split one
   `uv.lock` into per-extra `uv.lock` files, you have to maintain a separate
   `pyproject.toml` and `uv.lock` per variant (`variants/cpu/` and
   `variants/cu132/`), or else fall back to `uv export --frozen --extra <v>`
   into `requirements.txt` files.
2. **Tradeoffs of the `uv export` alternative.** If you must keep the single
   shared `project/uv.lock` as the source of truth, `uv export --frozen --extra <v>`
   produces `requirements.txt` files that `pip.parse(requirements_lock = ...)`
   can read, but adds extra friction:
   - `uv export` drops transitive extras (`cuda-toolkit[cublas,cudart,...]`
     becomes `cuda-toolkit==13.2.2`), causing rules_python to omit
     `nvidia-cuda-runtime` and fail at import time
     (bazel-contrib/rules_python#4168, closed as not planned).
   - `uv export` does not record per-package indexes, so each hub must also set
     `experimental_index_url_overrides = {"torch": ...}`.
3. **Two hubs are still required for two `uv_lock` files.** `hub_builder.bzl`
   allows only one `pip.parse` call per `(hub_name, python_version)`, and
   `uv_lock` is a single label rather than a per-platform dict like
   `requirements_by_platform`. The unified `@pypi` hub hides the split behind
   `@rules_python//python/config_settings:venv`, while shared wheels are still
   extracted once per concrete hub.
4. **Upcoming:** bazel-contrib/rules_python#4395, #4428, and #4429 add
   `pip.configure(hub_name, dependency_groups, pyproject_toml, testonly, venv)`
   for selecting `[dependency-groups]`. Those PRs target dependency groups
   rather than conflicting extras inside one `uv_lock`.
