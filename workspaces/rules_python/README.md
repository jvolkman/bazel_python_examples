# uv workspace with conflicting `test` groups, using rules_python 2.5.1

The shared workspace ([`project/`](../project)) has a root `monorepo` project.
The root is `package = false` and has a `dev` group with ruff and mypy. The
workspace has three members: `libs/common`, `apps/app-a` and `apps/app-b`.
app-a's `test` group pins pytest 7, and app-b's `test` group needs pytest 8+.
The two groups are declared conflicting, so `uv.lock` has `pytest 7.4.4` and
`pytest 9.2.0` on separate forks.

**Summary:** `pip.parse(uv_lock = ...)` fails on this lock with a hard error.
The setup that works uses ONE hub, `@monorepo_deps`, for the whole workspace.
It is built from three requirements files, each exported from the same
`uv.lock` with `uv export --frozen`:

- `prod`: all members, with no `dev` group and no `test` groups.
- `app_a_test`: app-a's closure plus app-a's `test` group.
- `app_b_test`: app-b's closure plus app-b's `test` group.

Each file is bound to a custom `pip.default` platform. Each platform is Linux
x86_64 plus one value of a `//:deps` flag. Each test sets the flag on itself
through `py_test(config_settings = ...)`. `bazel test //...` runs both test
suites, with pytest 7 and pytest 9 respectively.

## Setup

`MODULE.bazel` (trimmed):

```starlark
bazel_dep(name = "rules_python", version = "2.5.1")

python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(is_default = True, python_version = "3.14")

# Allow py_binary/py_test to set //:deps through `config_settings`.
config = use_extension("@rules_python//python/extensions:config.bzl", "config")
config.add_transition_setting(setting = "//:deps")

pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")

# One custom "platform" per dependency set: Linux x86_64 + a value of //:deps.
[
    pip.default(
        arch_name = "x86_64",
        config_settings = [
            "@platforms//cpu:x86_64",
            "@platforms//os:linux",
            "//:deps_" + deps,
        ],
        os_name = "linux",
        platform = "linux_x86_64_" + deps,
        whl_abi_tags = ["abi3", "cp{major}{minor}"],
        whl_platform_tags = ["linux_x86_64", "manylinux_*_x86_64"],
    )
    for deps in ["prod", "app_a_test", "app_b_test"]
]

pip.parse(
    hub_name = "monorepo_deps",
    python_version = "3.14",
    requirements_by_platform = {
        "//requirements:prod.txt": "linux_x86_64_prod",
        "//requirements:app_a_test.txt": "linux_x86_64_app_a_test",
        "//requirements:app_b_test.txt": "linux_x86_64_app_b_test",
    },
    # Required: without it only the host platform is evaluated, and every
    # file above is silently ignored.
    target_platforms = [
        "linux_x86_64_prod",
        "linux_x86_64_app_a_test",
        "linux_x86_64_app_b_test",
    ],
)
use_repo(pip, "monorepo_deps")
```

`BUILD.bazel` (trimmed):

```starlark
string_flag(
    name = "deps",
    build_setting_default = "prod",
    values = ["prod", "app_a_test", "app_b_test"],
)

[config_setting(name = "deps_" + d, flag_values = {":deps": d}) for d in ["prod", "app_a_test", "app_b_test"]]

py_library(
    name = "common",
    srcs = glob(["project/libs/common/src/common/**/*.py"]),
    imports = ["project/libs/common/src"],
    deps = ["@monorepo_deps//requests"],
)

py_library(
    name = "app_a",
    srcs = glob(["project/apps/app-a/src/app_a/**/*.py"]),
    imports = ["project/apps/app-a/src"],
    deps = [":common", "@monorepo_deps//pydantic"],
)
# app_b: same, with @monorepo_deps//attrs

py_test(
    name = "app_a_test",
    srcs = ["project/apps/app-a/tests/test_app_a.py", "project/tools/pytest_main.py"],
    args = ["$(rootpath project/apps/app-a/tests/test_app_a.py)"],
    config_settings = {"//:deps": "app_a_test"},
    main = "project/tools/pytest_main.py",
    deps = [":app_a", "@monorepo_deps//pytest"],
)
# app_b_test: same, with config_settings = {"//:deps": "app_b_test"}
```

