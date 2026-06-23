# websim Expansion Plan — Add the Remaining KORG Platforms

Status: **largely implemented (2026-06-23)** — §3 shared infra, NTS migration, Phase 1
(microKORG2 osc + fx templates), Phase 2 (drumlogue synth + fx), and Phase 3 (gen-1 osc on
nutekt-digital / minilogue xd / prologue) all build via `make websim PROJECT=...`.
Remaining: the NEON-heavy microKORG2 "real" units (vox, MorphEQ, MultitapDelay, Vibrato,
breveR) need extra SIMDe lane-path triage; browser audio-correctness spot-checks (§7) are
still manual. See "Supported platforms & caveats" in [WEBSIM.md](../../WEBSIM.md).
Owner: TBD
Last updated: 2026-06-23

This plan describes how to extend [websim](websim/) — currently limited to **NTS-1 mkII**
and **NTS-3 kaoss** — to cover every other logue-SDK platform in this repo:

| Phase | Platform(s) | SDK gen | Unit kinds | Difficulty |
|-------|-------------|---------|------------|------------|
| 1 | **microKORG2** | gen-2 (class) | osc, modfx, delfx, revfx | low–moderate |
| 2 | **drumlogue** | gen-2 (class) | synth, delfx, revfx, masterfx | moderate |
| 3 | **prologue / minilogue xd / NTS-1 mkI** (`nutekt-digital`) | gen-1 (C funcs) | osc, modfx, delfx, revfx | moderate (new harness) |

The phases are independent and can ship one at a time. Phase 1 is the recommended
starting point because it reuses the most existing machinery.

---

## 1. Background & the core constraint

websim does **not** emulate the hardware. The `make wasm` target bypasses the ARM
toolchain and recompiles the *DSP source* to WebAssembly with Emscripten, then drives it
from a Web Audio AudioWorklet. See [WEBSIM.md](WEBSIM.md) for the full description.

The single most important fact: the host bridge
[platform/nts-1_mkii/waves/wasm.cc](platform/nts-1_mkii/waves/wasm.cc) binds **directly to
the C++ processor class** (`Osc processor;` → `processor.init/process/setParameter/
noteOn/setPitch/getBufferSize`) and reads parameter metadata from `unit_header`. It never
calls the `unit_*` C callbacks. Therefore websim compatibility is governed by three things,
which every phase below must satisfy:

1. **The DSP source must compile under `emcc`** (no ARM-only headers that lack a wasm path).
2. **Each platform's firmware-ROM runtime API must exist as a host re-implementation**, the
   way [websim/dsp/osc_api.cpp](websim/dsp/osc_api.cpp) and
   [websim/dsp/fx_api.cpp](websim/dsp/fx_api.cpp) stand in for the NTS ROM today.
3. **A bridge + HTML shell must emulate that platform's runtime context** (mono vs. poly
   pitch, mono vs. stereo geometry, presets, tempo, …).

### Two SDK generations

- **gen-2 "unit" SDK** (`unit.cc` + `header.c` + `config.mk`, DSP in a C++ class):
  NTS-1 mkII, NTS-3 — **and microKORG2 and drumlogue**. websim was built for this shape, so
  Phases 1–2 *extend* the existing bridge.
- **gen-1 legacy SDK** (`OSC_INIT`/`OSC_CYCLE`/`OSC_PARAM` free functions over
  `user_osc_param_t`, q31 output, `project.mk` + linker scripts): prologue, minilogue xd,
  NTS-1 mkI. websim's class-binding bridge does not apply; Phase 3 needs a *new* harness.

---

## 2. Enabling libraries & helpers (research summary)

These remove the obstacles that originally looked hard. Sources are listed in §9.

