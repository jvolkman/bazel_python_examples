# Conflicting extras (CPU vs CUDA torch) with rules_py 2.0.0-alpha.11

Module: `conflicts_rules_py`. It uses rules_py's own interpreter provisioning
(`python_interpreters`, Python 3.12) and its own `py_test`.

```sh
bazel test //...                 # //:torch_{cpu,cu132}_test + //shared_lock:torch_{cpu,cu132}_test
bazel test //naive:all           # the naive attempts (tagged manual)
```

## 1. Setup

rules_py has no way to select an extra such as `torch-app[cu132]` per target.
It also does not read `[tool.uv] conflicts` (aspect-build/rules_py#1510).
The only per-target switch is the **dependency group** (`dep_group`). A
dependency group is either a `[dependency-groups]` entry of the pyproject.toml
given to `uv.project()`, or, if that table is absent, one implicit group named
after `[project].name`. Setting `dep_group` on a `py_test` is a configuration
transition, so both variants build and run in one `bazel test //...`.

**Main setup: one hub, one `uv.project()` per variant.** `variants/cpu` and
`variants/cu132` each contain a copy of the shared project, locked for one
torch build only. These copies have no extras and no `conflicts`:

```starlark
# MODULE.bazel
uv = use_extension("@rules_py//uv:extensions.bzl", "uv")
uv.declare_hub(hub_name = "pypi")
uv.project(hub_name = "pypi", lock = "//variants/cpu:uv.lock", pyproject = "//variants/cpu:pyproject.toml")
uv.project(hub_name = "pypi", lock = "//variants/cu132:uv.lock", pyproject = "//variants/cu132:pyproject.toml")
use_repo(uv, "pypi")
```

```starlark
# BUILD.bazel
py_test(
    name = "torch_cu132_test",
    srcs = ["project/src/check_torch.py"],
    main = "project/src/check_torch.py",
    args = ["cu132"],
    dep_group = "torch-app-cu132",  # implicit group = [project].name of variants/cu132
    deps = ["@pypi//numpy", "@pypi//torch"],
)
```

Here is how `variants/<v>/pyproject.toml` differs from `project/pyproject.toml`:

- `name = "torch-app-<v>"`. The project name becomes the group name, and it
  must be unique; see the gotchas below.
- `dependencies = ["numpy>=2", "torch>=2.9"]`, with no extras and no
  `[tool.uv] conflicts`.
- `[tool.uv.sources] torch = { index = "pytorch-<v>" }`, and only that one
  PyTorch index.
- `package = false`. The `environments` setting and the public PyPI index are
  unchanged.

Both files were relocked with `uv lock` (uv 0.9.5) against public indexes
only. The results are 12 packages for cpu and 31 for cu132. Both get the same
torch 2.15.0+cpu/+cu132 and numpy 2.5.5 as the shared lock.

**Alternative on the same hub: the shared uv.lock.** `shared_lock/pyproject.toml`
is a Bazel-only stand-in for the root pyproject.toml, used with the unchanged
shared `uv.lock`. It adds two dependency groups, `shared-cpu = ["torch-app[cpu]"]`
and `shared-cu132 = ["torch-app[cu132]", "cuda-toolkit[cublas,cudart,...]"]`.
The `cuda-toolkit[...]` entry is copied by hand from the `torch 2.15.0+cu132`
entry in the lock, because rules_py drops that edge (see section 3). The CUDA
test also has to list `@pypi//cuda_toolkit` in its `deps`. The project is named
`torch-app-shared` because of the name-collision gotcha.

## 2. Result

`bazel test //...` (one invocation, Bazel 9.3.2):

| Target | Status | Observed |
| --- | --- | --- |
| `//:torch_cpu_test` | pass | `torch 2.15.0+cpu (cuda=None), numpy 2.5.5` |
| `//:torch_cu132_test` | pass | `torch 2.15.0+cu132 (cuda=13.2), numpy 2.5.5` |
| `//shared_lock:torch_cpu_test` | pass | `torch 2.15.0+cpu (cuda=None), numpy 2.5.5` |
| `//shared_lock:torch_cu132_test` | pass | `torch 2.15.0+cu132 (cuda=13.2), numpy 2.5.5` |

Naive attempts (`bazel test //naive:all`):

| Target | Status | Observed |
| --- | --- | --- |
| `//naive:torch_cpu_test`, `//naive:torch_cu132_test` | fail (analysis) | `no such package '@@rules_py++uv+pypi_naive//torch'` |
| `//naive:groups_torch_cpu_test` | pass | `torch 2.15.0+cpu (cuda=None)` |
| `//naive:groups_torch_cu132_test` | **silently wrong graph**, fails at import | `OSError: libcudart.so.13: cannot open shared object file` |

## 3. What happened with the naive approach

**Step 1: the shared pyproject.toml and uv.lock as they are** (hub `pypi_naive`).
There are no `[dependency-groups]`, so the hub gets one implicit group,
`torch-app`, that contains only the project and its base dependencies. torch is
reachable only through the `cpu`/`cu132` extras. rules_py has no way to
activate those extras, so torch is missing from the hub entirely:

```
$ bazel query @pypi_naive//...
@pypi_naive//dep_group:torch-app
@pypi_naive//numpy:numpy
@pypi_naive//torch_app:torch_app
...
$ bazel test //naive:torch_cpu_test
ERROR: no such package '@@rules_py++uv+pypi_naive//torch': BUILD file not found in directory 'torch'
of external repository @@rules_py++uv+pypi_naive.
```

**Step 2: map each extra to a dependency group** (hub `pypi_naive_groups`). This
step is what the docs suggest, using `naive/pyproject.toml` with the shared lock:
`cpu = ["torch-app[cpu]"]`, `cu132 = ["torch-app[cu132]"]`, and
`py_test(dep_group = ...)`. The CPU variant works. The CUDA variant picks the
right torch wheel (`torch-2.15.0+cu132.dist-info` is in the venv), but some of
its dependencies are missing. Analysis and build succeed with no warning, and
the test fails only when torch is imported:

```
File ".../site-packages/torch/__init__.py", line 433, in _load_global_deps
OSError: libcudart.so.13: cannot open shared object file: No such file or directory
...
ValueError: libcudart.so.*[0-9] not found in the system path [...]
```

The cause is aspect-build/rules_py#1510. uv encodes the extras conflict as
markers like `extra == 'extra-9-torch-app-cu132'`. In this lock, torch+cu132
depends on cuda-toolkit through such a marker:

```toml
{ name = "cuda-toolkit", extra = ["cublas", "cudart", "cufft", ...],
  marker = "(platform_machine == 'x86_64' and sys_platform == 'linux' and extra == 'extra-9-torch-app-cu132') or ..." }
```

rules_py does not parse `[tool.uv] conflicts`, so that marker is always false
and the edge is dropped. The cu132 venv still has nvidia-cublas, nvrtc, cccl,
cudnn, cusparselt, nccl and nvshmem, which arrive through other edges. It is
missing `cuda-toolkit`, `nvidia-cuda-runtime` (libcudart), `nvidia-cufft`,
`nvidia-cufile`, `nvidia-cuda-cupti`, `nvidia-cusolver`, `nvidia-cusparse`,
`nvidia-nvjitlink` and `nvidia-nvtx`. On a machine where the system provides a
CUDA runtime, the test could import a mix of system and wheel libraries
instead of failing.

## 4. Friction / limitations

- **Extras aren't selectable, and conflicts aren't understood.** Only dependency
  groups from the pyproject.toml given to `uv.project()` can be selected. uv
  conflict markers evaluate to false, which silently drops edges
  (aspect-build/rules_py#1510, open). The related group-conflict case is
  aspect-build/rules_py#817, which is closed. It works only as long as no edge
  is conflict-gated.
- **Main setup: two locks instead of one.** Both variant locks must be kept
  in sync by hand, for example to keep numpy the same. uv no longer guarantees
  that shared packages resolve identically for both variants. Nothing is
  hand-patched, though: each lock is single-fork, so no edge depends on a
  conflict marker.
- **Alternative: one lock, with hand-restored edges.** You have to find every
  conflict-gated edge in uv.lock yourself, copy it into a Bazel-only
  pyproject.toml, and add the restored package to the test's `deps`. Nothing
  warns you when a relock adds a new conflict-gated edge.
- **Gotcha: `[project].name` must be unique across all hubs.** rules_py names
  the generated project repository `project__<[project].name>`, and the name
  is global to the extension. During this work, three `uv.project()`s on
  different hubs were all named `torch-app`. They silently overwrote each
  other, and `@pypi_naive//numpy` ended up pointing at the other hub's
  project. The symptom:

  ```
  ERROR: .../rules_py++uv+project__torch_app/BUILD.bazel:660:6: configurable attribute "actual" in
  @@rules_py++uv+project__torch_app//:numpy doesn't match this configuration.
  Conditions checked:
   @@rules_py++uv+project__torch_app//private/dep_group:cpu
   @@rules_py++uv+project__torch_app//private/dep_group:cu132
  ```

  This is why the Bazel-only pyproject files here are named `torch-app-groups`
  and `torch-app-shared`. A related cross-module report is
  aspect-build/rules_py#1093. Group names must also be unique within one hub,
  otherwise you get `Conflict on configuration name ...`.
- **Every group is its own configuration.** Hub targets are incompatible
  outside their group, so a library that depends on `@pypi//torch` builds only
  under a terminal or flag that sets `dep_group`. To get a default, set
  `common --@pypi//dep_group=<group>`.
