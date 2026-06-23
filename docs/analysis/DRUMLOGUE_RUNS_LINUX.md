# Does the drumlogue run Linux?

**Yes.** The drumlogue runs an embedded **Linux** userspace on an ARMv7-A
(Cortex-A7) SoC. User units are Linux ELF shared objects (`.drmlgunit`) that the
audio engine loads dynamically at runtime. The evidence is entirely contained in
this SDK.

## The decisive signal: the cross-compiler triple

[docker/docker-app/drumlogue/environment](../../docker/docker-app/drumlogue/environment#L59) sets:

```sh
export BUILD_TARGET_TRIPLE=arm-unknown-linux-gnueabihf
export CROSS_COMPILE=${BUILD_TARGET_TRIPLE}-
```

The `-linux-gnueabihf` component means units are compiled for **Linux userspace**
with glibc and the ARM hard-float EABI. Every *other* bare-metal logue platform
uses an `arm-none-eabi` (no-OS) toolchain instead:

| Platform | Toolchain | OS |
|---|---|---|
| prologue, minilogue xd, NTS-1, NTS-1 mkII, NTS-3 | `arm-none-eabi` | bare metal (Cortex-M) |
| **drumlogue** | **`arm-unknown-linux-gnueabihf`** | **Linux** |
| microKORG2 | `arm-unknown-linux-gnueabihf` | Linux (same as drumlogue) |

## Corroborating evidence

**1. Application-class CPU, not a microcontroller.**
[platform/drumlogue/dummy-delfx/Makefile](../../platform/drumlogue/dummy-delfx/Makefile) targets:

```
-march=armv7-a -mtune=cortex-a7
```

Cortex-**A**7 is an application processor with an MMU — the class of core that
runs a full OS. The bare-metal logue boards use Cortex-**M** microcontrollers.

**2. Units are Linux shared objects, dynamically loaded.**
The link step uses `-shared -fPIC … -lm -lc`, producing an ELF shared library
(the `.drmlgunit` file is effectively a `.so`). There is no linker script and
units link against the C library. The platform README confirms the host loads
them from a filesystem:

> *.drmlgunit* files can be loaded … by powering it up in USB mass storage device
> mode, and placing the files into the appropriate directory under *Units/* …
> loaded in alphabetical order upon restarting.

A filesystem with directories, and a host process that `dlopen`s plugins at
runtime. The `__unit_callback` entry points (`unit_init`, `unit_render`, etc.)
are the exported symbols the Linux host resolves.

**3. POSIX/Linux file-ownership semantics in the build.**
The Makefile's `POST_MAKE_ALL_RULE_HOOK` chowns build outputs back to the user
with `stat -c %u` / `stat -c %g`.

## Note on `wasm.cc`

[platform/drumlogue/dummy-delfx/wasm.cc](../../platform/drumlogue/dummy-delfx/wasm.cc)
is unrelated to the device runtime. It is a small shim for the **websim** browser
simulator (compiled to WebAssembly via emscripten, per the websim block at the
bottom of the Makefile), wrapping the `Delay` class in the websim host bridge so
the same DSP can run in a browser.

## Bottom line

The drumlogue runs **embedded Linux** on an ARMv7-A (Cortex-A7) SoC. User units
are Linux `.so` shared libraries (`.drmlgunit`) loaded dynamically by the audio
engine — confirmed by the `arm-unknown-linux-gnueabihf` toolchain, the
`-shared -fPIC -lm -lc` link, the Cortex-A target, and the filesystem-based USB
mass-storage unit loading. It is one of only two logue platforms (with the
microKORG2) that is Linux-based rather than bare-metal.
