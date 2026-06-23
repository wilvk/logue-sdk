// websim-selector.js — device + project switcher for the websim shells.
//
// Populated from /projects.json (written by websim/gen_manifest.py). Each entry
// is {id, name, shell, built, page}.
//
// * `make websim` serves the tree through websim/scripts/websim_server.py and
//   the manifest carries `canCompile: true`. The combobox lists *every* project;
//   picking one that's already built loads its page, and picking one that isn't
//   compiles it on demand via GET /api/compile (a loading overlay covers the wait)
//   before loading the freshly emitted page.
// * `make websim-all` prebuilds everything and serves it with emrun, so every
//   listed project is built and selecting one just navigates — no overlay.
// * A single unit served standalone by `make wasm` has no manifest, so
//   /projects.json 404s and the selector hides itself: the page looks unchanged.
(function () {
  "use strict";

  // "/nts-1_mkii/waves/waves.html" -> "nts-1_mkii/waves/waves.html"
  function currentPagePath() {
    return decodeURIComponent(window.location.pathname).replace(/^\/+/, "");
  }

  function option(value, text) {
    var o = document.createElement("option");
    o.value = value;
    o.textContent = text;
    return o;
  }

  // ---- loading / error overlay (injected so every shell shares it) ----------
  function ensureOverlay() {
    var el = document.getElementById("WebsimOverlay");
    if (el) return el;

    var css = document.createElement("style");
    css.textContent =
      "#WebsimOverlay{position:fixed;inset:0;z-index:9999;display:none;" +
      "align-items:center;justify-content:center;background:rgba(8,9,12,.78);" +
      "backdrop-filter:blur(2px);font-family:'Space Grotesk',sans-serif;color:#e8e9ec}" +
      "#WebsimOverlay .ws-card{background:#1a1c22;border:1px solid #2e323c;" +
      "border-radius:14px;padding:26px 30px;max-width:min(820px,92vw);" +
      "box-shadow:0 18px 50px rgba(0,0,0,.5);text-align:center}" +
      "#WebsimOverlay .ws-spinner{width:34px;height:34px;margin:0 auto 16px;" +
      "border:3px solid #2e323c;border-top-color:#f3e939;border-radius:50%;" +
      "animation:ws-spin .8s linear infinite}" +
      "@keyframes ws-spin{to{transform:rotate(360deg)}}" +
      "#WebsimOverlay .ws-msg{font-size:15px;font-weight:700;letter-spacing:.3px}" +
      "#WebsimOverlay .ws-sub{margin-top:6px;font-size:12px;color:#9aa0ab}" +
      "#WebsimOverlay .ws-log{display:none;margin:16px 0 0;max-height:46vh;overflow:auto;" +
      "text-align:left;white-space:pre-wrap;font-size:11px;line-height:1.45;color:#cdd2db;" +
      "background:#0e0f13;border:1px solid #2e323c;border-radius:8px;padding:12px}" +
      "#WebsimOverlay .ws-close{display:none;margin-top:16px;font-family:inherit;" +
      "font-size:13px;color:#e8e9ec;background:#22252e;border:1px solid #2e323c;" +
      "border-radius:8px;padding:7px 16px;cursor:pointer}" +
      "#WebsimOverlay .ws-close:hover{border-color:#f3e939;color:#f3e939}";
    document.head.appendChild(css);

    el = document.createElement("div");
    el.id = "WebsimOverlay";
    el.innerHTML =
      '<div class="ws-card">' +
      '<div class="ws-spinner" id="WebsimSpinner"></div>' +
      '<div class="ws-msg" id="WebsimOverlayMsg"></div>' +
      '<div class="ws-sub" id="WebsimOverlaySub"></div>' +
      '<pre class="ws-log" id="WebsimOverlayLog"></pre>' +
      '<button class="ws-close" id="WebsimOverlayClose">Close</button>' +
      "</div>";
    document.body.appendChild(el);
    document.getElementById("WebsimOverlayClose").onclick = hideOverlay;
    return el;
  }

  function showLoading(msg, sub) {
    var el = ensureOverlay();
    document.getElementById("WebsimSpinner").style.display = "";
    document.getElementById("WebsimOverlayMsg").textContent = msg;
    document.getElementById("WebsimOverlaySub").textContent = sub || "";
    document.getElementById("WebsimOverlayLog").style.display = "none";
    document.getElementById("WebsimOverlayClose").style.display = "none";
    el.style.display = "flex";
  }

  function showError(msg, log) {
    ensureOverlay();
    document.getElementById("WebsimSpinner").style.display = "none";
    document.getElementById("WebsimOverlayMsg").textContent = msg;
    document.getElementById("WebsimOverlaySub").textContent =
      "The other units are still available — pick another, or fix the build and retry.";
    var logEl = document.getElementById("WebsimOverlayLog");
    if (log) {
      logEl.textContent = log;
      logEl.style.display = "block";
    }
    document.getElementById("WebsimOverlayClose").style.display = "inline-block";
    document.getElementById("WebsimOverlay").style.display = "flex";
  }

  function hideOverlay() {
    var el = document.getElementById("WebsimOverlay");
    if (el) el.style.display = "none";
  }

  function init(manifest) {
    var devices = (manifest && manifest.devices) || [];
    var canCompile = !!(manifest && manifest.canCompile);
    var container = document.getElementById("WebsimSelector");
    var deviceSelect = document.getElementById("DeviceSelect");
    var projectSelect = document.getElementById("ProjectSelect");

    if (!container || !deviceSelect || !projectSelect || devices.length === 0) {
      if (container) container.style.display = "none";
      return;
    }

    var here = currentPagePath();
    var byId = {};
    devices.forEach(function (d) {
      d.projects.forEach(function (p) { byId[p.id] = p; });
    });

    // Which project/device is the page we're currently on (default: first).
    var currentId = devices[0].projects[0] && devices[0].projects[0].id;
    var currentDeviceId = devices[0].id;
    devices.forEach(function (d) {
      d.projects.forEach(function (p) {
        if (p.page && p.page === here) {
          currentId = p.id;
          currentDeviceId = d.id;
        }
      });
    });

    function deviceById(id) {
      return devices.filter(function (d) { return d.id === id; })[0] || devices[0];
    }

    function fillProjects(deviceId, selectedId) {
      projectSelect.innerHTML = "";
      var d = deviceById(deviceId);
      d.projects.forEach(function (p) {
        projectSelect.appendChild(option(p.id, p.name));
      });
      if (selectedId && byId[selectedId]) projectSelect.value = selectedId;
      if (!projectSelect.value && d.projects.length) {
        projectSelect.value = d.projects[0].id;
      }
    }

    // Load (and, if needed, compile) the chosen project.
    function go(id) {
      var p = byId[id];
      if (!p || id === currentId) return;
      if (p.built && p.page) {
        window.location.href = "/" + p.page;
        return;
      }
      if (!canCompile) {
        if (p.page) window.location.href = "/" + p.page;
        return;
      }
      compileThenLoad(p);
    }

    function compileThenLoad(p) {
      showLoading("Compiling " + p.name + "…",
                  "Building the WebAssembly unit — this can take a few seconds.");
      fetch("/api/compile?project=" + encodeURIComponent(p.id), { method: "GET" })
        .then(function (r) { return r.json().catch(function () { return null; }); })
        .then(function (res) {
          if (res && res.ok && res.page) {
            showLoading("Loading " + p.name + "…", "");
            window.location.href = "/" + res.page;
          } else {
            projectSelect.value = currentId; // undo the failed selection
            showError("Couldn't build " + p.name,
                      (res && (res.log || res.error)) || "Unknown build error.");
          }
        })
        .catch(function (err) {
          projectSelect.value = currentId;
          showError("Couldn't build " + p.name, String(err));
        });
    }

    devices.forEach(function (d) {
      deviceSelect.appendChild(option(d.id, d.name));
    });
    deviceSelect.value = currentDeviceId;
    fillProjects(currentDeviceId, currentId);

    // Changing device repopulates the project list and loads that device's first
    // project; changing project loads it. Re-selecting the current is a no-op.
    deviceSelect.onchange = function () {
      fillProjects(deviceSelect.value, null);
      go(projectSelect.value);
    };
    projectSelect.onchange = function () {
      go(projectSelect.value);
    };

    container.style.display = ""; // reveal (class .control -> display:flex)
  }

  document.addEventListener("DOMContentLoaded", function () {
    fetch("/projects.json", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(init)
      .catch(function () {
        var c = document.getElementById("WebsimSelector");
        if (c) c.style.display = "none";
      });
  });
})();