The requirements files are generated, never written by hand. The export flags
live in [`requirements/BUILD.bazel`](requirements/BUILD.bazel):

| File | `uv export --frozen --no-emit-workspace ...` |
| --- | --- |
| `prod.txt` | `--all-packages --no-dev` |
| `app_a_test.txt` | `--package=app-a --group=test --no-dev` |
| `app_b_test.txt` | `--package=app-b --group=test --no-dev` |

```sh
bazel run //requirements:prod.update        # likewise app_a_test.update, app_b_test.update
bazel test //requirements:all               # fails if a file is out of date with uv.lock
```

Run everything:

```sh
cd workspaces/rules_python
bazel test //...
```

## Result

| Target | `bazel test //...` | Observed |
| --- | --- | --- |
| `//:common`, `//:app_a`, `//:app_b` | build | resolve `@monorepo_deps` in the default `prod` configuration |
| `//:app_a_test` | pass | `platform linux -- Python 3.14.10, pytest-7.4.4, pluggy-1.7.0`, 2 passed |
| `//:app_b_test` | pass | `platform linux -- Python 3.14.10, pytest-9.2.0, pluggy-1.7.0`, 2 passed |
| `//requirements:{prod,app_a_test,app_b_test}_test` | pass | files match `uv export` of `uv.lock` |

How the single hub behaves:

- Wheels that are the same in several sets resolve to one repository. For
  example, `@monorepo_deps//pydantic` selects
  `monorepo_deps_314_pydantic_py3_none_any_3f7b3477` for both
  `cp314_linux_x86_64_prod` and `cp314_linux_x86_64_app_a_test`. Only `pytest`
  gets two repositories, one per test platform.
- The `dev` group never reaches Bazel. No `ruff` or `mypy` repositories are
  created, and `cquery 'deps(//:app_b)'` shows no pytest, ruff or mypy.
- If a target in the default configuration depends on `@monorepo_deps//pytest`,
  it fails at analysis time:

  ```
  configurable attribute "actual" in @@rules_python++pip+monorepo_deps//pytest:_no_matching_repository
  doesn't match this configuration: No matching wheel for current configuration's Python version and platform.
  ... This distribution supports the following Python configuration settings:
      //_config:is_cp314_linux_x86_64_app_a_test
      //_config:is_cp314_linux_x86_64_app_b_test
  ```

### What the Slack user asked for

- **One hub for the whole workspace:** yes, `@monorepo_deps`.
- **Keep `[dependency-groups]` (with `dev`) in the root `pyproject.toml`:**
  yes. Nothing in the pyproject was changed. `--no-dev` leaves out `dev` at
  export time.
- **An all-members hub without a hand-maintained member list:** yes.
  `uv export --all-packages` walks every workspace member that uv knows about.
  A new member shows up after `bazel run //requirements:prod.update`, and
  `//requirements:prod_test` fails until you run it.
- **Default build packages (setuptools, wheel, build):** not needed. The hub
  holds wheels only, and Bazel builds the members from their `src/` dirs.
- **Workaround still needed:** an export step in a `bazel run` target, plus one
  requirements file per conflicting group.

## What happened with the naive approach

The naive setup is in [`naive/`](naive). It is a separate module listed in
`.bazelignore`, and it is one hub from the shared lock:

```starlark
pip.parse(hub_name = "pypi", python_version = "3.14", uv_lock = "//:project/uv.lock")
```

`cd naive && bazel build //...` fails while Bazel evaluates the module
extension:

```
ERROR: .../external/rules_python+/python/private/pypi/hub_builder.bzl:366:13: Traceback (most recent call last):
  ...
Error in fail: attempting to override an existing repo 'pypi_314_pytest_py3_none_any_b090cdf5_linux_x86_64'
for config setting 'struct(target_platforms = ("cp314_linux_x86_64",), version = "3.14")'
with a new repo 'pypi_314_pytest_py3_none_any_07acdcf8_linux_x86_64'
ERROR: Analysis of target '//:app_a_test' failed; build aborted:
error evaluating module extension @@rules_python+//python/extensions:pip.bzl%pip
```

