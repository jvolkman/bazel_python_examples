"""Verify active and marker-gated edges of the unishell cycle on Linux."""

import importlib.util
import sys


def main():
    entry = sys.argv[1]
    has_base = importlib.util.find_spec("unishell") is not None
    has_unix = importlib.util.find_spec("unishell_unix") is not None
    has_win = importlib.util.find_spec("unishell_win") is not None
    print(f"entry={entry} unishell={has_base} unishell_unix={has_unix} unishell_win={has_win}")

    if entry in ("unishell", "unishell_unix"):
        assert has_base, "missing unishell"
        assert has_unix, "missing unishell_unix"
        assert not has_win, "unexpected unishell_win on Linux (marker is sys_platform == 'win32')"
    elif entry == "unishell_win":
        assert has_win, "missing unishell_win (direct dep!)"
        assert has_base, "missing unishell"
        assert has_unix, "missing unishell_unix"
    else:
        raise ValueError(f"unknown entry: {entry}")


if __name__ == "__main__":
    main()
