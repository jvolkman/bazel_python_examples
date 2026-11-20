"""Inspect selected wheel tags from an installed distribution, .whl file, or wheel dir."""

import importlib.metadata
import os
import sys
import zipfile


def _parse_tags(wheel_metadata: str) -> list[str]:
    return [
        line.split(":", 1)[1].strip()
        for line in wheel_metadata.splitlines()
        if line.startswith("Tag:")
    ]


def tags_from_path(path: str) -> list[str]:
    if os.path.isdir(path):
        whls = [f for f in os.listdir(path) if f.endswith(".whl")]
        if len(whls) == 1:
            path = os.path.join(path, whls[0])
        else:
            wheel_metas = []
            for root, _, files in os.walk(path):
                if root.endswith(".dist-info") and "WHEEL" in files:
                    wheel_metas.append(os.path.join(root, "WHEEL"))
            if len(wheel_metas) != 1:
                raise AssertionError(
                    f"Expected 1 .whl or .dist-info/WHEEL under {path}, found {wheel_metas}"
                )
            with open(wheel_metas[0], encoding="utf-8") as f:
                return _parse_tags(f.read())
    with zipfile.ZipFile(path) as zf:
        wheel_files = [n for n in zf.namelist() if n.endswith(".dist-info/WHEEL")]
        if len(wheel_files) != 1:
            raise AssertionError(f"Expected 1 WHEEL metadata in {path}, found {wheel_files}")
        return _parse_tags(zf.read(wheel_files[0]).decode("utf-8"))


def tags_from_dist(dist_name: str) -> list[str]:
    text = importlib.metadata.distribution(dist_name).read_text("WHEEL")
    assert text is not None, f"No WHEEL metadata for {dist_name}"
    return _parse_tags(text)


def main() -> None:
    if len(sys.argv) < 4 or sys.argv[1] not in ("dist", "whl"):
        raise SystemExit("Usage: check_wheel.py (dist <pkg> | whl <path>) <expected_tag_substring>")
    mode, target, expected = sys.argv[1], sys.argv[2], sys.argv[3]
    tags = tags_from_dist(target) if mode == "dist" else tags_from_path(target)
    print(f"{mode} {target}: tags={tags}")
    assert any(expected in t for t in tags), (
        f"Expected tag containing {expected!r} for {target}, got {tags}"
    )


if __name__ == "__main__":
    main()
