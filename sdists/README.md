# Scenario 4: building C-extension sdists (`crcmod` and `datrie`)

Some PyPI packages ship only source distributions (`.tar.gz` sdists) with no pre-built wheels. [`project/`](project) locks two sdist-only C extensions on Python 3.12 (Linux x86_64), neither of which needs external system C libraries:

- `crcmod==1.7`: legacy `setup.py`-only package (`from distutils.core import setup`) compiling `crcmod._crcfunext`. Its `setup.py` silently falls back to pure Python if C compilation fails.
- `datrie==0.8.3`: PEP 517 `pyproject.toml` package (`[build-system] requires = ["setuptools>=40.8.0", "wheel", "Cython"]`) that compiles a C static library (`libdatrie.a` via `setuptools` `build_clib`) and links a Cython extension (`datrie.*.so`).

Each Bazel module runs `//:sdist_test` ([`project/src/check_sdists.py`](project/src/check_sdists.py)), which imports `crcmod._crcfunext` and `datrie`, asserts that both loaded compiled `.so` extensions, and checks a CRC-32C checksum and trie lookup.

## Comparison

| | [rules_python](rules_python/README.md) | [rules_pycross](rules_pycross/README.md) | [rules_py](rules_py/README.md) |
| --- | --- | --- | --- |
| Where sdists are compiled | Repository fetch (`pip wheel` on the host) | Sandboxed Bazel build action (`PycrossPep517Build`) | Sandboxed Bazel build action (`pep517_native_whl`) |
| Compiler / archiver used | Host `clang` + host `ar` (outside Bazel's CC toolchain) | Bazel CC toolchain | Bazel CC toolchain |
| Build dependencies (`setuptools`, `wheel`, `cython`) | Downloaded from PyPI on the fly during fetch (unpinned, requires network) | Pinned either in a `[dependency-groups]` group in the same `uv.lock` (auto-discovered, never exposed in `@pypi`) or in an optional separate `build_tools_repo` lock; `build` frontend is shipped internally | Must be pinned in the same `uv.lock` and the same `dep_group` as the runtime packages, including `build` itself |
| Naive setup (shared `uv.lock`) | `crcmod` builds, then `datrie` fails during fetch: `No such file or directory: '/tools/llvm/bin/llvm-ar'` (baked into `python-build-standalone`'s `sysconfig`) | Fails build: `Backend 'setuptools.build_meta:__legacy__' is not available.` (`setuptools`/`wheel`/`cython` are not in `project/uv.lock`) | Fails extension evaluation: `Unable to resolve a default version for requirement "build" in @@//:project/uv.lock` |
| Working setup | `pip.parse(uv_lock = "//:project/uv.lock", environment = {"AR": "ar"})` | Either add `setuptools`/`wheel`/`cython` to a `[dependency-groups]` group in `uv.lock` (no extra lock needed), or keep `project/uv.lock` unchanged as shown here by pointing `uv.package(name = "*", build_tools_repo = "build_tools")` at a separate `build_tools/uv.lock` | Maintain a Bazel-only `pyproject.toml` and relocked `uv.lock` with `build`, `setuptools`, `wheel`, and `cython` added directly to `[project].dependencies` |
| Uses shared `uv.lock` as-is | Yes | Yes | No (build tools must be in the same lock and group) |
| Hermetic / RBE-cacheable / cross-compilable | No (host fetch action, network access, leaks `~/.cache/pip/wheels`) | Yes (and repairs output wheels to `manylinux`) | Yes (for builds; cross-compilation uses Bazel CC toolchains) |

## Modules

- [`rules_python/`](rules_python/README.md) (rules_python 2.5.1)
- [`rules_pycross/`](rules_pycross/README.md) (rules_pycross `main`, `e81bcb31`)
- [`rules_py/`](rules_py/README.md) (rules_py 2.0.0-alpha.11)
