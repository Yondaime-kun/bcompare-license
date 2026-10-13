# bcompare-license

Reverse engineering of the licence check in **Beyond Compare 5** (`BCompare`, by
Scooter Software), and a patch for it.

**The patch in this repository does not work.** It is kept because the analysis is
sound and the failure is informative, and because a repository that quietly drops
a broken patch is worse than one that says so. Details below, including the
measurement that disproved it.

## What was found

The binary is stripped Free Pascal with no application symbols, so the licence
code was found by string reference: load it, search the loaded image for the app's
own licence strings, and group the functions by which strings they touch. That
gives the path directly.

```
00e86a50   "--- BEGIN LICENSE KEY ---" / "--- END LICENSE KEY -----"
00e802a0   "BEGINLICENSEKEY" / "ENDLICENSEKEY"     second key format
00e80f10   decodes a key block into two 132-byte buffers
00e8a670   the base64 decoder
00f8a070   loads <config>/BC5Key.txt
00f8a120   checks the file, calls 00f8a100
00f8a100   calls 00e80ba0, then 00f8b7a0
00f89fa0   the entry point: tries the config dir, then /etc/, then a fallback
00f89d80   branches on the licence state to pick standard / pro / trial
00f8b350   branches on the licence state to fill "Licensed to:" etc.
00f8b7a0   branches on the licence state before pulling platform flags
00e870f0   the state read
00f8b340   applies the result to the UI
```

`00e870f0` is twenty bytes and does one thing:

```
d870f0:  55                   push  %rbp
d870f1:  48 89 e5             mov   %rsp,%rbp
d870f4:  48 8d 64 24 f0       lea   -0x10(%rsp),%rsp
d870f9:  48 89 7d f8          mov   %rdi,-0x8(%rbp)
d870fd:  48 8b 45 f8          mov   -0x8(%rbp),%rax
d87101:  8a 80 20 06 00 00    mov   0x620(%rax),%al
d87107:  88 45 f4             mov   %al,-0xc(%rbp)
d8710a:  8a 45 f4             mov   -0xc(%rbp),%al
d8710d:  48 89 ec             mov   %rbp,%rsp
```

Three call sites read it and agree on the encoding: `00f89d80` branches on 0/1/2
for standard/pro/trial, `00f8b350` branches on 3 for registered and otherwise
writes the string `<unregistered>`, and `00f8b7a0` branches on 3.

## The patch

Replace the field load with a constant, same length, so nothing shifts:

```
before:  8a 80 20 06 00 00     mov   0x620(%rax),%al
after:   b0 03 90 90 90 90     mov   $0x3,%al ; nop nop nop nop
```

Six bytes at file offset `0xd87101`. `cmp -l` reports exactly six bytes:

```
14184706 212 260     0x8a -> 0xb0
14184707 200   3     0x80 -> 0x03
14184708  40 220     0x20 -> 0x90
14184709   6 220     0x06 -> 0x90
14184710   0 220     0x00 -> 0x90
14184711   0 220     0x00 -> 0x90
```

For **5.2.6.32774** (from `bcompare-5.2.6.32774_amd64.deb`; the `BCompare` inside
is 44,888,265 bytes). SHA256 before
`11e18e44332e213e404abf1d49ea869a5edb93df5783d9b1487bbbc2b6a9f567`, after
`91f2708ef830ab8441af5a4eaf07419121053be00d8f94ba0445b3a90be286bc`.

## Address mapping, confirmed

The binary has four `PT_LOAD` segments and, for the executable one,
`vaddr == offset` (`0xcb8000` for both), so the file offset of any address is the
address itself. The analysis tool used here loads images with a `0x100000`
rebase, so a tool address of `0x00e870f0` is VM address `0xd870f0`, which is file
offset `0xd870f0`.

That was checked rather than assumed, by scanning `.text` for every `call rel32`
whose target resolves to `0xd870f0`. Fifteen call sites:

