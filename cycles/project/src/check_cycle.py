"""Verify active and marker-gated edges of the Apache Airflow cycle on Python 3.14."""

import importlib.util
import sys


def has_mod(name):
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def main():
    entry = sys.argv[1]
    has_airflow = has_mod("airflow")
    has_std = has_mod("airflow.providers.standard")
    has_tinkerpop = has_mod("airflow.providers.apache.tinkerpop")
    has_gremlin = has_mod("gremlin_python")
    print(
        f"entry={entry} py={sys.version_info[:2]} airflow={has_airflow} "
        f"standard={has_std} tinkerpop={has_tinkerpop} gremlin={has_gremlin}"
    )

    if entry == "airflow":
        assert has_airflow, "missing airflow"
        assert has_std, "missing airflow.providers.standard"
        assert not has_tinkerpop, "unexpected tinkerpop on Python 3.14 (marker is python_full_version < '3.14')"
        assert not has_gremlin, "unexpected gremlin_python on Python 3.14 (only depended on by tinkerpop)"
    elif entry == "airflow_imports":
        assert has_airflow, "missing airflow"
        assert has_std, "missing airflow.providers.standard"
    elif entry == "tinkerpop":
        assert has_tinkerpop, "missing tinkerpop (direct dep!)"
        assert has_gremlin, "missing gremlin_python (dep of tinkerpop!)"
        assert has_airflow, "missing airflow"
        assert has_std, "missing airflow.providers.standard"
    else:
        raise ValueError(f"unknown entry: {entry}")


if __name__ == "__main__":
    main()
