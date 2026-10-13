#!/usr/bin/env python3
"""Apply the Beyond Compare 5 licence patch to a copy of the BCompare binary.

Replaces, at file offset 0xd87101, the instruction that loads the licence-state
byte from the licence object:

    mov 0x620(%rax),%al      (8a 80 20 06 00 00)
    ->
    mov $0x3,%al             (b0 03)  followed by four NOPs

The replacement is the same length, so nothing shifts and the file size is
unchanged. Function 00e870f0 returns this byte, and its three call sites use it as
the licence state (0 standard, 1 pro, 2 trial, 3 registered).

Usage:  apply.py <BCompare>            patch in place (writes .orig backup)
        apply.py <BCompare> --check    only report whether it is patched
"""
import sys
import shutil

OFFSET = 0xD87101
ORIGINAL = bytes.fromhex("8a8020060000")
PATCHED = bytes.fromhex("b003909090 90".replace(" ", ""))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    path = sys.argv[1]
    check_only = "--check" in sys.argv[2:]

    with open(path, "rb") as fh:
        data = bytearray(fh.read())

    if len(data) < OFFSET + 6:
        print(f"{path}: too short to be a BCompare binary")
        return 1

    have = bytes(data[OFFSET:OFFSET + 6])

    if check_only:
        if have == PATCHED:
            print(f"{path}: patched")
            return 0
        if have == ORIGINAL:
            print(f"{path}: unpatched")
            return 0
        print(f"{path}: neither patched nor original ({have.hex()})")
        return 3

    if have == PATCHED:
        print(f"{path}: already patched")
        return 0
    if have != ORIGINAL:
        print(f"{path}: unexpected bytes at 0x{OFFSET:x}: {have.hex()}")
        print("refusing to patch a binary this is not known to match")
        return 3

    shutil.copyfile(path, path + ".orig")
    data[OFFSET:OFFSET + 6] = PATCHED
    with open(path, "wb") as fh:
        fh.write(data)

    print(f"{path}: patched at 0x{OFFSET:x}; backup at {path}.orig")
    return 0


if __name__ == "__main__":
    sys.exit(main())
