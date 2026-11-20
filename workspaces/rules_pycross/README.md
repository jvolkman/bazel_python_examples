# Workspaces: rules_pycross (`main`)

The uv workspace in [`project/`](../project) (root `monorepo` with a `dev` group, members
`libs/common`, `apps/app-a`, `apps/app-b`, and conflicting per-member `test` groups that need
pytest 7 and pytest 8+), with [rules_pycross](https://github.com/jvolkman/rules_pycross) pinned to
`main` (`8d788096`) and rules_python 2.5.1 (toolchain, `py_library`/`py_test`, and
`config_settings` transition), Bazel 9.3.2, Python 3.12.

## Setup

rules_pycross picks the hub's contents in `MODULE.bazel`, not from the root `[dependency-groups]`.
A single `uv.repo` with `projects = ["*"]` and `dependency_groups = ["default", "group:test;testonly"]`
exposes the runtime dependencies of every workspace member in the lock's `[manifest]` plus their
conflicting `test` groups (marked `testonly = True` so `py_library` targets cannot depend on
`pytest`). You do not keep a member list, and you do not edit the root `pyproject.toml`. The root
`dev` group is simply never selected.

Registering `@pypi//_variants` with `rules_python`'s `config.add_transition_setting` lets each
`py_test` pick its member's `test` group (`group_app-a_test` or `group_app-b_test`) from the same
`@pypi` hub, while `py_library` targets build with no flags at all.

[`MODULE.bazel`](MODULE.bazel) (trimmed):

```starlark
bazel_dep(name = "rules_pycross")
git_override(
    module_name = "rules_pycross",
    commit = "8d78809639063b1582dfda0bd78a39dc8b967ff8",
    remote = "https://github.com/jvolkman/rules_pycross.git",
)
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.12")

config = use_extension("@rules_python//python/extensions:config.bzl", "config")
config.add_transition_setting(setting = "@pypi//_variants")

uv = use_extension("@rules_pycross//pycross/extensions:uv.bzl", "uv")
uv.workspace(name = "mono", lock_file = "//:project/uv.lock")

# One hub: runtime deps of all members plus testonly `test` groups; no `dev`, no member list.
uv.repo(
    name = "pypi",
    dependency_groups = ["default", "group:test;testonly"],
    projects = ["*"],
    workspace = "mono",
)
use_repo(uv, "pypi")
```

[`BUILD.bazel`](BUILD.bazel) (trimmed):

```starlark
load("@pypi//:requirements.bzl", "requirement")

py_library(
    name = "common",
    srcs = glob(["project/libs/common/src/common/**/*.py"]),
    imports = ["project/libs/common/src"],
    deps = [requirement("requests")],
)
py_library(
    name = "app_a",
    srcs = glob(["project/apps/app-a/src/app_a/**/*.py"]),
    imports = ["project/apps/app-a/src"],
    deps = [":common", requirement("pydantic")],
)
# app_b: the same, with requirement("attrs").

py_test(
    name = "app_a_test",
    srcs = ["project/apps/app-a/tests/test_app_a.py", "project/tools/pytest_main.py"],
    args = ["$(rootpath project/apps/app-a/tests/test_app_a.py)"],
    config_settings = {"@pypi//_variants": "group_app-a_test"},
    main = "project/tools/pytest_main.py",
    deps = [":app_a", requirement("pytest")],
)
# app_b_test: the same, with config_settings = {"@pypi//_variants": "group_app-b_test"}.
```

rules_pycross has no pytest rule of its own, so the tests are plain `py_test` targets running
`project/tools/pytest_main.py`. Everything comes from the shared `project/` (via the `project`
symlink), with no BUILD files added there.

Variant-independent packages (`requests`, `pydantic`, `attrs`, and pytest's shared dependencies
like `pluggy`, `packaging`, and `iniconfig`) reset the variant flags and install once across both
test configurations, so `app_a_test` and `app_b_test` share the exact same installs.

Run: `bazel test //...`

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:common`, `//:app_a`, `//:app_b` | build | deps from `@pypi`, no variant flags needed |
| `bazel test //...` | `//:app_a_test` | pass | `pytest-7.4.4` |
| `bazel test //...` | `//:app_b_test` | pass | `pytest-9.2.0` |

Hub contents (`bazel query '@pypi//:*'`): `attrs`, `pydantic`, `pytest` (`testonly = True`), and
`requests` only. These are the direct runtime and `test`-group deps of the three members.
`requests` comes from `common` and is pulled in through the `common = { workspace = true }`
dependency. `@pypi//ruff` and `@pypi//mypy` do not exist. `pytest` is `testonly`, so a `py_library`
cannot depend on it by accident.

### How the workspace members are treated

rules_pycross treats the editable/virtual entries in `uv.lock` (`common`, `app-a`, `app-b`,
`monorepo`) as *projects*, not as packages. They get no `@pypi//common` or `@pypi//app_a` targets,
no error, and no override. A member's dependency on another member is flattened. For example, a
per-member repo `uv.repo(projects = ["app-a"])` contains `pydantic` and `requests` (the latter via
`common`). The first-party code is then the user's own `py_library` targets, as above.

### One hub vs. per-member repos

- `projects = ["*"]` with `["default", "group:test;testonly"]` gives one hub with no member list at
  all. Tests pick their conflicting `test` group via `config_settings` on `@pypi//_variants`
  (`group_app-a_test` or `group_app-b_test`). Setting `group_test` instead would enable both
  conflicting groups, and the variant resolver rejects it (`Conflicting variants are active
  simultaneously`).
- If you prefer selecting by repo name without `config_settings`, per-member test repos
  (`projects = ["app-a"]`, `dependency_groups = ["group:test;testonly"]`) also work and select
  their single requested group automatically with no `flags` needed.
- `group:*` does not help. It would select both conflicting test groups *and* the root `dev` group.

## Friction / limitations

- **The Slack requirement is met natively.** One lock, one hub, no member list in `MODULE.bazel`,
  `[dependency-groups]` left in place, and no pyproject rewriting. Group selection is a
  `MODULE.bazel` concern (`dependency_groups`), separate from what `pyproject.toml` declares.
- **Disambiguated variant names.** Because both `app-a` and `app-b` name their conflicting group
  `test`, tests targeting the combined `@pypi` hub use `group_app-a_test` and `group_app-b_test`
  rather than `group_test`.
- **The auto-generated `mono__build` repo** contains all groups of all projects plus transitives
  (`["*", "transitive"]`), including `ruff`, `mypy`, and both pytests. It is only used for sdist
  build tools, and its packages are fetched only when an sdist build needs them. Nothing here
  builds from source.
- rules_pycross builds no first-party wheels. The members' hatchling build-system is irrelevant
  here, because Bazel builds the members from `src/` with `py_library`.
