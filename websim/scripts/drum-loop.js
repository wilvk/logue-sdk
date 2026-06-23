// drum-loop.js — shared 8-bar drum step sequencer panel for the websim shells.
//
// Each shell sets up its own audio graph + keyboard, records the last note
// played on the keyboard in window.lastPlayedNote / window.lastPlayedFrequency,
// then calls window.initDrumLoop(opts) to drop a "Drum Loop" panel into the
// page. Selected beats retrigger that last note as a short percussive blip on
// the shell's shared `envelope` GainNode.
//
// The shells differ in how a pitch is produced — the osc shell drives the wasm
// voice via Module.setOscPitch/noteOn, while the fx/xypad shells set the
// frequency of a continuously running OscillatorNode — so the pitch/gate hooks
// are passed in:
//
//   initDrumLoop({
//     mount,               // element to append the panel to (defaults to .grid)
//     context,             // AudioContext
//     envelope,            // GainNode the percussive blip is applied to
//     setPitch(frequency), // point the voice at this frequency
//     noteOn(note),        // optional: gate/trigger the voice on
//     noteOff(note),       // optional: gate the voice off
//   })
//
// Timing uses the Web Audio clock with a setInterval lookahead (the standard
// "two clocks" pattern) so it stays steady regardless of main-thread jitter;
// the visual playhead is driven off the same scheduled times.
(function () {
  "use strict";

  var BARS = 8, BEATS_PER_BAR = 4, STEPS = BARS * BEATS_PER_BAR;
  var LOOKAHEAD = 0.1;  // seconds scheduled ahead of the clock
  var TICK = 25;        // ms between scheduler ticks

  function injectCss() {
    if (document.getElementById("DrumLoopCss")) return;
    var css = document.createElement("style");
    css.id = "DrumLoopCss";
    css.textContent =
      ".drumctl{display:flex;align-items:center;gap:18px;flex-wrap:wrap;margin-bottom:12px}" +
      "#DrumGrid{display:flex;flex-wrap:wrap;gap:16px}" +
      ".bar{display:flex;flex-direction:column;gap:6px}" +
      ".bar .barlabel{color:var(--muted);font-size:11px;letter-spacing:1px;text-align:center}" +
      ".bar .beats{display:flex;gap:6px}" +
      ".beat{width:30px;height:30px;padding:0;border-radius:8px}" +   // a <button> — inherits .active accent
      ".beat.playing{outline:2px solid var(--text);outline-offset:1px}" + // playhead
      ".beat.active.playing{outline-color:var(--bg)}";
    document.head.appendChild(css);
  }

  function buildPanel(mount) {
    var section = document.createElement("section");
    section.className = "panel";
    section.style.gridArea = "drum";
    section.innerHTML =
      '<h2>Drum Loop<button id="DrumPlayButton" style="margin-left:auto">Play</button></h2>' +
      '<p class="tip">8 bars &times; 4 beats &middot; click beats to toggle &middot; retriggers the last note played on the keyboard</p>' +
      '<div class="drumctl">' +
        '<div class="control"><label for="DrumTempo">Tempo</label>' +
        '<input type="range" min="40" max="240" value="120" step="1" id="DrumTempo">' +
        '<span id="DrumTempoLabel" class="readout"></span></div>' +
        '<div class="control"><label>Note</label><span id="DrumNoteLabel" class="readout"></span></div>' +
        '<button id="DrumClearButton">Clear</button>' +
      '</div>' +
      '<div class="body"><div id="DrumGrid"></div></div>';
    mount.appendChild(section);
  }

  window.initDrumLoop = function (opts) {
    var context = opts.context, envelope = opts.envelope;
    var setPitch = opts.setPitch || function () {};
    var noteOn = opts.noteOn || function () {};
    var noteOff = opts.noteOff || function () {};
    var mount = opts.mount || document.querySelector(".grid") || document.body;

    injectCss();
    buildPanel(mount);

    var steps = new Array(STEPS).fill(false);
    var cells = [];
    var bpm = 120;
    var playing = false;
    var stepIndex = 0, nextTime = 0, timer = null;

    function secondsPerStep() { return 60.0 / bpm; } // one quarter-note beat per step

    // Build the 8 × 4 grid of toggle cells.
    var gridEl = document.getElementById("DrumGrid");
    for (var bar = 0; bar < BARS; bar++) {
      var barEl = document.createElement("div"); barEl.className = "bar";
      var label = document.createElement("div"); label.className = "barlabel";
      label.textContent = bar + 1; barEl.appendChild(label);
      var beatsEl = document.createElement("div"); beatsEl.className = "beats";
      for (var b = 0; b < BEATS_PER_BAR; b++) {
        (function (step, barNo, beatNo) {
          var cell = document.createElement("button");
          cell.type = "button"; cell.className = "beat";
          cell.title = "Bar " + (barNo + 1) + ", beat " + (beatNo + 1);
          cell.onclick = function () {
            steps[step] = !steps[step];
            cell.classList.toggle("active", steps[step]);
          };
          cells[step] = cell; beatsEl.appendChild(cell);
        })(bar * BEATS_PER_BAR + b, bar, b);
      }
      barEl.appendChild(beatsEl); gridEl.appendChild(barEl);
    }

    // Percussive blip on the shared envelope at audio time `time`, using
    // whatever note was last played on the keyboard (default A3 / 440Hz).
    function triggerHit(time) {
      var gate = Math.min(0.14, secondsPerStep() * 0.9);
      var delayMs = Math.max(0, (time - context.currentTime) * 1000);
      setTimeout(function () {
        if (!playing || context.state !== "running") return;
        var note = window.lastPlayedNote || "A3";
        var freq = window.lastPlayedFrequency || 440.0;
        setPitch(freq); noteOn(note);
        var now = context.currentTime;
        envelope.gain.cancelScheduledValues(now);
        envelope.gain.setValueAtTime(Math.max(envelope.gain.value, 1e-4), now);
        envelope.gain.linearRampToValueAtTime(1.0, now + 0.005);
        envelope.gain.linearRampToValueAtTime(0.0, now + gate);
        setTimeout(function () { noteOff(note); }, gate * 1000);
      }, delayMs);
    }

    function highlight(step, time) {
      var delayMs = Math.max(0, (time - context.currentTime) * 1000);
      setTimeout(function () {
        if (!playing) return;
        for (var i = 0; i < cells.length; i++) cells[i].classList.toggle("playing", i === step);
      }, delayMs);
    }

    function scheduler() {
      while (nextTime < context.currentTime + LOOKAHEAD) {
        if (steps[stepIndex]) triggerHit(nextTime);
        highlight(stepIndex, nextTime);
        nextTime += secondsPerStep();
        stepIndex = (stepIndex + 1) % STEPS;
      }
    }

    function start() {
      if (timer) return;
      stepIndex = 0; nextTime = context.currentTime + 0.1;
      timer = setInterval(scheduler, TICK);
    }
    function stop() {
      clearInterval(timer); timer = null;
      for (var i = 0; i < cells.length; i++) cells[i].classList.remove("playing");
    }

    var playBtn = document.getElementById("DrumPlayButton");
    playBtn.onclick = function () {
      playing = !playing;
      playBtn.classList.toggle("active", playing);
      playBtn.textContent = playing ? "Stop" : "Play";
      if (playing) {
        if (context.state !== "running") context.resume().catch(function () {});
        start();
      } else {
        stop();
      }
    };

    var tempo = document.getElementById("DrumTempo");
    var tempoLabel = document.getElementById("DrumTempoLabel");
    tempo.value = bpm; tempoLabel.textContent = bpm + " BPM";
    tempo.oninput = function () { bpm = Number(tempo.value); tempoLabel.textContent = bpm + " BPM"; };

    document.getElementById("DrumClearButton").onclick = function () {
      steps.fill(false);
      for (var i = 0; i < cells.length; i++) cells[i].classList.remove("active");
    };

    var noteLabel = document.getElementById("DrumNoteLabel");
    window.updateDrumNoteLabel = function (note) { noteLabel.textContent = note; };
    noteLabel.textContent = window.lastPlayedNote || "A3";
  };
})();
