# Workspaces: rules_pycross (`main`)

The uv workspace in [`project/`](../project) (root `monorepo` with a `dev` group, members
`libs/common`, `apps/app-a`, `apps/app-b`, and conflicting per-member `test` groups that need
pytest 7 and pytest 8+), with [rules_pycross](https://github.com/jvolkman/rules_pycross) pinned to
`main` (`bd4800c5`) and rules_python 2.5.1 (toolchain and `py_library`/`py_test`), Bazel 9.3.2,
Python 3.12.

## Setup

rules_pycross picks the hub's contents in MODULE.bazel, not from the root
`[dependency-groups]`. A `uv.repo` with `projects = ["*"]` and `dependency_groups = ["default"]`
gets the runtime dependencies of every workspace member that is in the lock's `[manifest]`. You
don't keep a member list, and you don't need to edit the root pyproject.toml. The root `dev` group
is just never selected.

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
uv.workspace(name = "mono", lock_file = "//:project/uv.lock")

# The one hub: default deps of all members; no `dev`.
uv.repo(
    name = "pypi",
    dependency_groups = ["default"],
    projects = ["*"],
    workspace = "mono",
)

# Test-only views: each requests one member's conflicting `test` group, so the
# variant is selected automatically with no `flags` needed.
uv.repo(
    name = "pypi_test_a",
    dependency_groups = ["group:test;testonly"],
    projects = ["app-a"],
    workspace = "mono",
)
uv.repo(
    name = "pypi_test_b",
    dependency_groups = ["group:test;testonly"],
    projects = ["app-b"],
    workspace = "mono",
)
use_repo(uv, "pypi", "pypi_test_a", "pypi_test_b")
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
    main = "project/tools/pytest_main.py",
    deps = [":app_a", "@pypi_test_a//pytest"],
)
# app_b_test: the same, with @pypi_test_b//pytest.
```

rules_pycross has no pytest rule of its own, so the tests are plain `py_test` targets running
`project/tools/pytest_main.py`. Everything comes from the shared `project/` (via the `project`
symlink), with no BUILD files added there.

Each test repo requests only one member's `test` group (`projects = ["app-a"]` or `["app-b"]`),
so rules_pycross selects that variant automatically with no `flags` attribute needed.

All three repos are views onto one backing package repo (`@mono__pkgs`). Variant-independent
packages (`requests`, `pydantic`, `attrs`, and pytest's shared dependencies) are fetched and
installed once across all three repo configurations, and app-a and app-b see the same versions.

Run: `bazel test //...`

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:common`, `//:app_a`, `//:app_b` | build | deps from `@pypi` |
| `bazel test //...` | `//:app_a_test` | pass | `pytest-7.4.4` |
| `bazel test //...` | `//:app_b_test` | pass | `pytest-9.2.0` |

Hub contents (`bazel query @pypi//...`): `attrs`, `pydantic` and `requests` only. These are the
direct runtime deps of the three members. `requests` comes from `common` and is pulled in through
the `common = { workspace = true }` dependency. `@pypi//ruff` doesn't exist ("no such package"), and
neither does mypy or pytest. `all_requirements` in `@pypi//:requirements.bzl` lists the same three
packages. pytest is `testonly` in the test repos, so a `py_library` can't depend on it by accident.

### How the workspace members are treated

rules_pycross treats the editable/virtual entries in uv.lock (`common`, `app-a`, `app-b`,
`monorepo`) as *projects*, not as packages. They get no `@pypi//common`, `@pypi//app_a` targets, no
error, and no override. A member's dependency on another member is flattened. For example, a
per-member repo `uv.repo(projects = ["app-a"])` contains `pydantic` and `requests` (the latter via
`common`). The first-party code is then the user's own `py_library` targets, as above.

### One hub vs. per-member repos

- `projects = ["*"]` with `["default"]` is enough for the production hub.
- For the conflicting test groups, you need one repo per variant. A flag pins a variant for one
  repo, and two repos are the only way to get both pytest versions in one build.
- Per-member test repos (`projects = ["app-a"]`) are the simplest choice, because each requests
  only one item of the conflict set and needs no `flags`. A repo with `projects = ["*"]` and
  `group:test` also works if it pins `group_app-a_test` or `group_app-b_test`. Pinning `group_test`
  there would select both conflicting groups, and the extension rejects it ("select conflicting
  variants group_app-a_test and group_app-b_test").
- `group:*` doesn't help. It would select both conflicting test groups *and* the root `dev`
  group.

## Friction / limitations

- **The Slack requirement is met natively.** One lock, one hub, no member list,
  `[dependency-groups]` left in place, and no pyproject rewriting. Group selection is
  a MODULE.bazel concern (`dependency_groups`), separate from what pyproject declares.
- **Conflicting groups need one repo per variant.** Targets pick the variant by repo name
  (`@pypi_test_a//pytest` vs. `@pypi_test_b//pytest`). There is no single `@pypi//pytest` that
  follows the test target.
- **Variant flags are per repo.** The same flag name can mean different groups in different
  repos, which is convenient here but worth knowing when reading `.bazelrc` flags.
- **The auto-generated `mono__build` repo** contains all groups of all projects plus transitives
  (`["*", "transitive"]`), including `ruff`, `mypy` and both pytests. It's only used for sdist
  build tools, and its packages are fetched only when an sdist build needs them. Nothing here
  builds from source.
- rules_pycross builds no first-party wheels. The members' hatchling build-system is irrelevant
  here, because Bazel builds the members from `src/` with `py_library`.
