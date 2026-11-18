# uv workspace with conflicting test groups, using rules_py 2.0.0-alpha.11

Module: `workspaces_rules_py`. It uses rules_py's own interpreter provisioning
(`python_interpreters`, Python 3.12) and rules_py's `py_library` and
`py_pytest_test`.

```sh
bazel test //...        # //:app_a_test, //:app_b_test, //bazel/prod:smoke_test
bazel build //naive:app_a   # the naive attempt (tagged manual)
```

## 1. Setup

There is one hub, `@pypi`, over the **unchanged shared `uv.lock`**. The real
root `project/pyproject.toml` is not given to rules_py at all. Instead, the
lock is registered twice, with two small Bazel-only pyproject.toml files:

```starlark
# MODULE.bazel
uv = use_extension("@rules_py//uv:extensions.bzl", "uv")
uv.declare_hub(hub_name = "pypi")
uv.project(hub_name = "pypi", lock = "//:project/uv.lock", pyproject = "//bazel/prod:pyproject.toml")
uv.project(hub_name = "pypi", lock = "//:project/uv.lock", pyproject = "//bazel/tests:pyproject.toml")

# Mandatory for every editable workspace member in uv.lock (see section 4).
[
    uv.override_package(name = name, lock = "//:project/uv.lock", target = target)
    for name, target in [("common", "//:common"), ("app-a", "//:app_a"), ("app-b", "//:app_b")]
]
use_repo(uv, "pypi")
```

```toml
# bazel/prod/pyproject.toml: no [dependency-groups], so rules_py creates one
# implicit group named "prod" containing every member in uv.lock's [manifest].
[project]
name = "prod"
version = "0.1.0"
requires-python = ">=3.12"
```

```toml
# bazel/tests/pyproject.toml: member test groups restated at the "root"
[project]
name = "tests"
version = "0.1.0"
requires-python = ">=3.12"

[dependency-groups]
app-a-test = ["app-a", "pytest>=7,<8"]
app-b-test = ["app-b", "pytest>=8"]
```

```starlark
# BUILD.bazel (abridged)
py_library(
    name = "app_a",
    srcs = glob(["project/apps/app-a/src/app_a/**/*.py"]),
    imports = ["project/apps/app-a/src"],
    deps = [":common", "@pypi//pydantic"],
)

py_pytest_test(
    name = "app_a_test",
    srcs = ["project/apps/app-a/tests/test_app_a.py"],
    dep_group = "app-a-test",   # transition: this test sees pytest 7.4.4
    deps = [":app_a", "@pypi//pytest"],
)
```

The hub has three groups: `prod`, `app-a-test` and `app-b-test`. Its packages
are the members, their dependencies, and pytest with its dependencies. There
is no ruff, mypy, or any other package from the `dev` group.
`.bazelrc` sets `common --@pypi//dep_group=prod` as the default.

## 2. Result

`bazel test //...` (one invocation, Bazel 9.3.2):

| Target | Status | Observed |
| --- | --- | --- |
| `//:common`, `//:app_a`, `//:app_b` | build | (with the default `dep_group=prod`) |
| `//:app_a_test` | pass | `platform linux -- Python 3.12.13, pytest-7.4.4` |
| `//:app_b_test` | pass | `platform linux -- Python 3.12.13, pytest-9.2.0` |
| `//bazel/prod:smoke_test` | pass | imports app_a and app_b (`requests 2.34.2`); `pytest`, `ruff` and `mypy` are not importable |

Naive attempts:

| Setup | Status | Observed |
| --- | --- | --- |
| shared root pyproject, no overrides | fail (extension) | `Editable package app_a in lockfile @@//:project/uv.lock doesn't have a mandatory uv.override_package(target = ...) annotation!` |
| shared root pyproject, with overrides (`//naive:app_a`) | fail (analysis) | hub has only group `dev`; `no such package '@@rules_py++uv+pypi_naive//pydantic'` |

## 3. What happened with the naive approach

First, I pointed `uv.project()` at `project/pyproject.toml` and `project/uv.lock`
as they are. The module extension failed immediately:

