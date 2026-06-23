##############################################################################
# logue-sdk root Makefile — build & launch the web simulator (websim)
#
# Convenience wrapper around the per-project `make wasm` flow. See WEBSIM.md.
#
# Quick start:
#   make setup                              # one-time: fetch + install emsdk
#   make list                               # show wasm-capable projects
#   make websim                             # launch the default project (waves)
#   make websim PROJECT=platform/nts-3_kaoss/pluck
#   make websim PROJECT=dummy-osc           # bare name is resolved if unambiguous
#   make clean   PROJECT=waves
#
# Requirements: git, python3, GNU make, and Google Chrome (the per-project wasm
# target launches `emrun --browser chrome`). On Windows use Git Bash, MSYS2, or WSL.
##############################################################################

# Default project to launch (path relative to repo root, or a bare project name).
PROJECT ?= platform/nts-1_mkii/waves

EMSDK_DIR     := tools/emsdk
EMSDK         := $(EMSDK_DIR)/emsdk
EMCC_BIN_PATH := $(EMSDK_DIR)/upstream/emscripten

# Co-serve output root for `make websim-all`: every selected project is built
# into $(WEBSIM_SIM_ROOT)/<platform>/<project>/ and served together so the
# in-page device/project comboboxes can navigate between them.
WEBSIM_SIM_ROOT := websim/sim

# Auto-discover every project that can build a wasm sandbox: either it defines a
# literal `wasm:` target (legacy/inline) or it includes a shared websim fragment
# (websim/wasm.mk for gen-2, websim/legacy.mk for gen-1). Matching both keeps any
# not-yet-migrated project working during the transition.
WASM_PROJECTS := $(patsubst %/Makefile,%,$(shell \
    grep -rlE '^(wasm:|[[:space:]]*include .*/(wasm|legacy)\.mk)' \
    platform/*/*/Makefile 2>/dev/null))

# Resolve $(PROJECT) to a project directory at recipe time:
#   - a real path containing a Makefile is used as-is
#   - otherwise it's matched as a bare name against the discovered wasm projects
#   - 0 matches -> error with the list; >1 matches -> error asking for the full path
define resolve_project
	dir=""; \
	if [ -f "$(PROJECT)/Makefile" ]; then \
	  dir="$(PROJECT)"; \
	else \
	  matches=$$(printf '%s\n' $(WASM_PROJECTS) | grep -E "/$(PROJECT)$$" || true); \
	  count=$$(printf '%s\n' $$matches | grep -c . || true); \
	  if [ "$$count" = "1" ]; then \
	    dir="$$matches"; \
	  elif [ "$$count" = "0" ]; then \
	    echo "error: no wasm-capable project matches '$(PROJECT)'."; \
	    echo "Run 'make list' to see the available projects."; \
	    exit 1; \
	  else \
	    echo "error: '$(PROJECT)' is ambiguous; matches:"; \
	    printf '  %s\n' $$matches; \
	    echo "Re-run with the full path, e.g. PROJECT=platform/nts-1_mkii/$(PROJECT)"; \
	    exit 1; \
	  fi; \
	fi
endef

.DEFAULT_GOAL := help

.PHONY: help setup check list websim websim-all run clean

# Projects to bundle into the co-serve tree. Defaults to every wasm-capable
# project; override with a space-separated list of full paths, e.g.
#   make websim-all PROJECTS="platform/nts-1_mkii/waves platform/microkorg2/waves"
PROJECTS ?=
WEBSIM_ALL_PROJECTS := $(if $(PROJECTS),$(PROJECTS),$(WASM_PROJECTS))

