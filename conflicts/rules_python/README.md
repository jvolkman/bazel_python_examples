# Conflicting torch extras with rules_python 2.5.1

The shared project ([`project/`](../project)) has two conflicting extras, `cpu`
and `cu132`. Each one installs a different torch build from a different PyTorch
index. `uv lock` resolves both into one `uv.lock` as two forks.

**Summary:** `pip.parse(uv_lock = ...)` can't read this lock. It fails with a
hard error before it builds anything. The setup that works exports one
requirements file per extra from the same `uv.lock` with `uv export --frozen`
and creates one hub per variant (`@pypi_cpu`, `@pypi_cu132`). A single
`bazel test //...` then runs both variants. Two things have to be done by hand:
the PyTorch index must be set per hub, and the extras that `uv export` strips
must be put back.

## Setup

`MODULE.bazel` (trimmed):

```starlark
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.12")

pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")
pip.parse(
    # torch==2.15.0+cpu only exists on the PyTorch index.
    experimental_index_url_overrides = {"torch": "https://download.pytorch.org/whl/cpu"},
    hub_name = "pypi_cpu",
    python_version = "3.12",
    requirements_lock = "//requirements:cpu.txt",
)
pip.parse(
    experimental_index_url_overrides = {"torch": "https://download.pytorch.org/whl/cu132"},
    hub_name = "pypi_cu132",
    python_version = "3.12",
    requirements_lock = "//requirements:cu132.txt",
)
use_repo(pip, "pypi_cpu", "pypi_cu132")

# uv binary for `bazel run //requirements:<variant>.update`.
uv = use_extension("@rules_python//python/uv:uv.bzl", "uv", dev_dependency = True)
uv.configure(version = "0.13.5")
```

`BUILD.bazel`:

```starlark
load("@rules_python//python:py_test.bzl", "py_test")

py_test(
    name = "torch_cpu_test",
    srcs = ["project/src/check_torch.py"],
    args = ["cpu"],
    main = "project/src/check_torch.py",
    deps = ["@pypi_cpu//numpy", "@pypi_cpu//torch"],
)

py_test(
    name = "torch_cu132_test",
    srcs = ["project/src/check_torch.py"],
    args = ["cu132"],
    main = "project/src/check_torch.py",
    deps = ["@pypi_cu132//numpy", "@pypi_cu132//torch"],
)
```

The requirements files in [`requirements/`](requirements) are generated from
`project/uv.lock`. They are never written by hand:

```sh
bazel run //requirements:cpu.update     # uv export --frozen --no-dev --no-emit-project --extra cpu
bazel run //requirements:cu132.update   # ... --extra cu132
bazel test //requirements:all           # fails if a file is out of date with uv.lock
```

[`tools/export_requirements.py`](tools/export_requirements.py) runs the `uv`
binary from rules_python's uv toolchain. `--frozen` means uv doesn't re-resolve
anything, so `uv.lock` stays the single source of truth. The script also puts
back the extras that `uv export` drops (see "Friction" below).

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
| `//requirements:cpu_test` | pass | `cpu.txt` matches `uv export` of `uv.lock` |
| `//requirements:cu132_test` | pass | `cu132.txt` matches `uv export` of `uv.lock` |

Both torch variants build and run in one invocation. No flags, transitions, or
`--config` are needed because each test depends on a different hub. The CUDA
test runs on a machine without a GPU: it imports the CUDA build and checks
`torch.version.cuda`. That needs about 3-4 GB of `nvidia-*` wheels.

Other things I checked:

- `torch` is downloaded from the PyTorch index. The repo attributes show
  `urls = ["https://download-r2.pytorch.org/whl/cu132/torch-2.15.0%2Bcu132-cp312-cp312-manylinux_2_28_x86_64.whl"]`.
  All other packages come from `files.pythonhosted.org`.
- The two hubs share downloads but not repositories. `numpy` becomes two
  repositories,
  `pypi_cpu_312_numpy_cp312_cp312_manylinux_2_27_x86_64_704d8192` and
  `pypi_cu132_312_numpy_..._704d8192`. Both have the same URL and the same
  sha256, so Bazel's repository cache downloads the wheel only once. It is
  still extracted twice.

## What happened with the naive approach

The naive setup is in [`naive/`](naive). It is a separate module, listed in
`.bazelignore`, because the failure breaks the whole `pip` extension. That
setup is a single hub that points straight at the shared lock:

```starlark
pip.parse(
    hub_name = "pypi_naive",
    python_version = "3.12",
    uv_lock = "//:project/uv.lock",
)
```

`cd naive && bazel build //...` fails while Bazel evaluates the module
extension:

```
ERROR: .../external/rules_python+/python/private/pypi/hub_builder.bzl:366:13: Traceback (most recent call last):
  ...
Error in fail: attempting to override an existing repo
'pypi_naive_312_torch_cp312_cp312_manylinux_2_28_x86_64_0955c7e3_linux_x86_64'
for config setting 'struct(target_platforms = ("cp312_linux_x86_64",), version = "3.12")'
with a new repo
'pypi_naive_312_torch_cp312_cp312_manylinux_2_28_x86_64_84936484_linux_x86_64'
ERROR: Analysis of target '//:naive_torch_cpu_test' failed; build aborted:
error evaluating module extension @@rules_python+//python/extensions:pip.bzl%pip
```

