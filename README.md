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
misplaced write — but it is not the null read first supposed either; see the test
below that ruled that out.

## Why it does not work, measured

The app was run two ways from a cleared config directory, under a real X server,
and compared. The original builds its window and writes its state files; the
patched build does neither, and it does not crash either — it stays alive and never
initialises.

```
                        original                patched
window                  "Home - Beyond Compare" none (only a Qt owner window)
                       1105x808
screenshot              88,715 bytes            353 bytes (blank)
exit after cap          124 (still running)     124 (still running)
~/.config/bcompare5/    IsPro, registry.dat,    directory is empty
                        BCState.xml, menu.ini
```

The patched build runs, stays running, and produces nothing: no window, no config
directory. It is not a crash, so the cause is not a fault in the patched
instruction itself.

### What actually happens, and why the patch cannot work

Two explanations were tested and discarded before the real one was found. The
measurements, from running each build under a real X server and reading its own
process state:

```
                        original                    patched
process state           S (sleeping)                R (running, burning CPU)
threads                 7                           2
open files (non-lib)    BCLOCK, BC_IPC_SERVER       none
~/.config/bcompare5/    IsPro, registry.dat,        directory is empty
                        BCState.xml, menu.ini
window                  "Home - Beyond Compare"     none
                        1105x808
```

**The state byte is not a flag that gets compared; it is set by the success path.**
An earlier note in this analysis said nothing writes 3 to `+0x620` and that was
wrong — a scan for `mov byte [reg+disp32], imm8` over `.text` finds the value 3
written at two places inside the licence code. The success path, at file offset
`0xd81755`, is:

```
d81738   mov BYTE PTR [rax+0x640],0x1     set window mode
d81743   call 0xd84f50                    read the key
d8174c   call 0xd87070                    invoke a registered callback
d81755   mov BYTE PTR [rax+0x620],0x3     only now the state becomes registered
d81760   mov BYTE PTR [rax+0x621],0x4     and a source tag is set
```

The state is written *after* the key has been read and a callback invoked — not
independently of them. `0xd87070` is a callback dispatcher: it tests a function
pointer at `+0x708` and calls it if non-null. The enclosing routine also consults
`+0x640` and `+0xa0` before reaching that path, and writes `+0x1b8`.

Forcing `+0x620` to 3 therefore does not reproduce a licensed object. It leaves the
object with the registered state while `+0x1b8`, `+0xa0` and `+0x640` still hold
their defaults, the callback never ran, and the key was never read. Start-up then
sees an inconsistent object and spins instead of initialising — which is exactly the
`R`/two-thread/no-I/O state measured above.

**So the patch is correct in address and wrong in approach: it fakes a result that
the program depends on having been computed.** A working change has to make the key
path run — have `0xd84f50` read a key the parser accepts — not set the state the
path would have set.

### Two explanations tested and discarded

**Null reads in the display branch.** The registered branch reads three pointers
out of the licence object (`+0x1c8`, `+0x100`, `+0xf8`) and the constructor zeroes
all of them, so the obvious explanation was null reads. Each reader was rewritten to
point at the `<unregistered>` string already in the image, as `lea rsi,[rip+disp32]`
in place of `mov rsi,[rax+disp]` — seven bytes for seven bytes, so nothing shifts:

```
00e84ec0   48 8b b0 c8 01 00 00  ->  48 8d 35 ...   ("Licensed to:" value)
00e871b0   48 8b b0 00 01 00 00  ->  48 8d 35 ...   ("License type:" value)
00e80a90   48 8b b0 f8 00 00 00  ->  48 8d 35 ...   (platform flags)
```

Result: unchanged. No window, empty config directory, same `R`/two-thread state.
Applying only the status-store patch reproduces it exactly, so the trigger is the
state patch itself and not those reads.

**A misplaced write.** The patch address was confirmed correct by scanning `.text`
for every `call rel32` resolving to it: fifteen call sites, three of them the branch
instructions named above. So the failure is not a wrong address.

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
misplaced write — but it is not the null read first supposed either; see the test
below that ruled that out.

## Why it does not work, measured

The app was run two ways from a cleared config directory, under a real X server,
and compared. The original builds its window and writes its state files; the
patched build does neither, and it does not crash either — it stays alive and never
initialises.

```
                        original                patched
window                  "Home - Beyond Compare" none (only a Qt owner window)
                       1105x808
screenshot              88,715 bytes            353 bytes (blank)
exit after cap          124 (still running)     124 (still running)
~/.config/bcompare5/    IsPro, registry.dat,    directory is empty
                        BCState.xml, menu.ini
```

The patched build runs, stays running, and produces nothing: no window, no config
directory. It is not a crash, so the cause is not a fault in the patched
instruction itself.

### What actually happens: the patched build spins

Two explanations were tested and both were wrong; the measurements below replaced
them. Running each build under a real X server and reading its own process state:

