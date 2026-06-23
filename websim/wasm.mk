##############################################################################
# websim shared build fragment
#
# Extracted from the per-project `wasm:` recipe that used to be duplicated
# inline in every NTS-1 mkII / NTS-3 project Makefile. Including this file gives
# a project a `wasm:` target that builds its DSP to WebAssembly with Emscripten
# and launches the browser sandbox. See WEBSIM.md.
#
# A project includes it (after `include config.mk`) like so:
#
#   WEBSIM_SHELL    := osc.html              # osc.html | fx.html | xypad.html | synth.html
#   WEBSIM_INCFLAGS := $(INCDIR)             # -I flags for the unit's own headers
#   include $(SANDBOXDIR)/wasm.mk
#
# Optional overrides (sensible defaults below):
#   WEBSIM_UNITSRC    bridge + unit sources           (default: wasm.cc $(UCSRC) $(UCXXSRC))
#   WEBSIM_DSP        firmware-ROM stand-in sources    (default: websim/dsp/*.c + *.cpp)
#   WEBSIM_EMCC_EXTRA extra emcc flags (e.g. SIMD)     (default: empty)
#   WEBSIM_WORKLET    AudioWorklet processor name      (default: logue-osc)
##############################################################################

# Locate the shared websim assets and the emsdk relative to the project root.
# Every supported project Makefile defines PROJECT_ROOT before including us.
SANDBOXDIR    ?= $(realpath $(PROJECT_ROOT)/../../../websim)
TOOLSDIR      ?= $(realpath $(PROJECT_ROOT)/../../../tools)
EMCC_BIN_PATH ?= $(TOOLSDIR)/emsdk/upstream/emscripten
WASMDIR       ?= $(PROJECT_ROOT)/sim

# Note: do NOT add emsdk's .../emscripten/system/include to the include path.
# Recent Emscripten rejects including headers directly from its source tree
# ("Please use the cache/sysroot/include directory"); emcc resolves its own
# system headers via the sysroot automatically. SIMDe (arm_neon.h) is likewise
# pulled in from the sysroot when building with -msimd128.

# Defaults — a project overrides any of these before `include`-ing this file.
WEBSIM_SHELL    ?= osc.html
WEBSIM_DSP      ?= $(wildcard $(SANDBOXDIR)/dsp/*.c) $(wildcard $(SANDBOXDIR)/dsp/*.cpp)
WEBSIM_UNITSRC  ?= wasm.cc $(UCSRC) $(UCXXSRC)
WEBSIM_INCFLAGS ?=
WEBSIM_EMCC_EXTRA ?=

# Full source list handed to emcc. Note what's intentionally absent vs. the
# hardware build: no _unit_base.c, no CMSIS, no linker script.
WEBSIM_WASMSRC := $(WEBSIM_UNITSRC) $(WEBSIM_DSP)

.PHONY: wasm wasm-build

# Build-only: compile the DSP to wasm and stage the page + assets in WASMDIR,
# WITHOUT launching a server. `make wasm` adds the emrun launch on top; the root
# Makefile's `websim-all` reuses this with a per-project WASMDIR to co-serve many
# units from one tree (see WEBSIM.md).
wasm-build:
	@echo Building WebAssembly audio processor
	@mkdir -p $(WASMDIR)
	@cp -r $(SANDBOXDIR)/samples $(WASMDIR)/
	@cp -r $(SANDBOXDIR)/scripts $(WASMDIR)/
	@cp -r $(SANDBOXDIR)/images $(WASMDIR)/
	@cp -r $(WEBSIM_WASMSRC) $(WASMDIR)/
	@$(EMCC_BIN_PATH)/emcc -Wno-unknown-attributes -Wno-limited-postlink-optimizations \
		$(WEBSIM_INCFLAGS) \
		-s AUDIO_WORKLET=1 \
		-s WASM_WORKERS=1 \
		-lembind \
		--shell-file $(SANDBOXDIR)/$(WEBSIM_SHELL) \
		--emrun \
		-O2 \
		-g -fdebug-compilation-dir='..' \
		$(WEBSIM_EMCC_EXTRA) \
		$(WEBSIM_WASMSRC) \
		-o $(WASMDIR)/$(PROJECT).html
	@echo Done

# Build a single unit and launch its sandbox (the standalone flow).
wasm: wasm-build
	@echo Opening the sandbox
	@$(EMCC_BIN_PATH)/emrun --browser chrome --serve_after_close $(WASMDIR)/$(PROJECT).html
