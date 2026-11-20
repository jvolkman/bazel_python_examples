"""Verify that both sdist-only C extensions compiled and work."""

import crcmod
import crcmod._crcfunext
import datrie


def main() -> None:
    assert crcmod._crcfunext.__file__.endswith(".so"), crcmod._crcfunext.__file__
    crc32c = crcmod.predefined.mkPredefinedCrcFun("crc-32c")
    checksum = crc32c(b"123456789")
    assert checksum == 0xE3069283, f"unexpected crc32c: {checksum:#x}"

    assert datrie.__file__.endswith(".so"), datrie.__file__
    trie = datrie.Trie("abcdefghijklmnopqrstuvwxyz")
    trie["bazel"] = 1
    trie["build"] = 2
    assert trie["bazel"] == 1
    assert trie.keys("ba") == ["bazel"]

    print(f"crcmod={crcmod._crcfunext.__file__}")
    print(f"datrie={datrie.__file__}")


if __name__ == "__main__":
    main()