| Obstacle | Helper | Notes |
|----------|--------|-------|
| ARM NEON intrinsics in DSP (drumlogue `vst1_f32`/`vdup_n_f32`; microKORG2 `float32x4_t`/`f32x4_*`) | **Emscripten's bundled SIMDe** via `-mfpu=neon -msimd128` | Compiles `arm_neon.h` unchanged. 128-bit "q" ops map to native wasm SIMD; 64-bit ops are scalarized (correct, just slower) — fine for a sim. No hand-written shim needed. |
| Coverage gaps / x86 SSE paths | **standalone [SIMDe](https://github.com/simd-everywhere/simde)** (header-only, MIT) | Fallback only if Emscripten's vendored snapshot is missing an intrinsic. |
| AudioWorklet plumbing | **Emscripten Wasm Audio Worklets** (`-sAUDIO_WORKLET -sWASM_WORKERS`) | Already used by websim; nothing new. |
| Stereo / block-size mismatch (drumlogue) | **WASM ring buffer** pattern (Google web-audio-samples; `wasm-ring-buffer`) | For N-channel interleave + 128-frame quanta. |
| C++↔JS controls | **Embind** (`-lembind`) | Already used; extend bindings per platform. |
| gen-1 reference | **[dukesrg/logue-osc](https://github.com/dukesrg/logue-osc)** | Community prior art running logue oscillators in the browser; reference for the legacy runtime API and q31 conventions. |

---

## 3. Shared infrastructure (do this first, once)

Today the `wasm:` recipe and its wasm-only variables are **duplicated inline** in each
supported project's `Makefile` (see
[platform/nts-1_mkii/waves/Makefile](platform/nts-1_mkii/waves/Makefile#L137-L266): the
`SANDBOXDIR` / `WASMSRC` / `WASMDIR` / `EMCC_BIN_PATH` block and the `wasm:` target). Adding
three platforms × several projects this way is unmaintainable.

**Task 3.1 — Extract a shared wasm fragment.** Create `websim/wasm.mk` containing the
`wasm:` target and its variables, parameterised by:
- `WEBSIM_SHELL` — `osc.html` | `fx.html` | `xypad.html`
- `WEBSIM_DSP` — the platform's ROM stand-in source glob (defaults to `websim/dsp/*`)
- `WEBSIM_EMCC_EXTRA` — extra flags (e.g. `-mfpu=neon -msimd128` for gen-2 SIMD platforms)
- `WEBSIM_WASMSRC` — bridge + unit sources

Each project then does `include $(SANDBOXDIR)/wasm.mk` instead of copy-pasting. Migrate the
existing NTS projects to it as the first, behaviour-preserving change (regression baseline).

**Task 3.2 — Make `websim/dsp/` layered.** Keep the current files as the NTS/`osc_api`/
`fx_api` baseline, add per-platform subdirs (`websim/dsp/microkorg2/`,
`websim/dsp/drumlogue/`, `websim/dsp/legacy/`) so platform ROM stand-ins don't collide.

**Task 3.3 — Root Makefile: keep `make websim` working for every platform.** The root
[Makefile](Makefile) is the single entry point (`make websim PROJECT=...`,
`make list`, `make clean PROJECT=...`) and it auto-discovers projects by grepping for a
literal `wasm:` target:

```make
# Makefile:25 (current)
WASM_PROJECTS := $(patsubst %/Makefile,%,$(shell grep -rl '^wasm:' platform/*/*/Makefile 2>/dev/null))
```

Three things must change/​be verified here, or the new instruments won't be callable:

- **3.3a — Discovery must survive the §3.1 refactor.** Once `wasm:` lives in an *included*
  `websim/wasm.mk` (and `websim/legacy.mk` for gen-1), project Makefiles no longer contain a
  literal `^wasm:` line, so the current grep returns nothing and **all** projects disappear
  from `make list`/`make websim`. Update discovery to match the include marker as well, e.g.:

  ```make
  WASM_PROJECTS := $(patsubst %/Makefile,%,$(shell \
      grep -rlE '^(wasm:|[[:space:]]*include .*websim/(wasm|legacy)\.mk)' \
      platform/*/*/Makefile 2>/dev/null))
  ```

  (Matching both forms keeps any not-yet-migrated project working during the transition.)

- **3.3b — The discovery glob already spans every platform.** `platform/*/*/Makefile` already
  covers `microkorg2/`, `drumlogue/`, `prologue/`, `minilogue-xd/`, `nutekt-digital/`, so new
  projects are picked up automatically the moment they include the fragment — **no per-
  platform edit to the root Makefile is required** beyond 3.3a. Verify gen-1 projects, which
  today use `project.mk` (not this `Makefile`/`config.mk`), still expose a `Makefile` that
  the glob can see; if a gen-1 project's entry point is `project.mk`, either add a thin
  `Makefile` that `include`s `websim/legacy.mk`, or widen the glob to
  `platform/*/*/{Makefile,project.mk}` and adjust `resolve_project` accordingly.

- **3.3c — One unified command, including gen-1.** gen-1 projects must be reachable through
  the **same** `make websim PROJECT=...` — *no* separate `make websim-legacy` target. They
  achieve this by exposing a discoverable `wasm:` via `websim/legacy.mk` (see §6). This keeps
  one mental model for users across all six platforms.

- **3.3d — Bare-name ambiguity is expected and already handled.** As platforms are added,
  bare names collide (`waves` exists on 5 platforms; `dummy-osc` on 3; `pluck` on 2). The
  existing `resolve_project` (Makefile:31-51) already rejects ambiguous names with the
  candidate list and asks for the full path — good. Just (i) keep the default
  `PROJECT ?= platform/nts-1_mkii/waves` fully-qualified, and (ii) update the `help` text and
  examples (Makefile:57-74) to show full paths for the new platforms, e.g.
  `make websim PROJECT=platform/microkorg2/waves`.

**Acceptance for §3:**
- `make websim PROJECT=waves` and `PROJECT=platform/nts-3_kaoss/pluck` behave exactly as
  before, now driven by the shared fragment.
- `make list` shows the NTS projects (and later every migrated/new project across all
  platforms) — nothing dropped by the discovery change.
- `make websim PROJECT=platform/<plat>/<proj>` and `make clean PROJECT=...` dispatch
  correctly to any platform that includes the fragment.

---

## 4. Phase 1 — microKORG2 (gen-2 oscillator first)

microKORG2 runs the same logue SDK 2.0 engine as the NTS-1 mk2, uses the class-based unit
model, and is **48 kHz** like websim. Reference unit:
[platform/microkorg2/waves](platform/microkorg2/waves).

### Differences vs. NTS-1 mkII that the bridge must handle

1. **Polyphonic osc context.** microKORG2's
   [`unit_runtime_osc_context_t`](platform/microkorg2/common/unit_osc.h#L70-L78) is
   `pitch[kMk2MaxVoices]`, `voiceLimit`, `outputStride` — not NTS's single `uint16_t pitch`.
   The `Process(out, frames)` loop iterates voices and writes with `outputStride` /
   `GetBufferOffset`. The bridge must construct and populate this context each block.
   **Decision (2026-06-23): v1 is single-voice** — set `voiceLimit = 1`, fill `pitch[0]`
   from the keyboard, `outputStride = 1`. This keeps the bridge and `osc.html` essentially
   the same as the NTS mono path; small polyphony is deferred to a later iteration.
2. **Class method names differ.** `Init` / `Process(out,frames)` (no `in` arg), plus
   `getParameterValue`, `getParameterBmpValue`, `LoadPreset`, `getPresetIndex`,
   `unit_platform_exclusive` — see [waves.h](platform/microkorg2/waves/waves.h). Needs a
   microKORG2-specific `wasm.cc`, not the NTS one.
3. **SIMD types** (`float32x4_t`, `f32x4_ld`, `float32x4_fmulscaladd`) appear in
   `common/utils/io_ops.h` and the platform-exclusive mod path. Compile with
   `-mfpu=neon -msimd128`. The mod path is not driven by the sim and can be stubbed.
4. **Extra runtime surface:** `waves.h` pulls in `<iostream>`, `macros.h`, and
   [`SystemPaths.h`](platform/microkorg2/common/SystemPaths.h) (device filesystem paths).
   Provide host stubs.
5. **microKORG2 runtime ROM API** — `osc_wave_scanf`, `osc_w0f_for_note`, `osc_bitresf`,
   `osc_white`, `osc_tanpif`, the `wavesA..F` tables, `dsp::ParallelBiQuad`. Some overlap
   with the existing NTS `osc_api.cpp`/`waves-*.c`; provide a `websim/dsp/microkorg2/`
   stand-in set (reuse NTS implementations where the symbols/semantics match).

### Tasks

- [ ] 4.1 Add `platform/microkorg2/waves/wasm.cc` (single-voice osc context: `voiceLimit=1`,
      keyboard note → `pitch[0]`, `outputStride=1`).
- [ ] 4.2 Create `websim/dsp/microkorg2/` ROM stand-ins (osc API, wavetables, biquad,
      `SystemPaths`/`<iostream>` stubs, no-op `unit_platform_exclusive`).
- [ ] 4.3 Add a `wasm:` include to [platform/microkorg2/waves/Makefile](platform/microkorg2/waves/Makefile)
      via the §3 fragment, with `WEBSIM_SHELL=osc.html`,
      `WEBSIM_EMCC_EXTRA=-mfpu=neon -msimd128`, `WEBSIM_DSP=websim/dsp/microkorg2/*`.
- [ ] 4.4 Get `make wasm` to compile; triage each missing symbol / ARM header into a stub.
- [ ] 4.5 Voice policy locked to single-voice for v1 (see Decision above). Note `waves`'
      inter-voice drift won't be audible with one voice — acceptable trade-off.
- [ ] 4.6 Reuse `osc.html` as-is (no poly UI needed for v1).
- [ ] 4.7 Repeat for `microkorg2/dummy-osc`, then the fx templates
      (`dummy-modfx`/`dummy-delfx`/`dummy-revfx` → `fx.html`), then `vox`, `MorphEQ`,
      `MultitapDelay`, `Vibrato`, `breveR`.
- [ ] 4.8 Confirm root-Makefile dispatch (§3.3): `make list` shows the microKORG2 projects and
      `make websim PROJECT=platform/microkorg2/waves` / `make clean PROJECT=...` work. Add a
      microKORG2 example to the root `help` text.

**Acceptance:** `make websim PROJECT=platform/microkorg2/waves` (the root-Makefile command)
opens Chrome, the keyboard sounds the oscillator, and all `unit_header` params render as
working sliders.

---

## 5. Phase 2 — drumlogue (gen-2, stereo, NEON, presets)

drumlogue uses the class model and 48 kHz, but is a Cortex-A7 platform with stereo output
and pervasive NEON. Reference:
[platform/drumlogue/dummy-synth](platform/drumlogue/dummy-synth).

### Differences the bridge must handle

1. **NEON in the render path** — every drumlogue unit (`synth.h`, `delay.h`, `reverb.h`,
   `masterfx.h`) includes `<arm_neon.h>` and uses intrinsics directly. Compile with
   `-mfpu=neon -msimd128` (SIMDe). `vst1_f32`/`vdup_n_f32` scalarize; acceptable for a sim.
2. **Stereo output.** [synth.h `Init`](platform/drumlogue/dummy-synth/synth.h#L33-L45)
   requires `output_channels == 2`; `Render` writes interleaved stereo. websim's `osc.html`
   path and `wasm.cc` assume mono — add a stereo output route (2-channel AudioWorklet node;
   optional ring buffer from §2).
3. **Synth note/gate model** — `NoteOn/NoteOff/GateOn/GateOff/AllNoteOff/PitchBend` (see
   [unit.cc](platform/drumlogue/dummy-synth/unit.cc#L77-L107)); map keyboard → these.
4. **Presets** — `LoadPreset/getPresetIndex/getPresetName`. Optionally surface a preset
   selector in the shell; otherwise default preset 0.
5. **Linux/posix runtime assumptions** (dynamic `.drmlgunit`, richer runtime). Stub any
   filesystem/runtime calls the units touch.

### Tasks

- [ ] 5.1 `platform/drumlogue/<unit>/wasm.cc` — stereo bridge, synth/gate note routing.
- [ ] 5.2 Stereo support in the shell: new `synth.html` (or extend `osc.html`) + 2-channel
      worklet node; integrate ring buffer if block sizes mismatch.
- [ ] 5.3 `websim/dsp/drumlogue/` ROM stand-ins + posix/runtime stubs.
- [ ] 5.4 Build `dummy-synth` with `-mfpu=neon -msimd128`; triage NEON/ABI errors.
- [ ] 5.5 Effects (`dummy-delfx`/`dummy-revfx` → `fx.html` stereo, `dummy-masterfx`).
- [ ] 5.6 Validate audio correctness vs. a known-good build (spot-check waveforms).
- [ ] 5.7 Confirm root-Makefile dispatch (§3.3): `make list` shows the drumlogue projects and
      `make websim PROJECT=platform/drumlogue/dummy-synth` works; add a drumlogue `help`
      example.

**Acceptance:** `make websim PROJECT=platform/drumlogue/dummy-synth` (the root command) plays
in stereo from the keyboard with working param sliders.

---

## 6. Phase 3 — prologue / minilogue xd / NTS-1 mkI (gen-1)

These share the legacy SDK and need a **separate harness** (the DSP is exposed as free C
functions, not a class) — but it is still driven by the **same** `make websim PROJECT=...`
root command via a discoverable `wasm:` target (§3.3c), not a separate launcher. Reference:
[platform/nutekt-digital/waves/waves.cpp](platform/nutekt-digital/waves/waves.cpp). Upside:
no NEON, plain fixed-point/float DSP that compiles cleanly under emcc, and a huge existing
catalogue of community oscillators becomes runnable once the harness exists.

### What the harness must provide

1. **A function-API bridge** (`websim/legacy/wasm_osc.cc`) that:
   - synthesizes a `user_osc_param_t` each block (pitch from keyboard, shape/shiftshape,
     LFO, the 6 user params),
   - calls `OSC_INIT` once, then `OSC_CYCLE` per 128-frame block, routing `OSC_NOTEON`/
     `OSC_NOTEOFF`/`OSC_PARAM`,
   - converts the q31 (`q31_t *yn`) output to float for Web Audio.
2. **Legacy runtime ROM stand-ins** (`websim/dsp/legacy/`) for the gen-1 osc API
   (`osc_sinf`, `osc_wave`, fixed-point LUTs, `q31_to_f32`, etc.) — analogous to the gen-2
   `osc_api.cpp`; cross-check against dukesrg/logue-osc.
3. **A gen-1 build path, reachable from the unified command.** gen-1 projects use
   `project.mk` (no `config.mk`, no `wasm:` target). Add a `websim/legacy.mk` that compiles
   `UCXXSRC`/`UCSRC` + the legacy bridge + legacy stand-ins with emcc **and defines a `wasm:`
   target** so the project is discovered by the root Makefile (§3.3) and runs via the same
   `make websim PROJECT=...` — **no separate `make websim-legacy` target** (decision per
   §3.3c). If a gen-1 project's only entry point is `project.mk`, add a thin `Makefile` that
   `include`s `websim/legacy.mk` so both the discovery glob and `make -C <dir> wasm` work.
4. **Param mapping.** Map the gen-1 `k_user_osc_param_*` ids to slider metadata (gen-1 lacks
   the rich `unit_header`; synthesize descriptors from the manifest or a small table).
5. **Effects** (`MODFX`/`DELFX`/`REVFX`) use distinct gen-1 entry points — second harness if
   effects are in scope; start with oscillators.

### Tasks

- [ ] 6.1 `websim/legacy/wasm_osc.cc` (function-API bridge, q31→float).
- [ ] 6.2 `websim/dsp/legacy/` osc ROM stand-ins.
- [ ] 6.3 `websim/legacy.mk` emcc build wired to `project.mk` variables, exposing a `wasm:`
      target (+ thin `Makefile` per gen-1 project if needed) so the root Makefile discovers it.
- [ ] 6.4 Param-descriptor synthesis for the osc shell.
- [ ] 6.5 Prove on `nutekt-digital/waves`, then `minilogue-xd/waves`, then `prologue/waves`.
- [ ] 6.6 Confirm root-Makefile dispatch (§3.3): these appear in `make list` and run via
      `make websim PROJECT=platform/nutekt-digital/waves`; verify the discovery glob sees the
      gen-1 entry point (widen to include `project.mk` if a project has no `Makefile`).
- [ ] 6.7 (Stretch) gen-1 effects harness + `fx.html`.

**Acceptance:** `make websim PROJECT=platform/nutekt-digital/waves` (the unified root command)
plays the oscillator from the keyboard with usable param sliders.

---

## 7. Cross-cutting validation

- **Toolchain:** `make setup` (emsdk) must be current enough to bundle SIMDe with NEON
  support; pin/note the minimum Emscripten version in [WEBSIM.md](WEBSIM.md).
- **Per project smoke test:** builds, page loads cross-origin-isolated under `emrun`, audio
  starts on gesture, every param slider maps to an audible/visible change, no console errors.
- **Audio correctness:** spot-check the wasm output against the hardware/native build for at
  least one unit per platform (oscilloscope/spectrum view already in the shells).
- **Regression:** the two existing NTS platforms keep working after the §3 refactor.
- **Root-Makefile dispatch:** after each phase, `make list` includes the new projects and
  `make websim PROJECT=platform/<plat>/<proj>` + `make clean PROJECT=...` resolve and run for
  every platform (gen-2 and gen-1) through the **single** unified command — no separate
  launcher. Bare-name collisions error cleanly with candidates (Makefile `resolve_project`).
- **Docs:** update [WEBSIM.md](WEBSIM.md) "Supported platforms" + the project table, the root
  [Makefile](Makefile) `help`/examples (Makefile:57-74) with new-platform paths, and add a
  per-platform caveats note (single-voice osc, stereo, gen-1 limitations).

---

## 8. Sequencing & rough effort

1. **§3 shared infra** — small, unblocks everything, do first.
2. **Phase 1 microKORG2 osc** — best ROI; mostly poly-context emulation + ROM stand-ins +
   SIMD flags. Then fan out to microKORG2 fx/other units.
3. **Phase 3 gen-1 harness** — medium one-time cost, then cheap per unit; unlocks the largest
   existing library; no SIMD risk.
4. **Phase 2 drumlogue** — moderate; gated on stereo shell + NEON compile triage; do once the
   shared infra and a second platform have shaken out the bridge abstractions.

Each phase is independently shippable; stop after any phase with a coherent result.

---

## 9. Open questions / risks

- ~~**microKORG2 poly UX:** single-voice vs. small polyphony for v1?~~ **Resolved
  (2026-06-23): single-voice for v1.** Small polyphony deferred.
- **SystemPaths / device runtime:** how much of microKORG2/drumlogue runtime touches the
  filesystem? Determines how many stubs are needed (likely small for osc, larger for units
  that load samples/presets).
- **NEON scalarization performance:** acceptable for a browser sim, but verify CPU-heavy
  units still run in real time in the worklet.
- **gen-1 param metadata:** gen-1 lacks `unit_header`; confirm a clean source for slider
  descriptors (manifest.json vs. hand table).
- **License/headers:** keep KORG BSD-3 headers intact on any copied/derived source.

## Sources

- Emscripten — Using SIMD with WebAssembly (NEON via SIMDe): https://emscripten.org/docs/porting/simd.html
- SIMDe: https://github.com/simd-everywhere/simde
- Emscripten — Wasm Audio Worklets API: https://emscripten.org/docs/api_reference/wasm_audio_worklets.html
- Web Audio Samples — WASM ring buffer: https://googlechromelabs.github.io/web-audio-samples/audio-worklet/design-pattern/wasm-ring-buffer/
- Embind: https://emscripten.org/docs/porting/connecting_cpp_and_javascript/index.html
- dukesrg/logue-osc (gen-1 browser prior art): https://github.com/dukesrg/logue-osc
- microKORG2 fw 2.0 = logue SDK 2.0: https://synthanatomy.com/2025/10/korg-microkorg-2-firmware-2-0-unlocks-the-logue-sdk-engine-better-looper-and-more.html
