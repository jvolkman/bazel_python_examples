# Workspaces: rules_pycross 2.2.0

The uv workspace in [`project/`](../project) (root `monorepo` with a `dev` group, members
`libs/common`, `apps/app-a`, `apps/app-b`, and conflicting per-member `test` groups that need
pytest 7 and pytest 8+), with [rules_pycross](https://github.com/jvolkman/rules_pycross) 2.2.0 and
rules_python 2.5.1 (toolchain and `py_library`/`py_test`), Bazel 9.3.2, Python 3.12.

## Setup

rules_pycross picks the hub's contents in `MODULE.bazel`, not from the root `[dependency-groups]`.
A `uv.repo` with `projects = ["*"]` and `dependency_groups = ["default"]` exposes the runtime
dependencies of every workspace member in the lock's `[manifest]`. You do not keep a member list
for the runtime hub, and you do not edit the root `pyproject.toml`. The root `dev` group is simply
never selected.

For the conflicting per-member `test` groups, two small test-only repos (`@pypi_test_a` and
`@pypi_test_b`) each request one member's `test` group (`group:test;testonly`). Because each repo
requests only one item of the conflict set, rules_pycross selects its variant automatically with no
`flags` and no `config_settings` boilerplate on test targets.

[`MODULE.bazel`](MODULE.bazel) (trimmed):

```starlark
bazel_dep(name = "rules_pycross", version = "2.2.0")
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.12")

uv = use_extension("@rules_pycross//pycross/extensions:uv.bzl", "uv")
uv.workspace(name = "mono", lock_file = "//:project/uv.lock")

# The hub: default deps of all members; no `dev`.
uv.repo(
    name = "pypi",
    dependency_groups = ["default"],
    projects = ["*"],
    workspace = "mono",
)

# Test-only views: each requests one member's conflicting `test` group, so the
# variant is selected automatically with no `flags` or `config_settings` needed.
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
py_library(
    name = "common",
    srcs = glob(["project/libs/common/src/common/**/*.py"]),
    imports = ["project/libs/common/src"],
    deps = ["@pypi//requests"],
)
py_library(
    name = "app_a",
    srcs = glob(["project/apps/app-a/src/app_a/**/*.py"]),
    imports = ["project/apps/app-a/src"],
    deps = [":common", "@pypi//pydantic"],
)
# app_b: the same, with @pypi//attrs.

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

All three repos are views onto one backing package repo (`@mono__pkgs`). Variant-independent
packages (`requests`, `pydantic`, `attrs`, and pytest's shared dependencies like `pluggy`,
`packaging`, and `iniconfig`) reset the variant flags and install once across all three repo
configurations.

Run: `bazel test //...`

## Result

| Command | Target | Status | Observed |
| --- | --- | --- | --- |
| `bazel test //...` | `//:common`, `//:app_a`, `//:app_b` | build | deps from `@pypi` |
| `bazel test //...` | `//:app_a_test` | pass | `pytest-7.4.4` |
| `bazel test //...` | `//:app_b_test` | pass | `pytest-9.2.0` |

Hub contents (`bazel query '@pypi//:*'`): `attrs`, `pydantic`, and `requests` only. These are the
direct runtime deps of the three members. `requests` comes from `common` and is pulled in through
the `common = { workspace = true }` dependency. `@pypi//ruff`, `@pypi//mypy`, and `@pypi//pytest`
do not exist. `pytest` is `testonly` in `@pypi_test_a` and `@pypi_test_b`, so a `py_library` cannot
depend on it by accident.

### How the workspace members are treated

rules_pycross treats the editable/virtual entries in `uv.lock` (`common`, `app-a`, `app-b`,
`monorepo`) as *projects*, not as packages. They get no `@pypi//common` or `@pypi//app_a` targets,
no error, and no override. A member's dependency on another member is flattened. For example, a
per-member repo `uv.repo(projects = ["app-a"])` contains `pydantic` and `requests` (the latter via
`common`). The first-party code is then the user's own `py_library` targets, as above.

### One hub vs. per-member test repos

- `projects = ["*"]` with `["default"]` keeps the production hub member-list-free.
- Per-member test repos (`projects = ["app-a"]`, `dependency_groups = ["group:test;testonly"]`) are
  ergonomic here because each requests only one item of the conflict set, selects its variant
  automatically, and lets tests depend on `@pypi_test_a//pytest` without repeating
  `config_settings` on every test target.
- A single combined hub (`projects = ["*"]`, `dependency_groups = ["default", "group:test;testonly"]`)
  also works if you register `@pypi//_variants` with `rules_python`'s `config.add_transition_setting`
  and set `config_settings = {"@pypi//_variants": "group_app-a_test"}` on each test (the same
  pattern shown in [`conflicts/rules_pycross/`](../../conflicts/rules_pycross/README.md)).
- `group:*` does not help. It would select both conflicting test groups *and* the root `dev` group.

## Friction / limitations

- **The Slack requirement is met natively.** One lock, one runtime hub with no member list,
  `[dependency-groups]` left in place, and no pyproject rewriting. Group selection is a
  `MODULE.bazel` concern (`dependency_groups`), separate from what `pyproject.toml` declares.
- **Per-member test repos vs. per-test flags.** Splitting tests into `@pypi_test_a` and
  `@pypi_test_b` keeps `BUILD.bazel` clean at the cost of one `uv.repo` per conflicting test group;
  the single-hub `config_settings` alternative avoids extra repos at the cost of repeating
  `group_<project>_test` on each test.
- **The auto-generated `mono__build` repo** contains all groups of all projects plus transitives
  (`["*", "transitive"]`), including `ruff`, `mypy`, and both pytests. It is only used for sdist
  build tools, and its packages are fetched only when an sdist build needs them. Nothing here
  builds from source.
- rules_pycross builds no first-party wheels. The members' hatchling build-system is irrelevant
  here, because Bazel builds the members from `src/` with `py_library`.
