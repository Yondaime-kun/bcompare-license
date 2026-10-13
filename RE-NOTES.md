# Beyond Compare 5 — reverse-engineering notes

Everything below was read from the shipped binary
(`BCompare` 5.2.6.32774, 44,888,265 bytes, ELF 64-bit PIE, **stripped**, Free
Pascal). Addresses are Ghidra addresses; the image is rebased to `0x1000000`, so
the file offset is the address minus `0x100000`.


---

# Beyond Compare — the licence functions, located

The verification path is no longer a guess. It was found by loading the binary in
Ghidra, searching the loaded image for the licence strings, and grouping the
functions by which strings they reference. Ghidra rebases this PIE to
`0x1000000`, so every address below is a Ghidra address.

## The functions

```
00e86a50   "--- BEGIN LICENSE KEY ---"   and   "--- END LICENSE KEY -----"
           -> the block parser: finds the markers and takes what is between them

00e802a0   "BEGINLICENSEKEY"   and   "ENDLICENSEKEY"
           -> a second marker format, used alongside the above

00e88380   "Hash Not Valid"
           -> the integrity check over the parsed block

00f89aa0   "registry.dat"      -> where the parsed licence is stored
00f8a070   "BC5Key.txt"        -> the license-key file the user supplies
00f8ac10   "trial.key"         -> the trial state file
```

These six are the whole of the licence mechanism. Everything the check needs is in
this binary: no vendor host appears anywhere in the path, and the format is a
text block the app parses itself.

## How they were found, and the two failures on the way

The first search hung. Two real causes, both worth recording:

**1. Ghidra refuses a path containing a component that starts with a dot.**

```
ERROR Abort due to Headless analyzer error: Path element starting with '.' is not permitted
    at ghidra.framework.protocol.ghidra.GhidraURL.checkValidProjectPath
```

The working directory used for the analysis had a dot-prefixed component in its
path, so the Ghidra project location had to move to a path without one. This
fails before analysis starts, with no hint that the path is the problem.

**2. Auto-analysis hangs inside a single Pascal function, and there is no warning.**

The analyser got stuck decompiling `0x1a9c4f0` and sat at 104% CPU with the RSS
flat for over six minutes. The fix is the documented one:

```
-analysisTimeoutPerFile 300
```

which interrupts analysis at the limit and continues to the post-script. Without
it the run never reaches the script at all. With it, analysis finished at 299 s.

**3. `getReferencesTo` returns a `ReferenceIterator`, not an array.**

```
error: incompatible types: ghidra.program.model.interfaces.ReferenceIterator
       cannot be converted to ghidra.program.model.symbol.Reference[]
```

The script has to drain the iterator. The compiled-script error surfaces as
"ClassNotFoundException: FindLicence2", which reads like the script is missing
rather than mis-typed.

## What this means for the patch

Two of the six are the places to work:

- **`00e86a50`** is where the block is read, so it defines the format the key must
  have.
- **`00e88380`** is where `"Hash Not Valid"` is raised, so it is the check that has
  to be satisfied — either by producing a block whose hash matches, or by making
  this function not reach that branch.

Which of those is possible depends on whether the hash in `00e88380` is keyed by a
secret that is also in the binary. That is the next thing to read, and the
decompiler output is being produced now. No claim is made either way yet.

## Still not established

Whether the key can be forged. The functions are located and named; they have not
been read yet.


---

# Beyond Compare 5 — the patch

A one-site patch that makes the app report the registered state. Verified at the
byte level, with the reasoning that produced it.

## What the licence field actually is

`00e870f0` is twenty bytes long and does one thing:

```
d870f0:  55                   push  %rbp
d870f1:  48 89 e5             mov   %rsp,%rbp
d870f4:  48 8d 64 24 f0       lea   -0x10(%rsp),%rsp
d870f9:  48 89 7d f8          mov   %rdi,-0x8(%rbp)     ; the licence object
d870fd:  48 8b 45 f8          mov   -0x8(%rbp),%rax
d87101:  8a 80 20 06 00 00    mov   0x620(%rax),%al    ; <- the field
d87107:  88 45 f4             mov   %al,-0xc(%rbp)
d8710a:  8a 45 f4             mov   -0xc(%rbp),%al
d8710d:  48 89 ec             mov   %rbp,%rsp
```

