# bazel_python_examples

Side-by-side examples of how three Bazel Python rulesets handle the same uv lock files:

| Ruleset | Version | Python rules used |
| --- | --- | --- |
| [rules_python](https://github.com/bazel-contrib/rules_python) | 2.5.1 | its own `py_library` / `py_test` |
| [rules_pycross](https://github.com/jvolkman/rules_pycross) | 2.1.0 | rules_python's `py_library` / `py_test` |
| [rules_py](https://github.com/aspect-build/rules_py) | 2.0.0-alpha.11 (BCR module `rules_py`) | its own `py_library` / `py_test` / `py_pytest_test` |

All modules use Bazel 9.3.2 and Python 3.12. The locks are restricted to Linux x86_64.

## Layout

```
conflicts/                     # Scenario 1: torch CPU vs CUDA in one lock
  project/                     #   shared pyproject.toml + uv.lock + src/check_torch.py
  rules_python/  rules_pycross/  rules_py/
workspaces/                    # Scenario 2: uv workspace with conflicting dependency groups
  project/                     #   shared workspace: root + libs/common, apps/app-a, apps/app-b
  rules_python/  rules_pycross/  rules_py/
```

Each `<scenario>/<ruleset>/` directory is its own Bazel module. It has a `project` symlink to the
shared uv project, and a README with the setup, results, what the naive approach did, and the
friction involved. Run any of them with:

```sh
cd conflicts/rules_pycross && bazel test //...
```

Every module's `bazel test //...` passes. Naive or failing setups are kept as `manual` targets or
nested modules that `.bazelignore` excludes, so you can reproduce them.

## Scenario 1: conflicts (torch CPU vs CUDA)

[`conflicts/project/pyproject.toml`](conflicts/project/pyproject.toml) is the uv-documented
setup:
- The extras `cpu` and `cu132` both depend on `torch`.
- `[tool.uv] conflicts` declares them mutually exclusive.
- `[tool.uv.sources]` routes torch to the PyTorch CPU or CUDA 13.2 index.

One `uv.lock` therefore holds `torch 2.15.0+cpu` and `torch 2.15.0+cu132` on separate forks. The
nvidia-\*/cuda-\* wheels appear only on the CUDA fork. Each module must provide
`//:torch_cpu_test` and `//:torch_cu132_test`, and both must pass in a single `bazel test //...`.
The CUDA test runs fine without a GPU; it checks `torch.version.cuda`.

| | rules_python | rules_pycross | rules_py |
| --- | --- | --- | --- |
| Reads `[tool.uv] conflicts` | No | **Yes** | No ([#1510](https://github.com/aspect-build/rules_py/issues/1510)) |
| Naive (point at the shared uv.lock) | **Loud** failure at extension time: `attempting to override an existing repo ... torch ...` | **Loud** failure at analysis: `No uv conflict variant selected. Set one of the _variants flags ...`. Passing the flag works. | Torch isn't in the hub (extras are never activated). Mapping the extras to groups builds, but cu132 is **silently wrong**: torch's conflict-gated `cuda-toolkit[...]` edge is dropped, so `import torch` fails with `libcudart.so.13: cannot open shared object file` |
| Working setup | `uv export --extra <v>` → one requirements file and one `pip.parse` hub per variant (`@pypi_cpu`, `@pypi_cu132`) | Shared uv.lock unchanged. Two `uv.repo` views over one workspace, each pinned with `flags = ["--@<repo>//_variants:extra_<v>=True"]` | A separate pyproject + uv.lock per variant (no extras, no conflicts), each a `uv.project` on one hub, picked by `py_test(dep_group = ...)` |
| Variant chosen by | Hub name | Repo name (repo transition), or a global flag | `dep_group` on the terminal target (transition) or a global flag |
| Uses the shared uv.lock as-is | No (exported requirements files) | **Yes** | No (per-variant locks). A shared-lock variant works only if you restate the cuda-toolkit edge by hand |
| Hand work | Export script and up-to-date tests. `experimental_index_url_overrides` for the torch indexes. A helper that adds back extras `uv export` strips (`cuda-toolkit[cudart,...]`) | None | Copy and relock each variant |

## Scenario 2: uv workspace with conflicting dependency groups

This is the Slack question about rules_py hubs. The user has one workspace and one lock, and wants
**one hub** with every member's production dependencies. The root `pyproject.toml` has a `dev`
group (linters, stubs) that Bazel doesn't need. They want neither to delete `[dependency-groups]`
nor to keep a member list by hand.

[`workspaces/project/`](workspaces/project) reproduces that setup:
- The root `monorepo` has `[dependency-groups] dev = [ruff, mypy]`.
- `libs/common` uses requests.
- `apps/app-a` uses pydantic and has a `test` group requiring pytest < 8.
- `apps/app-b` uses attrs and has a `test` group requiring pytest ≥ 8.
- The two `test` groups are declared conflicting, so the lock has pytest 7.4.4 and 9.2.0.
- Members are real hatchling packages. Bazel builds the first-party code from `src/`.

| | rules_python | rules_pycross | rules_py |
| --- | --- | --- | --- |
| Where hub contents are chosen | Requirements files you export (`uv export --all-packages --no-dev`, `--package app-a --group test`, ...) | `MODULE.bazel`: `uv.repo(projects = ["*"], dependency_groups = ["default"])` | The root pyproject's `[dependency-groups]`. Without any, it uses one implicit group of all `[manifest].members` |
| All members, no `dev`, no hand-kept list | Yes, via `--all-packages --no-dev` | **Yes, native**: `dev` is just not selected, and the root pyproject is untouched | Only by giving rules_py a Bazel-only stub pyproject with no `[dependency-groups]`, so the real root pyproject is never read |
| Naive (shared lock + root pyproject) | **Loud** failure: `attempting to override an existing repo ... pytest ...` (it follows every dev-dependency edge, so `dev` would also land in the hub) | **Works** in 2.1.0 (2.0.1 had a bug, see below) | **Loud** failure: `Editable package app_a ... doesn't have a mandatory uv.override_package(target = ...)`. With overrides added, the only group is `dev`, so pydantic is missing |
| pytest 7 / 8 split | One hub. Each exported file is bound to a custom `pip.default` platform keyed on a `//:deps` string flag, and each `py_test` sets it with `config_settings` | Per-member test repos (`projects = ["app-a"]`, `group:test;testonly`), pinned with `flags` | Member groups are ignored, so they are restated as root groups (`app-a-test = ["app-a", "pytest>=7,<8"]`) and picked with `py_pytest_test(dep_group = ...)` |
| Workspace members | Silently dropped (`-e` lines are ignored; uses `--no-emit-workspace`) | Treated as projects: no targets, no error, member→member deps flattened | Each editable member needs `uv.override_package(target = ...)` |
| Uses the shared uv.lock as-is | No (exported files) | **Yes** (2.1.0) | Yes, plus two stub pyprojects |

## Bugs and limitations found

- **rules_pycross 2.0.1** (both fixed in 2.1.0):
  - `variant_item_qname()` (`pycross/private/util.bzl`) and `translate_uv` name group or extra
    variants `group_<name>` / `extra_<name>` and drop the conflict item's `package`. So
    `{package = "app-a", group = "test"}` and `{package = "app-b", group = "test"}` collide:
    ``Label '...__pkgs//_lock:group_test' is duplicated in the 'flags' attribute``. This breaks
    every repo on the workspace.
  - Member and root pyproject.toml files are resolved relative to the lock file's Bazel
    *package*, not its directory. With `//:project/uv.lock`, the root pyproject is silently `{}`,
    and per-member repos fail with `BUILD file not found`.
  - Details: [workspaces/rules_pycross/README.md](workspaces/rules_pycross/README.md). Both are
    fixed by [rules_pycross#381](https://github.com/jvolkman/rules_pycross/pull/381), released
    in 2.1.0. The example now uses the shared workspace lock unchanged.
- **rules_py 2.0.0-alpha.11:**
  - Conflicts are unsupported: conflict-gated edges are silently dropped
    ([#1510](https://github.com/aspect-build/rules_py/issues/1510)).
  - `project__<[project].name>` repos are global to the extension, so `uv.project`s on different
    hubs that share a `[project].name` overwrite each other (related:
    [#1093](https://github.com/aspect-build/rules_py/issues/1093)).
  - Hub labels are incompatible outside a selected `dep_group`, so `//...` silently skips
    libraries unless `.bazelrc` sets a default.
- **rules_python 2.5.1:**
  - `pip.parse(uv_lock = ...)` ignores conflicts and dependency-group selection.
  - `uv export` drops the extras that a dependency requests on its dependents
    ([#4168](https://github.com/bazel-contrib/rules_python/issues/4168), closed as not planned),
    which silently breaks CUDA torch.
  - Without `target_platforms`, a multi-file `requirements_by_platform` hub is silently empty.
  - `pip.configure(dependency_groups = ...)` is in progress upstream (PRs #4395, #4428, #4429).
