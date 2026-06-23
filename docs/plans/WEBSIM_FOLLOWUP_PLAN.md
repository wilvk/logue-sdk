# websim Follow-up Plan — Remaining Work After the Platform Expansion

Status: **proposal / not started**
Last updated: 2026-06-23
Predecessor: [WEBSIM_EXPANSION_PLAN.md](WEBSIM_EXPANSION_PLAN.md) (implemented — all six
platforms build templates/reference units via `make websim PROJECT=...`).

This plan covers what the expansion deliberately left out. The biggest item (A) is the
NEON-heavy microKORG2 "real" units; the rest are breadth (more units, effects), correctness
validation, and polish.

---

## A. microKORG2 NEON "real" units — the core remaining work

Units: [`vox`](../../platform/microkorg2/vox) (osc),
[`MorphEQ`](../../platform/microkorg2/MorphEQ) (modfx),
[`MultitapDelay`](../../platform/microkorg2/MultitapDelay) (delfx),
[`Vibrato`](../../platform/microkorg2/Vibrato) (modfx),
[`breveR`](../../platform/microkorg2/breveR) (revfx).

The bridges already exist ([mk2_osc_bridge.h](../../websim/dsp/microkorg2/mk2_osc_bridge.h),
[mk2_fx_bridge.h](../../websim/dsp/microkorg2/mk2_fx_bridge.h)) and the templates build, so the
*only* blocker is compiling these units' DSP under emcc/clang. There are **two distinct failure
modes**, both rooted in KORG's `common/utils/{int_simd,float_simd,fixed_simd}.h`:

### A.1 The diagnosis (measured 2026-06-23)

KORG's SIMD headers have two code paths, gated on `__ARM_NEON`:
- **non-NEON (`#else`)** — portable structs `struct float32x4_t { float val[4]; }` with `.val[]`
  access. websim uses this today (the expansion fixed its trivial bugs).
- **NEON (`#if`)** — `#include <arm_neon.h>` and native vector types + intrinsics.

Neither is clean under emcc:

1. **`vox`** uses NEON intrinsics *directly* in its DSP (`vrecpeq_f32`, `vbslq_s32`,
   `veorq_s32`, …). Under the non-NEON build these are undeclared (5 errors). It needs the
   NEON/SIMDe path.

2. **`MultitapDelay` / `Vibrato` / `breveR`** pull in `<arm_neon.h>` (SIMDe, from
   `emsdk/.../sysroot/include/compat/arm_neon.h`) *while* KORG's `float_simd.h` non-NEON path
   also defines `float32x2_t` as a struct → **typedef redefinition** (`simde_float32x2_t` vs
   `struct float32x2`). They need both sides to agree on the type.

3. **`MorphEQ`** is the worst: it accesses `.val[...]` on `float32x2_t` (the struct shape) *and*
   pulls SIMDe vectors → `member reference base type 'float32x2_t' is not a structure`
   (~1450 cascading errors). It wants the struct representation but also drags in SIMDe.

4. If we instead force the **NEON/SIMDe path** globally (`-D__ARM_NEON -D__ARM_FP -msimd128`),
   `arm_neon.h` resolves via SIMDe (verified working), but a bounded set of KORG NEON-path
   helpers pass a **runtime** argument to a `_n_` *immediate* intrinsic, which clang rejects
   ("`n` must be constant"): e.g. `uint32x{2,4}_shlscal` → `vshl_n_u32(a, b)`,
   the `*_shrscal` shifts, `si_i32x{2,4}qn_to_f32x{2,4}` → `vcvtq_n_f32_s32(x, qPoint)` and the
   inverse, plus the lane `get`/`set` helpers (`vget/vset_lane` with runtime index) at
   `int_simd.h:~915-1000` and `float_simd.h:~1346-1366`. GCC-on-ARM tolerates these because
   `always_inline` + `optimize("Ofast")` constant-folds `b` at each call site; clang enforces
   the immediate at the function-body level, before inlining. There are also raw ARM
   `asm volatile("vld1.32 …")` x2x2 load/store macros (`int_simd.h:490-547`) that SIMDe cannot
   help with — these break only if a unit expands them.

### A.2 Recommended approach — a websim mk2 SIMD compatibility header

Provide `websim/dsp/microkorg2/mk2_simd_compat.h`, force-included ahead of KORG's headers
(emcc `-include`), that makes **one** consistent representation for the wasm build:

- Keep the **struct** representation (`.val[]`) so KORG's `.val[]`-using code (MorphEQ) and the
  scalar `#else` bodies work, **and prevent `<arm_neon.h>` from also defining the types**.
  Options to stop the collision (pick by testing): define `__ARM_NEON`-free but shadow
  `<arm_neon.h>` with a websim header on the include path that maps the NEON intrinsics each
  unit uses (`vrecpeq_f32`, `vbslq_s32`, `veorq_s32`, `vmul_n_f32`, `vld1q_f32`, …) onto scalar
  `.val[]` struct ops — i.e. extend the same idea as
  [websim/dsp/legacy/arm_math.h](../../websim/dsp/legacy/arm_math.h) but for `arm_neon.h`.
  SIMDe already does this for *native* vectors; here we need it for the **struct** shape so it
  composes with KORG's non-NEON path. This single shim resolves modes 1–3 and avoids mode 4
  (no `_n_` immediate functions are compiled because we stay on the struct path).
- Scope the shim to the intrinsics actually used (grep shows a small set; `vox` needs 5).
  Add `__builtin_shufflevector`-free scalar implementations.

