# bcompare-license

A patch for the licence check in **Beyond Compare 5** (`BCompare`, by Scooter
Software). Six bytes, verified against the shipped binary.

The licence state is one byte in the licence object, returned by a twenty-byte
function. Every part of the app that asks "is this copy registered" asks that
function. The patch makes it answer "registered" without changing anything else.

## What it does

`00e870f0` reads a single byte and returns it:

```
d87101:  8a 80 20 06 00 00    mov   0x620(%rax),%al
```

The patch replaces that instruction with a constant, same length, so nothing
shifts:

```
d87101:  b0 03                mov   $0x3,%al
d87103:  90 90 90 90          nop nop nop nop
```

Three sites call that function and they agree on the encoding:

- `00f89d80` branches on 0, 1, 2 for standard / pro / trial
- `00f8b350` branches on 3 for registered, and its other branch sets the string
  `<unregistered>`
- `00f8b7a0` branches on 3 and then pulls the platform flags

Because the patch is inside the function, all three sites see 3.

## Usage

```sh
python3 apply.py /path/to/BCompare
```

Writes `BCompare.orig` next to the file as a backup, then patches in place. It
refuses to touch a binary whose bytes at that offset are neither the original nor
the patched pattern, so it will not corrupt a different build.

```sh
python3 apply.py /path/to/BCompare --check
```

Reports `patched`, `unpatched`, or `neither` and exits 0, 0, or 3.

Only a copy you own and are entitled to modify should be patched.

## Which build

Verified against **5.2.6.32774**, from
`bcompare-5.2.6.32774_amd64.deb` (25,235,566 bytes; the `BCompare` inside is
44,888,265 bytes, ELF 64-bit PIE, stripped).

SHA256 of the unpatched binary:

```
11e18e44332e213e404abf1d49ea869a5edb93df5783d9b1487bbbc2b6a9f567
```

after patching:

```
91f2708ef830ab8441af5a4eaf07419121053be00d8f94ba0445b3a90be286bc
```

`cmp -l` between the two reports exactly six bytes:

```
14184706 212 260     0x8a -> 0xb0
14184707 200   3     0x80 -> 0x03
14184708  40 220     0x20 -> 0x90
14184709   6 220     0x06 -> 0x90
14184710   0 220     0x00 -> 0x90
14184711   0 220     0x00 -> 0x90
```

On a different build the offsets move. Run `--check` first; it tells you which
category the bytes fall into before writing anything.

## How the site was found

The binary is stripped Free Pascal with no application symbols, so the licence
code was found by string reference rather than by name. Loading it in Ghidra,
searching the loaded image for the app's own licence strings, and grouping the
functions by which strings they reference gives the path directly:

```
00e86a50   "--- BEGIN LICENSE KEY ---" / "--- END LICENSE KEY -----"
00e802a0   "BEGINLICENSEKEY" / "ENDLICENSEKEY"
00e80f10   decodes a key block into two 132-byte buffers
00e8a670   the base64 decoder
00f8a070   loads <config>/BC5Key.txt
00f8a120   verifies the file, calls 00f8a100
00f8a100   calls 00e80ba0, then 00f8b7a0
00f8b7a0   tests the licence state
00e870f0   the state read
00f89d80   branches on the state to pick standard / pro / trial
00f8b350   branches on the state to fill in "Licensed to:" etc.
```

Full notes on the mechanism, the key block format, and the misreadings along the
way are in `RE-NOTES.md`.

## Not verified

**The patched binary has not been observed reporting itself registered.** The
app runs on the machine this was developed on — Qt6 6.4.2, the xcb platform
plugin, ICU 74 and the supporting libraries were assembled for it — but that
machine cannot serve X to a second process (`/tmp` has no execute bit, so
`/tmp/.X11-unix` cannot be created), and every attempt to inspect the running app
from outside its own process hung.

So: the decision point is established by reading three call sites, the patch
changes exactly that point, the change is exact at the byte level, and a run that
reports itself registered is still owed. The claim to test is in `RE-NOTES.md`:
with the patch applied the About dialog should show a licence line rather than
`<unregistered>`.
