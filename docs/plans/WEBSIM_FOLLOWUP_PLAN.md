# websim Follow-up Plan — Remaining Work After the Platform Expansion

Status: **complete** — §A, §B, §C.1, §C.2, §C.4, §D, §E done; §C.3 enabled (no in-repo units to
wire). §D landed after fixing two real bugs in vox's never-before-exercised x4 path (see §D).
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
- [x] A.3.1 Inventory the exact `v*` NEON intrinsics used across the five units. **Result:**
      only **5** are used directly, all in `vox`: `vrecpeq_f32`, `vrecpe_f32`, `veorq_s32`,
      `veor_s32`, `vbslq_s32`. MorphEQ/Vibrato/MultitapDelay/breveR use **none** directly.
- [x] A.3.2 Wrote `websim/dsp/microkorg2/mk2_simd_compat.h` (5 scalar `.val[]` intrinsics over
      KORG's struct types; includes only `float_simd.h` — *not* `fixed_simd.h`, which depends on
      `fixed_math.h` and breaks if pulled early) + `websim/dsp/microkorg2/arm_neon.h` (shadows
      SIMDe). Wired via `WEBSIM_EMCC_EXTRA := -include .../mk2_simd_compat.h` and the existing
      `-I .../dsp/microkorg2`. **No `-msimd128` needed** — the struct path is pure scalar C++.
- [x] A.3.3 Built `vox` (osc bridge). The 5 intrinsics were the only triage.
- [x] A.3.4 Built `Vibrato`, `MultitapDelay`, `breveR`. The SIMDe collision for the FX units
      comes from `common/attributes.h` (+ `common/dsp/LinearSmoother.h`) pulling `<arm_neon.h>`
      *transitively*; the shadow header intercepts it. `breveR` additionally calls KORG's
      `cortexa7_intrinsics.h` ARM-asm saturating ops (via `fixed_math.h`) — guarded with an
      `#ifdef __EMSCRIPTEN__` portable path (same pattern as `mk2_utils.h`).
- [x] A.3.5 Built `MorphEQ` (modfx). `.val[]` access compiles on the struct path; its render
      method is named `Render`, not `Process`, so the fx bridge gained an `MK2_FX_RENDER` hook.
- [x] A.3.6 Wired each unit's `wasm.cc` + Makefile websim stanza. `make list` shows all five;
      `make wasm-build` links each. waves/dummy templates still build (no regression).

**Acceptance:** all five units build and link to wasm via `make wasm` — **done**. Slider render /
audio playback is browser-only; covered headlessly by the §B.1 offline render harness.

---

## B. Audio-correctness validation (expansion §7, still manual)

Builds are verified; **audio output is not** — `emrun` opens Chrome, which CI/agents can't observe.

- [x] B.1 **Offline render harness** added: `make render` (in `websim/wasm.mk`) rebuilds the same
      DSP/bridge in `WEBSIM_RENDER` mode — no AudioWorklet — and runs it under emsdk node to dump a
      32-bit-float WAV (`websim/dsp/wav_writer.h`). The shared bridges (mk2 osc/fx, drumlogue
      synth/fx, gen-1 legacy osc) gained a `#ifdef WEBSIM_RENDER` `main`; setup was factored into a
      shared `websim_setup_processor()`. The inline NTS-1 mkII/NTS-3 bridges aren't dual-moded yet.
- [x] B.2 Golden spot-checks via `websim/scripts/check_render.py` (stdlib-only: peak/RMS/NaN +
      autocorrelation f0). `vox` and gen-1 `waves` both render note 69 at ~440 Hz (≈1.4 cents).
      `make render-all` renders every render-capable project and asserts finite output (CI smoke).