```
0xe89dd5  the standard/pro/trial branch
0xe8a51a
0xe8acf6
0xe8ad9e
0xe8b3c0  the "== 3" branch that fills "Licensed to:"
0xe8b7d9  the second "== 3" branch
0xe8b803
0xec2f84
0xee0244
0xf1b29a
0xf43915
0x1018474
0x1018523
0x1019caa
0x1019d34
```

Three of them are the sites named above, at exactly those offsets once the rebase
is undone. No `lea` takes its address, so it is only ever called. Because the patch
is inside the function rather than at a call site, one six-byte change covers all
fifteen callers.

So the patch is applied to the right place. The app's failure under it is not a
misplaced write; it is the null read described above.

## Why it does not work, measured

The app was run two ways from a cleared config directory, under a real X server,
and compared. The original builds its window and its state files; the patched
build does neither.

```
                        original                patched
window                  "Home - Beyond Compare" none (only a Qt owner window)
                       1105x808
screenshot              88,715 bytes            353 bytes (blank)
~/.config/bcompare5/    IsPro, registry.dat,    directory is empty
                        BCState.xml, menu.ini
```

So forcing the state to "registered" does not produce a registered app — it
produces an app that never reaches its own UI. The registered branch does not
merely set a flag: `00f8b350` fills the display fields by reading them out of the
licence object (`00e84ec0` for the name, `00e871b0` for the type, `00e80a90` for
the platform flags). With no key loaded, those reads have nothing to work from,
and the run ends before the window is mapped.

**The lesson is the patch principle, not the offset:** forcing a decision point
without satisfying the data that branch consumes breaks the program. The trial and
standard branches synthesise their fields; the registered branch reads them.

## What would be needed

Either a key that the parser accepts, so `+0x620` reaches 3 on its own, or a patch
that also supplies the fields the registered branch reads.

The second is more work than a byte swap, and the constructor shows why. The object
that holds the licence state initialises all four display fields to zero:

```c
FUN_00e7cb10:                      /* object constructor */
    *(undefined8 *)(obj + 0x1c8) = 0;   /* "Licensed to:" value  */
    *(undefined8 *)(obj + 0x100) = 0;   /* "License type:" value */
    *(undefined8 *)(obj + 0xf8)  = 0;   /* platform flags        */
    *(undefined8 *)(obj + 0xf0)  = 0;   /* string searched for \n */
```

Nothing else in the binary writes them along any path reachable without an accepted
key, so the registered branch has three nulls to dereference. Supplying the fields
means either reconstructing them the way a valid key would, or redirecting the
readers (`00e84ec0`, `00e871b0`, `00e80a90`) at strings that already exist in the
image. The second is a code patch rather than a byte swap and was not attempted.

To test that, the fields are worth identifying first: `00e84ec0`, `00e871b0` and
`00e80a90` are the readers, and `DAT_02ce1320` / `DAT_02ce1370` / `DAT_02ce1360`
are where their results land for the UI.

## Usage (of the patch, for the analysis)

```sh
python3 apply.py /path/to/BCompare            # patch, writes .orig backup
python3 apply.py /path/to/BCompare --check    # report patched / unpatched / neither
```

It refuses a binary whose bytes at the offset are neither the original nor the
patched pattern, so it will not corrupt a different build. Exit codes: 0 patched
or unpatched, 3 unrecognised.

Only run this against a copy you own and are entitled to modify.

## What did work

- The app runs on a headless Linux host: Qt6 6.4.2, the xcb platform plugin, ICU
  74 and the supporting libraries were assembled for it, and `BCompare` starts and
  builds its main window under an X server.
- The licence path, the two key formats, the runtime-built base64 alphabet, and
  the 4-byte-wise byte reversal in the block parser are all read and documented.

## Files

- `apply.py` — the patcher, with `--check`
- `patch.txt` — the six byte changes as text
- `RE-NOTES.md` — full notes: the licence path, the key format, the misreadings
  along the way, and the measurements above
- `evidence/run-original.log`, `evidence/run-patched.log` — the two runs compared
  in the table above: window tree, screenshot size, config files produced
