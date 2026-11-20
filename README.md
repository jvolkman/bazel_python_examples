# bazel_python_examples

Side-by-side examples of how three Bazel Python rulesets handle the same `uv.lock` files.

| Ruleset | Version | Python rules used |
| --- | --- | --- |
| [rules_python](https://github.com/bazel-contrib/rules_python) | 2.5.1 | its own `py_library` / `py_test` |
| [rules_pycross](https://github.com/jvolkman/rules_pycross) | 2.2.0 | rules_python's `py_library` / `py_test` |
| [rules_py](https://github.com/aspect-build/rules_py) | 2.0.0-alpha.11 (BCR module `rules_py`) | its own `py_library` / `py_test` / `py_pytest_test` |

All modules use Bazel 9.3.2 on Linux x86_64. The `conflicts/`, `workspaces/`, `sdists/`, and `wheel_selection/` examples run on Python 3.12. The `cycles/` example runs on Python 3.14 so that Airflow's `python_version != "3.14"` cycle edge is inactive.

## Scenarios

| Scenario | What it tests | Overview |
| --- | --- | --- |
| `conflicts/` | Mutually exclusive extras (`torch` CPU vs CUDA 13.2) in one lock file using `[tool.uv] conflicts` and custom indexes | [conflicts/README.md](conflicts/README.md) |
| `workspaces/` | A uv workspace with a root `dev` group and conflicting per-member `test` groups (`pytest` 7 vs 9) | [workspaces/README.md](workspaces/README.md) |
| `cycles/` | Apache Airflow 3.4.0, which has an 8-package base cycle plus a 9th marker-gated `apache-tinkerpop` provider | [cycles/README.md](cycles/README.md) |
| `sdists/` | Building two sdist-only C extensions (`crcmod==1.7` legacy `setup.py` and `datrie==0.8.3` PEP 517 Cython + `build_clib`) from a shared lock | [sdists/README.md](sdists/README.md) |
| `wheel_selection/` | Multi-tag Linux wheel selection (`bcrypt==5.0.0` and `cbor2==6.3.0`) across default glibc, glibc `2.17`/`2.34`, and Alpine/musl `1.2`/`1.1` | [wheel_selection/README.md](wheel_selection/README.md) |

Each scenario directory contains a shared `project/` directory (plain `pyproject.toml`, `uv.lock`, and Python sources with no Bazel files) alongside three standalone Bazel modules: `rules_python/`, `rules_pycross/`, and `rules_py/`. Each module symlinks `project` to `../project` and includes its own README covering the setup, test output, naive failure, and tradeoffs.

Run any module with:

```sh
cd conflicts/rules_pycross && bazel test //...
```

Every module's `bazel test //...` passes. Naive or broken setups are kept as `manual` targets or in nested modules excluded by `.bazelignore` so you can reproduce them directly.

## Bugs and limitations found

In rules_py 2.0.0-alpha.11:

- Marker-gated dependency cycles both over-include and under-include packages. `collect_sccs` collapses all members of a strongly connected component into one `py_library`, unions their external dependencies (leaking `gremlin_python` into `@pypi//apache_airflow` on Python 3.14), and gates each member's wheel on its inbound intra-SCC edge markers (replacing `@pypi//apache_airflow_providers_apache_tinkerpop` with `:empty` on Python 3.14 even when a target depends on it directly).
- `[tool.uv] conflicts` is unsupported, so conflict-gated edges are dropped without error ([#1510](https://github.com/aspect-build/rules_py/issues/1510)).
- Generated `project__<[project].name>` repositories are global to the extension. Two `uv.project()` calls on different hubs with the same `[project].name` overwrite each other (related: [#1093](https://github.com/aspect-build/rules_py/issues/1093)).
- Hub labels are incompatible outside a selected `dep_group`, so `bazel build //...` skips libraries unless `.bazelrc` sets a default.
- Sdist builds require `build` and all PEP 517 build backends (`setuptools`, `wheel`, `cython`) to be locked in the same `uv.lock` (there is no separate build-tools repo). Auto-discovered `[build-system].requires` packages resolve from `private/build_deps` regardless of `dep_group`, but `default_build_dependencies` (including `build` itself) and `uv.annotate_packages` build dependencies still resolve through surface aliases and must be active in the consuming `dep_group`.
- Wheel selection defaults `platform_version` from a host glibc probe (`@rules_py_uv_host`), so different Linux hosts silently pick different `manylinux` wheels unless the private `@rules_py//uv/private/constraints/platform:platform_version` flag is pinned.

In rules_python 2.5.1:

- `pip.parse(uv_lock = ...)` ignores `[tool.uv] conflicts` and cannot filter extras or dependency groups (requiring separate per-variant `uv.lock` files or `uv export` to `requirements.txt`).
- When using `uv export` to `requirements.txt` instead of `uv_lock`, stripped transitive extras are not restored ([#4168](https://github.com/bazel-contrib/rules_python/issues/4168), closed as not planned), which breaks CUDA `torch` unless restored by hand.
- `pip.parse(uv_lock = ...)` fails analysis on dependency cycles unless every cycle is merged and listed by hand in `experimental_requirement_cycles`, which is static and cannot respect version or platform markers.
- Sdist builds run `pip wheel` during repository fetch on the host (non-hermetic, network-dependent, leaks wheels through `~/.cache/pip`), and `setuptools` `build_clib` sdists fail unless `environment = {"AR": "ar"}` overrides `python-build-standalone`'s `/tools/llvm/bin/llvm-ar`.
- Built-in Linux platforms are glibc-only with an uncapped `manylinux_*` glob and Minimal Version Selection (preferring the lowest matching `manylinux`/`musllinux` version rather than the highest compatible tag); targeting musl or capping glibc requires custom `pip.default` platforms in `MODULE.bazel`.
- A multi-file `requirements_by_platform` hub is empty if `target_platforms` is omitted.
- `pip.configure(dependency_groups = ...)` is in progress upstream (PRs #4395, #4428, #4429).