```
Error in fail: Editable package app_a in lockfile @@//:project/uv.lock doesn't have a mandatory
`uv.override_package(target = ...)` annotation!
```

After adding the three `uv.override_package(target = ...)` tags, the hub
loaded. However, it contains exactly the root `[dependency-groups]`, which is
only `dev`:

```
$ bazel query @pypi_naive//... | grep -v ':pkg$\|:whl$'
@pypi_naive//dep_group:dev
@pypi_naive//ast_serialize  @pypi_naive//librt  @pypi_naive//mypy  @pypi_naive//mypy_extensions
@pypi_naive//pathspec  @pypi_naive//ruff  @pypi_naive//typing_extensions
```

None of requests, pydantic, attrs or pytest are in the hub, so any first-party
target fails:

```
ERROR: no such package '@@rules_py++uv+pypi_naive//pydantic': BUILD file not found in directory
'pydantic' of external repository @@rules_py++uv+pypi_naive.
```

This is exactly the problem described in the Slack thread. If
`[dependency-groups]` is present in the root pyproject, it replaces the
all-members default. The members' own deps then belong to no group unless a
group names the member packages.

## 4. Friction / limitations

- **Keeping `[dependency-groups]` in the real root file.** rules_py offers no
  attribute for this: `uv.project()` has no group filter or "include members"
  switch. The way around it is to give `uv.project()` a different
  pyproject.toml. A 4-line stub with no `[dependency-groups]` (`bazel/prod`)
  gives the all-members group with no hand-maintained member list. Members are
  read from uv.lock's `[manifest]`, and `dev` never enters the hub. This file
  is static, so it is simpler than generating a rewritten root pyproject in a
  module extension. In alpha.11, rules_py reads only `[project].name`,
  `[dependency-groups]` and `[tool.uv] no-binary-package` from this file. If
  the real root sets `no-binary-package`, it must be copied into the stub.
- **Member dependency groups are ignored.** rules_py builds groups only from
  the pyproject.toml passed to `uv.project()`. Per-group versions are taken
  only from the virtual root package's `dev-dependencies` in uv.lock, so
  app-a's and app-b's `test` groups are invisible. Each test environment must
  therefore be restated as a root-level group (`bazel/tests`), including its
  specifier. The specifier decides which locked pytest is picked (7.4.4 vs
  9.2.0). Neither uv nor PEP 735 lets a root group include another package's
  group, so this list is unavoidable.
- **Same lock, two `uv.project()`s.** This is how one hub gets both the
  implicit all-members group and explicit test groups. It works in alpha.11:
  `@pypi//app_a` selects `@project__prod//:app_a` or `@project__tests//:app_a`,
  depending on `dep_group`. The overrides key on the lock label, so they apply
  to both projects. This combination is not documented, though. Group names
  must be unique per hub (`Conflict on configuration name ...`), and
  `[project].name` must be unique across all hubs, because it names the
  generated `project__<name>` repository. See the conflicts README and
  aspect-build/rules_py#1093.
- **Packaged workspace members.** Every `source = { editable = ... }` package
  hard-fails unless it has `uv.override_package(target = ...)`. Modification-only
  overrides are rejected. The virtual root (`monorepo`, `package = false`) and
  virtual members are skipped. The override target is the user's own
  `py_library`. Its third-party deps come from the same hub, and Bazel builds
  the member from `src/`; the hatchling build is never used.
- **Dependency groups are configurations.** Hub labels are
  `target_compatible_with` their groups only. Without a default
  `--@pypi//dep_group`, `bazel build //:app_a` fails with `Target //:app_a is
  incompatible and cannot be built`, and `bazel build //...` silently skips the
  libraries. Each extra group is also another configuration of the
  first-party code, so it is analyzed and built once per group.
- **`[tool.uv] conflicts` is not parsed** (aspect-build/rules_py#1510). Here it
  doesn't matter, because each test group pins pytest by specifier and no
  shared edge is gated on the `group-5-app-*-test` markers. In other
  workspaces, a conflict-gated edge would be silently dropped; see the
  conflicts example.