Alternative (more surgical, more vendored edits): take the **SIMDe path** and rewrite the
~10 offending KORG NEON-path helpers to portable code guarded by `#ifdef __EMSCRIPTEN__`
(like the prefetch fix already in `mk2_utils.h`). Rejected as the primary plan because it
doesn't fix MorphEQ's `.val[]` usage and spreads edits across vendored headers.

### A.3 Tasks
- [ ] A.3.1 Inventory the exact `v*` NEON intrinsics used across the five units
      (`grep -rhoE 'v[a-z0-9_]+\(' platform/microkorg2/{vox,MorphEQ,MultitapDelay,Vibrato,breveR}`).
- [ ] A.3.2 Write `websim/dsp/microkorg2/arm_neon.h` (struct-shape intrinsic shim) +
      `mk2_simd_compat.h`; wire via `WEBSIM_EMCC_EXTRA += -include .../mk2_simd_compat.h` and
      `-I websim/dsp/microkorg2` (already on the path).
- [ ] A.3.3 Build `vox` (osc bridge); triage remaining intrinsics into the shim.
- [ ] A.3.4 Build `Vibrato`, `MultitapDelay`, `breveR` (fx bridges; modfx/delfx/revfx →
      `fx.html`); confirm the typedef collision is gone.
- [ ] A.3.5 Build `MorphEQ` (modfx) — expect the most triage; verify `.val[]` access compiles.
- [ ] A.3.6 Wire each unit's `wasm.cc` + Makefile websim stanza; confirm `make list` /
      `make websim PROJECT=...`.

**Acceptance:** all five units build and link to wasm via `make wasm`, sliders render, audio plays.

---

## B. Audio-correctness validation (expansion §7, still manual)

Builds are verified; **audio output is not** — `emrun` opens Chrome, which CI/agents can't observe.

- [ ] B.1 Add an **offline render harness**: a second emcc target per unit (no AudioWorklet)
      that calls `Init` + `Process/Render/OSC_CYCLE` for N blocks at a fixed note/params and
      dumps a WAV/PCM to stdout. Lets correctness be checked headlessly and in CI.
- [ ] B.2 Golden spot-checks: compare the offline render of one unit per platform against a
      reference (FFT peak at the played note for oscillators; passthrough/impulse response for
      fx). Tolerance-based, not bit-exact (NEON scalarization differs).
- [ ] B.3 Document a manual per-unit smoke checklist in [WEBSIM.md](../../WEBSIM.md)
      (loads cross-origin-isolated, audio starts on gesture, every slider audible, no console
      errors).

---

## C. Breadth — more units & effect kinds

- [ ] C.1 **gen-1 effects harness.** Today the legacy harness is osc-only. Add modfx/delfx/revfx
      bridges for the gen-1 `MODFX_*`/`DELFX_*`/`REVFX_*` entry points (q31, stereo where
      applicable) → `fx.html`. Reference: the gen-1 `usermodfx.h`/`userdelfx.h`/`userrevfx.h`.
- [ ] C.2 **gen-1 param metadata from `manifest.json`.** The per-unit `WEBSIM_LEGACY_PARAM_LIST`
      table is hand-written ([nutekt-digital/waves/wasm.cc](../../platform/nutekt-digital/waves/wasm.cc)).
      Generate it from `manifest.json` (build-time codegen or a small JSON parse in the bridge)
      so arbitrary community gen-1 units work without editing C.
- [ ] C.3 **More gen-1 oscillators** (the large dukesrg/logue catalogue) — once C.2 lands,
      proving a few non-`waves` units is mostly free.
- [ ] C.4 **drumlogue sample playback.** The sample-bank accessors are stubbed
      (`get_sample = nullptr` in [dl_synth_bridge.h](../../websim/dsp/drumlogue/dl_synth_bridge.h)).
      Implement host stand-ins backed by the `websim/samples/` assets so sample-based drum
      synths produce sound; revisit `sample_wrapper.h`.

---

## D. microKORG2 small polyphony (deferred from v1)

v1 is single-voice (`voiceLimit = 1`). To exercise the real poly render path
(`outputStride`, `GetBufferOffset`, per-voice pitch, `waves`' inter-voice drift):
- [ ] D.1 Bump `voiceLimit` in [mk2_osc_bridge.h](../../websim/dsp/microkorg2/mk2_osc_bridge.h),
      allocate the per-voice output stride, and sum/downmix voices to the worklet output.
- [ ] D.2 Add a simple voice allocator in the bridge driven by `noteOn`/`noteOff` (round-robin),
      and (optional) a poly-count control in `osc.html`.

---

## E. Toolchain, CI & docs

- [ ] E.1 **Pin the Emscripten minimum** in [WEBSIM.md](../../WEBSIM.md): SIMDe `arm_neon.h`
      support is required (drumlogue), and recent emsdk **rejects**
      `-I.../emscripten/system/include` (the expansion removed it). Note both.
- [ ] E.2 **CI smoke build**: a job that runs `make wasm` (build only, skip `emrun`) for every
      project in `make list` and fails on any compile/link error. Factor a `wasm-build` target
      (no browser launch) out of `websim/wasm.mk` so CI can call it.
- [ ] E.3 Keep [WEBSIM.md](../../WEBSIM.md) "Supported platforms & caveats" current as A–D land
      (drop the "not yet wired" microKORG2 row when A completes).

---

## Sequencing

1. **A** (microKORG2 NEON units) — highest user-visible value; the SIMD shim is the one hard
   piece and unblocks five units at once.
2. **B.1** (offline render harness) — small, and makes everything after it verifiable headlessly.
3. **C.1–C.2** (gen-1 effects + manifest-driven params) — unlocks the largest external catalogue.
4. **C.4 / D / E** — polish and breadth, independently shippable.

Each item is independently shippable; stop after any with a coherent result.
