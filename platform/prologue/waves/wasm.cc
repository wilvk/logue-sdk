// websim host bridge for the gen-1 nutekt-digital "waves" oscillator.
// The param table mirrors manifest.json's 6 custom params; the shared legacy
// bridge appends the SHAPE / SHIFT-SHAPE knobs and drives OSC_INIT/CYCLE/PARAM.
#include "userosc.h"

#define WEBSIM_LEGACY_PARAM_LIST(X)   \
  X("Wave A", 0, 45, LP_NONE)         \
  X("Wave B", 0, 43, LP_NONE)         \
  X("Sub Wave", 0, 15, LP_NONE)       \
  X("Sub Mix", 0, 100, LP_PERCENT)    \
  X("Ring Mix", 0, 100, LP_PERCENT)   \
  X("Bit Crush", 0, 100, LP_PERCENT)

#include "legacy_osc_bridge.h"