This is a loud failure, not a silent one. The cause is in the uv.lock reader
(`python/private/pypi/parse_requirements.bzl`, `_parse_uv_lock_json` and
`_uv_lock_package_platforms`). It walks the dependency edges from the
virtual/editable roots and follows every `optional-dependencies` and
`dev-dependencies` edge, because `uv_lock_extras_map` turns on every extra it
finds. It also evaluates `resolution-markers` and edge markers against each
target platform, but only a marker that is definitely `False` excludes
anything. Both torch entries carry only
`platform_machine == 'x86_64' and sys_platform == 'linux'`, and `torch-app`
reaches them through its `cpu` and `cu132` optional-dependency tables. uv
records the conflict as `extra == 'extra-9-torch-app-...'` terms, and the
platform environment can't evaluate those. Both `torch 2.15.0+cpu` and
`torch 2.15.0+cu132` therefore land on `cp312_linux_x86_64`. rules_python can only have one wheel per package per
platform in a hub, so it fails. The reader has no knowledge of
`[tool.uv] conflicts` and no way to choose an extra.

I also tried leaving out `experimental_index_url_overrides` from the working
setup. The Simple API lookup on PyPI can't find the hashes, so rules_python
logs `WARNING: Could not find a whl or an sdist with hash sha256:...` for every
torch hash. It then falls back to `pip wheel`, which fails while the torch
repository is fetched:

```
ERROR: Could not find a version that satisfies the requirement torch==2.15.0+cpu
(from versions: 2.2.0, ..., 2.14.1, 2.15.0)
ERROR: No matching distribution found for torch==2.15.0+cpu
```

## Friction / limitations

1. **`uv_lock` can't be used with conflicting extras.** There is no way to
   choose a fork or extra, and every extra is turned on. You have to leave the
   built-in uv.lock support and use requirements files that `uv export`
   produces from the same lock.
2. **`uv export` strips extras, and rules_python then silently drops
   dependencies.** torch's metadata asks for
   `cuda-toolkit[cublas,cudart,cufft,...]`. `uv export` writes a flat
   `cuda-toolkit==13.2.2`. rules_python builds a wheel's dependencies from its
   `METADATA`, and it only turns on the extras written on that package's own
   requirement line. So `@pypi_cu132//cuda_toolkit` got `extras = []` and no
   dependency on `nvidia-cuda-runtime`, `nvidia-cufft`, and the others.
   Analysis and build succeeded. The test failed at import time:

   ```
   OSError: libcudart.so.13: cannot open shared object file: No such file or directory
   ValueError: libcudart.so.*[0-9] not found in the system path [...]
   ```

   The upstream issue is bazel-contrib/rules_python#4168 ("`pip.parse` drops
   extras declared on the wheel's dependency"). It was closed as not planned.
   The maintainer's advice is to use the built-in `uv.lock` support, which this
   lock breaks, or `uv pip compile --no-strip-extras`, which re-resolves
   instead of reading `uv.lock`. Here,
   [`tools/export_requirements.py`](tools/export_requirements.py) reads the
   extras that each exported package's dependents ask for from `uv.lock` and
   rewrites the line as
   `cuda-toolkit[cublas,cudart,cufft,cufile,cupti,cusolver,cusparse,nvjitlink,nvrtc,nvtx]==13.2.2`.
   uv.lock-based tooling has to deal with this on its own.
3. **`uv export` doesn't record the index.** The lock knows that torch comes
   from `download.pytorch.org/whl/<variant>`, but the exported
   `torch==2.15.0+cpu --hash=...` line doesn't say so. Each hub has to repeat
   it with `experimental_index_url_overrides`. That attribute is still named
   "experimental". An `--extra-index-url` line would also send every other
   package through the PyTorch index first.
4. **One hub per variant.** A hub can only hold one wheel per package per
   platform, so you get two hubs and a duplicate repository for every shared
   wheel. A single hub would need custom `pip.default` platforms keyed on a
   flag, plus `config.add_transition_setting` so each `py_test` can set that
   flag. [`../../workspaces/rules_python`](../../workspaces/rules_python) uses
   that pattern and it works. Here, two hubs are simpler.
5. **The `lock` rule doesn't help.** rules_python's `lock` rule runs
   `uv pip compile`, which re-resolves from `pyproject.toml`. It doesn't read
   `uv.lock` and it doesn't know about `[tool.uv] conflicts` or the per-extra
   `[tool.uv.sources]`. That is why this setup uses `uv export --frozen` in a
   `bazel run` target instead.
6. **Upcoming:** bazel-contrib/rules_python#4395, #4428 and #4429 add
   `pip.configure(hub_name, dependency_groups, pyproject_toml, testonly, venv)`.
   That lets you choose which packages a hub exposes, based on
   `[dependency-groups]`. All three PRs are still open and not on `main` as of
   this writing. They target dependency groups, not conflicting extras inside
   one `uv_lock`, so they wouldn't fix the error above on their own.
