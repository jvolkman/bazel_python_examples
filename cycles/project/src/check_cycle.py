"""Verify both sides of the kedro <-> kedro-telemetry cycle are importable."""

import sys


def main():
    entry = sys.argv[1]
    import kedro
    import kedro_telemetry

    print(f"entry={entry} kedro={kedro.__version__} kedro_telemetry={kedro_telemetry.__version__}")
    # Also check transitive deps unique to each side of the cycle:
    # kedro -> dynaconf, kedro-telemetry -> requests
    import dynaconf
    import requests

    assert kedro.__version__ == "1.8.0", kedro.__version__
    assert kedro_telemetry.__version__ == "0.9.0", kedro_telemetry.__version__
    assert dynaconf is not None
    assert requests is not None


if __name__ == "__main__":
    main()