- [x] B.3 Documented in [WEBSIM.md](../../WEBSIM.md#headless-render): render-harness usage, the
      `check_render.py` gates, and a manual per-unit browser smoke checklist.

---

## C. Breadth — more units & effect kinds

- [x] C.1 **gen-1 effects harness** added: `websim/dsp/legacy/legacy_fx_bridge.h` handles the
      `MODFX_*` (5-arg, interleaved stereo in/out + sub) and `DELFX_*`/`REVFX_*` (in-place)
      entry points → `fx.html`, selected by a `WEBSIM_LEGACY_FX_{MODFX,DELFX,REVFX}` define. It
      supplies the `_fx_get_bpm[f]` ROM stand-ins (fx_api.h owns the public inlines). Verified
      with a worked example, [`platform/nutekt-digital/tremolo`](../../platform/nutekt-digital/tremolo)
      (builds + renders). delfx/revfx share the bridge but aren't exercised by an example yet.
- [x] C.2 **gen-1 param metadata from `manifest.json`** done: `websim/gen_legacy_params.py` emits
      `websim_legacy_params.h` (the `WEBSIM_LEGACY_PARAM_LIST` macro) from a unit's manifest.json;
      `wasm.mk` generates it when a project sets `WEBSIM_LEGACY_MANIFEST` and puts it on the include
      path. The nutekt-digital / minilogue-xd / prologue `waves` units now include the generated
      header instead of a hand-written table (all still render note 69 at ~440 Hz).
- [~] C.3 **More gen-1 oscillators** — *enabled* by C.2 but not exercised: there are no additional
      gen-1 osc units in-repo. With C.2, wiring a community unit is just dropping its sources + a
      3-line `wasm.cc` (`#include "userosc.h"` / `"websim_legacy_params.h"` / `"legacy_osc_bridge.h"`)
      and a Makefile stanza with `WEBSIM_LEGACY_MANIFEST`. No C edits needed.
- [x] C.4 **drumlogue sample playback** added: `websim/dsp/drumlogue/dl_sample_bank.h` provides a
      synthetic host sample bank (sine/noise/chord one-shots as `sample_wrapper_t`), wired into the
      synth bridge's `get_num_sample_banks`/`get_num_samples_for_bank`/`get_sample`. The
      [`sample-voice`](../../platform/drumlogue/sample-voice) (SmplVox) unit now builds + renders an
      audible hit. (Synthetic, not the device's real PCM; backing it with the `websim/samples/`
      assets would need a WAV decoder + FS access — deferred.)

---

## D. microKORG2 small polyphony — implemented

v1 was single-voice; `vox` now opts into **4-voice** polyphony.

- [x] D.1 The osc bridge gained an opt-in `MK2_OSC_VOICES` (default 1). At 4 it sets
      `voiceLimit = 4`, `outputStride = 4` (one x4 voice group; output interleaved `[v0..v3]` per
      sample) and downmixes **only currently-held** voices (average → consistent level, no clipping
      or droning of idle voices). `vox/wasm.cc` sets `MK2_OSC_VOICES 4`; waves/dummy stay mono.
- [x] D.2 Round-robin voice allocator in the bridge (`noteOn`/`noteOff` → per-voice `pitch[v]` +
      `processor.voiceEvent(allocation/release)`); pitch comes from the (exact) note number. The
      render harness accepts a comma-separated chord (`make render ... WEBSIM_RENDER_ARGS="out.wav
      57,60,64"`) and `check_render.py --peaks` (Goertzel) verifies all chord tones are present at
      comparable energy — `vox` renders a stable A-minor triad (220/261.6/329.6 Hz); a single note
      fails the 3-peak check (true discrimination).

**Two real bugs found and fixed while enabling the x4 path (which the shipped single-voice scalar
path never exercised):**
1. **Buffer overflow (the divergence):** `vox`'s `mOscBuffer` is `kMk2HalfVoices*kMk2BufferSize`
   = 256 floats (the unit's hardware block is 64). websim renders a 128-sample Web Audio quantum;
   mono writes `mOscBuffer[i]` (≤128, fits) but the x4 path writes `mOscBuffer[i*4+v]` up to 511,
   overrunning 256 and corrupting adjacent member arrays (e.g. `mNoiseLevelMod` → spurious noise →
   the high-Q formant filter rang up → divergence to ~10³). Fix: the bridge renders in
   `≤ kMk2BufferSize`-sample sub-blocks (poly only; mono keeps its single 128 call).
2. **UB in `float_simd.h`:** `si_i32x{2,4}qn_to_f32x{2,4}` non-NEON path computed
   `1.f / (1 << qPoint)` — `1 << 31` is signed-int overflow (UB). It only ever ran via `UpdateEg`
   with a 0 phase before, so it was masked. Fixed to `1.f / (float)((uint64_t)1 << qPoint)`
   (ARM build uses the NEON `vcvtq_n_f32_s32` branch, unaffected).

---

## E. Toolchain, CI & docs

- [x] E.1 **Emscripten minimum pinned** in [WEBSIM.md](../../WEBSIM.md) prerequisites (≥3.1.x for
      SIMDe `arm_neon.h`; must not add `-I.../emscripten/system/include`; CI pins 4.0.16).
- [x] E.2 **CI smoke** added: [.github/workflows/websim.yml](../../.github/workflows/websim.yml)
      runs `make build-all` (compile/link every wasm unit; fails on any error) and `make render-all`
      (render every render-capable unit, assert finite audio). Root `build-all` + `render-all`
      targets factor the per-project `wasm-build` / `render` (in `websim/wasm.mk`).
- [x] E.3 [WEBSIM.md](../../WEBSIM.md) kept current: project table + per-platform caveats updated
      for the microKORG2 real units, drumlogue sample playback, and gen-1 fx; added the headless
      render-harness section.

---

## Sequencing

1. **A** (microKORG2 NEON units) — highest user-visible value; the SIMD shim is the one hard
   piece and unblocks five units at once.
2. **B.1** (offline render harness) — small, and makes everything after it verifiable headlessly.
3. **C.1–C.2** (gen-1 effects + manifest-driven params) — unlocks the largest external catalogue.
4. **C.4 / D / E** — polish and breadth, independently shippable.

Each item is independently shippable; stop after any with a coherent result.