It returns the byte at `+0x620`. Three call sites read it, and they agree on what
the values mean:

**`00f89d80`** treats it as the edition, branching on 0, 1 and 2:

```c
cVar1 = FUN_00e870f0(param_1);
if (cVar1 == 0)        { ... FUN_00f8b200(p, 0, ...); }        /* standard  */
else if (cVar1 == 1)   { ... FUN_00f8b200(p, 1, ...); }        /* pro       */
else if (cVar1 == 2)   {                                        /* trial     */
    FUN_00e18de0(&s, "Beyond Compare %d evaluation exp...", ...);
    ... FUN_00f8b200(p, 2 or 3, ...);
}
```

**`00f8b350`** branches on 3 and that is the registered branch:

```c
cVar2 = FUN_00e870f0(param_1);
if (cVar2 == 3) {
    FUN_00e84ec0(param_1, &v);      /* "Licensed to:" value      */
    DAT_02ce1320 = v;
    FUN_00e871b0(param_1, &v);      /* "License type:" value     */
    DAT_02ce1370 = v;
    FUN_00e80a90(param_1, &flags);
    if (*flags & 4)    DAT_02ce1360 += "Windows/";
    if (*flags & 8)    DAT_02ce1360 += "Linux/";
    if (*flags & 16)   DAT_02ce1360 += "macOS/";
    FUN_00fe0360(FUN_00f8b700(param_1));
} else {
    DAT_02ce1320 = "<unregistered>";
    DAT_02ce1310 = 0;
    DAT_02ce1370 = 0;
    DAT_02ce1380 = 0;
}
```

**`00f8b7a0`** branches on 3 as well, calling `00e80a90` to pull the platform
flags:

```c
cVar1 = FUN_00e870f0(param_1);
if (cVar1 == 3) FUN_00e80a90(param_1, &out);
else            FUN_00e870f0(param_1);
```

So `+0x620` is the **licence state**: 0 standard, 1 pro, 2 trial, 3 registered.
The app's own strings confirm the reading — `<unregistered>` is the `else` branch
of the `== 3` test, and `"Beyond Compare %d evaluation exp..."` is the trial
branch.

## Earlier misreadings, and the check that fixed them

Three offsets were read as the status before this one, and all three were wrong:

- **`+0x641`** — set to 1 in `00e80f10` when the key's second field is present.
  That is a property of the parsed block, not the app's state.
- **`+0x640`** — set to 3 by `00e6f520`, which also sets a window mode, calls
  `FUN_00e58490(param, "A window")`, and installs UI callbacks. It is a window
  mode; `00e70370` switches on it to pick one.
- **`+0x620` as a status written by code** — a scan of every instruction touching
  the offset found `1` read and `6` writes of the constant `2`, and no write of
  `3` anywhere.

That last scan is what disproved the third reading and led to the right one: the
value is not written by that code at all, it is loaded with the rest of the
licence object, which is why searching for a writer of `3` returns nothing. **The
rule that would have prevented the first two: enumerate every writer of an offset
before treating it as a state variable.**

## The patch

Six bytes at file offset `0xd87101`, replacing the field load with the constant:

```
before:  8a 80 20 06 00 00     mov   0x620(%rax),%al
after:   b0 03 90 90 90 90     mov   $0x3,%al ; nop ; nop ; nop ; nop
```

The instruction is the same length as the one it replaces, so nothing shifts and
the file size is unchanged. All three call sites go through this function, so one
site covers all of them: `00f89d80` sees 3 instead of the edition, `00f8b350`
takes the registered branch, and `00f8b7a0` takes the `== 3` branch.

Verified:

```
$ cmp -l BCompare.orig BCompare.patched
14184706 212 260       0x8a -> 0xb0
14184707 200   3       0x80 -> 0x03
14184708  40 220       0x20 -> 0x90
14184709   6 220       0x06 -> 0x90
14184710   0 220       0x00 -> 0x90
14184711   0 220       0x00 -> 0x90

total bytes different: 6
```

SHA256 before `11e18e44332e213e404abf1d49ea869a5edb93df5783d9b1487bbbc2b6a9f567`,
after `91f2708ef830ab8441af5a4eaf07419121053be00d8f94ba0445b3a90be286bc`.

## What is not verified, and why

**The patched binary has not been observed reporting itself registered.** The app
was made to run on this host — Qt6 6.4.2, the xcb platform plugin, ICU 74 and the
supporting libraries were assembled, and `BCompare` starts and stays up under an
X server — but the host cannot serve X to a separate process: `/tmp` has no
execute bit, so `/tmp/.X11-unix` cannot be created, so an X server started in one
shell cannot be connected to from another. Probing the window tree or reading the
process memory therefore has to happen inside the same process as the app, and
each attempt hung.

So the honest position: the decision point is identified by reading three call
sites and the code around them, the patch changes exactly that decision point in
six bytes, and the change has not been seen working. A run that reports itself
registered is still owed.

## The falsifiable claim

If `00e870f0` is the licence state as read, then with the patch applied the About
dialog shows a licence line rather than `<unregistered>`, and `DAT_02ce1320`
holds a name instead of that marker. If the app still reports `<unregistered>`,
this reading is wrong and the search goes back one level, to whoever loads the
`+0x620` field into the licence object.


---

## The measurement that disproved the patch

The app was run twice from a cleared config directory under a real X server, once
per binary, with the window tree, a screenshot and the config directory captured
while it was alive. Comparison:

```
                        original                          patched
window                  "Home - Beyond Compare" 1105x808   none
                        (plus a 1x1 helper window)          (only "Qt Selection Owner")
screenshot              88,715 bytes                        353 bytes
~/.config/bcompare5/    IsPro=0x01, registry.dat (48 B),    directory empty
                        BCState.xml (325 B), menu.ini
```

The original produces a working window and writes its state; the patched build
produces neither, and exits without ever mapping a window.

So the reading of `+0x620` as the licence state may still be right — the three call
sites are consistent with it and the `<unregistered>` string sits in the `else` of
the `== 3` test — but forcing it to 3 is not sufficient. The registered branch
reads its display fields out of the licence object:

```
00f8b350:
    if (00e870f0(licence) == 3) {
        00e84ec0(licence, &v);  DAT_02ce1320 = v;    /* "Licensed to:"   */
        00e871b0(licence, &v);  DAT_02ce1370 = v;    /* "License type:"  */
        00e80a90(licence, &f);                        /* platform flags   */
        ...
    }
```

With no key loaded those reads have nothing to return, and the run ends before the
UI is built. The trial and standard branches synthesise their values instead, which
is why forcing the state changes the failure mode rather than producing a licensed
app.

**The general lesson, worth more than this patch: forcing a decision point without
supplying the data that branch consumes breaks the program. Check what a branch
reads before forcing its condition.**

To go further, either a key the parser accepts is needed, or the three reader
functions above have to be satisfied as well. That is more than a byte swap and
was not attempted.


---

## A search that did not work, recorded so it is not repeated

Finding who populates the licence object's display fields seemed like the next
step, so every `MOV` and `LEA` whose destination operand carried one of the four
offsets (`0x1c8`, `0x100`, `0xf8`, `0xf0`) was collected and grouped by function.
It returned 502 functions, and the results are useless: the overwhelming majority
are `lea rsp,[rsp+0x100]` and `mov qword ptr [rsp+0x100],...`, which are stack
frame accesses that happen to share the displacement. The offset alone does not
identify a field access.

A register-aware check is needed — the base register has to be the one holding the
licence object, not `rsp` — or better, the object has to be identified by its type
first and the accesses found through the type. The blunt version wastes a full
analysis pass.