The reader (`_uv_lock_package_platforms` in
`python/private/pypi/parse_requirements.bzl`) starts from every virtual or
editable root. It follows `dependencies`, every `optional-dependencies` table
and every `dev-dependencies` table, so both `test` groups are followed. Both
pytest forks only have Linux/x86_64 `resolution-markers`, so both land on
`cp314_linux_x86_64`. The reader doesn't know about `[tool.uv] conflicts` and
has no option to choose or skip groups.

Two more points, from reading the source (the hard error stops anything from
being observed):

- Even without the conflict, the same walk would put `ruff` and `mypy` (the
  root `dev` group) and both `test` groups into the hub. The 2.5.0 change log
  for `uv_lock` describes this on purpose: "Package platforms follow dependency
  markers from virtual and editable workspace roots, including development
  dependency groups."
- Workspace members (`common`, `app-a`, `app-b`, `monorepo`) are virtual or
  editable sources. They have no wheel or sdist, so they get `is_exposed =
  False` and are left out of the hub without an error.

How the requirements-file path treats members: by default, `uv export` without
`--no-emit-workspace` writes `-e ./apps/app-a`, `-e ./apps/app-b` and
`-e ./libs/common`. I fed that file to `pip.parse(requirements_lock = ...)`.
The `-e` lines were silently ignored, and the hub only contained the 11
third-party packages. The working setup passes `--no-emit-workspace` so the
files say what they mean.

## Friction / limitations

1. **`uv_lock` can't be used with conflicting groups, and it can't leave out
   `dev`.** You have to switch to exported requirements files. The plain way
   is one `pip.parse` per set (`@pypi`, `@pypi_app_a_test`,
   `@pypi_app_b_test`), but then each test mixes two hubs, and shared wheels
   get a second repository. A single hub needs the custom platform and flag
   setup shown above.
2. **The custom-platform setup is undocumented territory.** It uses only
   public APIs: `pip.default(platform, config_settings, ...)`,
   `requirements_by_platform`, `target_platforms`, and
   `config.add_transition_setting`. But `pip.default` platforms are meant for
   OS, arch and libc variants, not dependency sets. It is easy to get wrong.
   Without `target_platforms`, the debug log says
   `File @@//requirements:prod.txt will be ignored because there are no configured platforms`
   and the hub ends up empty (`packages = {}`). That only shows up later as
   `no such package '@@rules_python++pip+pypi//pydantic'`.
3. **Each test runs in its own configuration.** A test with
   `config_settings = {"//:deps": ...}` builds its whole closure, including
   `//:common` and `//:app_a`, in a transitioned configuration. This is cheap
   for pure-Python code, but it means separate output directories. A target
   that serves both apps would need one transition value per app.
4. **`uv export` strips extras.** This workspace has no extras edges, so
   nothing breaks here. The same export script restores them anyway (see
   `../../conflicts/rules_python/README.md` and
   bazel-contrib/rules_python#4168, closed as not planned).
5. **The hub name `pypi` is reserved.** With `hub_name = "pypi"`, rules_python
   2.5.1 warns:
   `The PyPI hub name 'pypi' is reserved (module 'workspaces_rules_python'). Please rename your hub, otherwise a future release will rename it to 'workspaces_rules_python_pypi'.`
6. **Upcoming:** bazel-contrib/rules_python#4395 (`pip.configure` to choose
   which packages a hub exposes), #4428 (`pip.configure.testonly`) and #4429
   (`pip.configure.venv` for named package sets). They are modeled on
   `[dependency-groups]` and address bazel-contrib/rules_python#3413
   ("`pip.parse` should allow hiding transitive dependencies"). All three are
   still open and not on `main` as of this writing. They would let you leave
   out `dev` and mark `test` packages as `testonly`. It isn't clear yet
   whether they also handle two conflicting forks of one package in one
   `uv_lock` hub, which is what fails above.