help:
	@echo "logue-sdk websim launcher"
	@echo ""
	@echo "Targets:"
	@echo "  setup            One-time: fetch the emsdk submodule and install/activate Emscripten."
	@echo "  list             List all wasm-capable projects."
	@echo "  websim           Build a single project to WebAssembly and open it in the browser."
	@echo "  websim-all       Build every (or PROJECTS=...) project into one tree and serve them"
	@echo "                   together, with in-page Device/Project comboboxes to switch units."
	@echo "  clean            Remove a project's build/ and sim/ output."
	@echo "  help             Show this message."
	@echo ""
	@echo "Variables:"
	@echo "  PROJECT          Project path or bare name for 'websim' (default: $(PROJECT))."
	@echo "  PROJECTS         Space-separated project paths to bundle for 'websim-all' (default: all)."
	@echo ""
	@echo "Examples:"
	@echo "  make setup"
	@echo "  make websim                                            # default (NTS-1 mkII waves)"
	@echo "  make websim-all                                        # all units, switchable in-page"
	@echo "  make websim-all PROJECTS=\"platform/nts-1_mkii/waves platform/microkorg2/waves\""
	@echo "  make websim PROJECT=platform/nts-3_kaoss/pluck"
	@echo "  make websim PROJECT=platform/microkorg2/waves          # microKORG2 (gen-2)"
	@echo "  make websim PROJECT=platform/drumlogue/dummy-synth     # drumlogue (stereo synth)"
	@echo "  make websim PROJECT=platform/nutekt-digital/waves      # NTS-1 mkI / gen-1 osc"
	@echo "  make websim PROJECT=platform/minilogue-xd/waves        # minilogue xd / gen-1 osc"
	@echo "  make websim PROJECT=platform/prologue/waves            # prologue / gen-1 osc"
	@echo "  make websim PROJECT=dummy-osc                          # bare name (must be unambiguous)"

# Clear stale emsdk env vars for the bootstrap. Sourcing emsdk_env.sh in a
# shell profile exports EMSDK_PYTHON / EMSDK_NODE / SSL_CERT_FILE pointing into
# bundled tool dirs (python, node, certifi) that a fresh checkout hasn't
# downloaded yet. They then break the very `emsdk install` meant to fetch them
# (missing python interpreter, missing CA bundle for curl). Unset them so the
# wrapper falls back to python3 / the system CA store from PATH.
BOOTSTRAP_ENV := env -u EMSDK_PYTHON -u EMSDK_NODE -u SSL_CERT_FILE -u CURL_CA_BUNDLE -u REQUESTS_CA_BUNDLE

setup:
	@echo "==> Fetching emsdk submodule"
	git submodule update --init $(EMSDK_DIR)
	@echo "==> Installing latest Emscripten (this may take a while)"
	cd $(EMSDK_DIR) && $(BOOTSTRAP_ENV) ./emsdk install latest
	@echo "==> Activating latest Emscripten"
	cd $(EMSDK_DIR) && $(BOOTSTRAP_ENV) ./emsdk activate latest
	@echo "==> Done. You can now run 'make websim'."

check:
	@test -x $(EMSDK) || { \
	  echo "error: Emscripten not set up ($(EMSDK) missing)."; \
	  echo "Run 'make setup' first."; \
	  exit 1; \
	}
	@test -x $(EMSDK_DIR)/upstream/emscripten/emcc || { \
	  echo "error: emcc not found — emsdk is fetched but not installed/activated."; \
	  echo "Run 'make setup' (or: cd $(EMSDK_DIR) && ./emsdk install latest && ./emsdk activate latest)."; \
	  exit 1; \
	}

list:
	@echo "wasm-capable projects:"
	@printf '  %s\n' $(WASM_PROJECTS)

# Build to WebAssembly and launch the browser sandbox.
websim run: check
	@$(resolve_project); \
	echo "==> Launching websim for $$dir"; \
	$(MAKE) -C "$$dir" wasm

# Build every (or PROJECTS="...") unit into one tree and serve them together so
# the in-page Device/Project comboboxes can switch between units. Building all
# projects with -O2 takes a while; pass PROJECTS=... to bundle a subset.
websim-all: check
	@echo "==> Building $(words $(WEBSIM_ALL_PROJECTS)) project(s) into $(WEBSIM_SIM_ROOT)"
	@rm -rf $(WEBSIM_SIM_ROOT)
	@mkdir -p $(WEBSIM_SIM_ROOT)
	@set -e; for p in $(WEBSIM_ALL_PROJECTS); do \
	  plat=$$(basename $$(dirname $$p)); \
	  proj=$$(basename $$p); \
	  echo "==> $$plat/$$proj"; \
	  $(MAKE) --no-print-directory -C "$$p" wasm-build \
	    WASMDIR="$(abspath $(WEBSIM_SIM_ROOT))/$$plat/$$proj"; \
	done
	@python3 websim/gen_manifest.py $(WEBSIM_SIM_ROOT) .
	@echo "==> Opening the websim launcher"
	@$(EMCC_BIN_PATH)/emrun --browser chrome --serve_after_close \
	  --serve_root $(WEBSIM_SIM_ROOT) $(WEBSIM_SIM_ROOT)/index.html

clean:
	@$(resolve_project); \
	echo "==> Cleaning $$dir"; \
	$(MAKE) -C "$$dir" clean