```
                        original                    patched
process state           S (sleeping)                R (running)
threads                 7                           2
open files (non-lib)    BCLOCK, BC_IPC_SERVER       none
~/.config/bcompare5/    IsPro, registry.dat,        directory is empty
                        BCState.xml, menu.ini
window                  "Home - Beyond Compare"     none
                        1105x808
```

The original parks in `S` with seven threads, having taken its lock and started its
IPC endpoint. The patched build sits in `R` with two threads, has opened nothing,
and writes nothing. That is not a crash and not a wait: it is a process burning CPU
before it has done any setup. (Measuring it further was cut short — the host ran out
of memory while the spinning process was alive, which is consistent with the build
looping rather than idling.)

### Two explanations tested and discarded

**Null reads in the display branch.** The registered branch reads three pointers
out of the licence object (`+0x1c8`, `+0x100`, `+0xf8`) and the constructor zeroes
all of them, so the obvious explanation was null reads. Each reader was rewritten to
point at the `<unregistered>` string already in the image, as `lea rsi,[rip+disp32]`
in place of `mov rsi,[rax+disp]` — seven bytes for seven bytes, so nothing shifts:

```
00e84ec0   48 8b b0 c8 01 00 00  ->  48 8d 35 ...   ("Licensed to:" value)
00e871b0   48 8b b0 00 01 00 00  ->  48 8d 35 ...   ("License type:" value)
00e80a90   48 8b b0 f8 00 00 00  ->  48 8d 35 ...   (platform flags)
```

Result: unchanged. No window, empty config directory, same `R`/two-thread state. So
the failure is not those reads.

**A misplaced write.** The patch address was confirmed to be the right one by
scanning `.text` for every `call rel32` resolving to it: fifteen call sites, three
of them the branch instructions named above. So the failure is not a wrong address
either.

**What the isolated test shows.** Applying only the status-store patch (without the
reader patches) reproduces the state exactly — `R`, two threads, empty config
directory. So the trigger is the state patch itself: the licence state byte is not
merely compared, it is *set* along the file-read path, and forcing it to its
registered value without that path having run leaves start-up in a state where it
spins instead of initialising. That is the current understanding, and it is where
the next step starts.

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
misplaced write — but it is not the null read first supposed either; see the test
below that ruled that out.

## Why it does not work, measured

The app was run two ways from a cleared config directory, under a real X server,
and compared. The original builds its window and writes its state files; the
patched build does neither, and it does not crash either — it stays alive and never
initialises.

```
                        original                patched
window                  "Home - Beyond Compare" none (only a Qt owner window)
                       1105x808
screenshot              88,715 bytes            353 bytes (blank)
exit after cap          124 (still running)     124 (still running)
~/.config/bcompare5/    IsPro, registry.dat,    directory is empty
                        BCState.xml, menu.ini
```

The patched build runs, stays running, and produces nothing: no window, no config
directory. It is not a crash, so the cause is not a fault in the patched
instruction itself.

### A first explanation, and the test that disproved it

The registered branch reads three pointers out of the licence object
(`+0x1c8`, `+0x100`, `+0xf8`) and the object's constructor zeroes all of them, so
the obvious explanation is that forcing the state sends the branch into null reads.
That was tested rather than assumed. Each of the three readers was rewritten to
point at the `<unregistered>` string that already exists in the image, as a
`lea rsi,[rip+disp32]` in place of `mov rsi,[rax+disp]` — seven bytes for seven
bytes, so nothing shifts:

```
00e84ec0   48 8b b0 c8 01 00 00  ->  48 8d 35 ...   ("Licensed to:" value)
00e871b0   48 8b b0 00 01 00 00  ->  48 8d 35 ...   ("License type:" value)
00e80a90   48 8b b0 f8 00 00 00  ->  48 8d 35 ...   (platform flags)
```

The result is unchanged: no window, empty config directory, same blank screenshot.
**That disproves the null-read explanation.** Whatever stops the app happens before
those readers are reached, so the failure is earlier in the licence path than the
branch that fills the display fields.

So the position is: the decision point is the right one, the patch is applied
exactly, and the app still does not reach the registered UI — but the reason is not
the one first supposed, and it is not yet known. What is known is that it is not a
null read of the three display fields, and not a misplaced write.

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
misplaced write — but it is not the null read first supposed either; see the test
below that ruled that out.

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

Supply the display fields. That was attempted — the three readers were redirected at
the `<unregistered>` string, seven bytes for seven bytes — and it changed nothing,
which is how the null-read explanation above was ruled out. So this is not the
remaining obstacle either.

The likely direction is earlier in the licence path: the state byte is not merely
compared, it is set by a load along the file-read path, and forcing it to its
registered value without that path having completed may leave the object in a state
the rest of start-up does not expect. Finding what actually stops the run means
tracing the start-up sequence rather than reading more of the licence functions.

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
