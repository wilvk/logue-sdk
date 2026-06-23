#!/usr/bin/env python3
"""websim dev server — serve the co-serve tree AND compile projects on demand.

`make websim` builds the requested PROJECT into websim/sim/<platform>/<project>/,
writes a projects.json that lists *every* wasm-capable project (built or not),
then launches this server. The in-page Project combobox
(websim/scripts/websim-selector.js) loads a built project directly; for one that
isn't built yet it calls

    GET /api/compile?project=<platform>/<project>

which runs `make wasm-build` for that unit into the same tree, regenerates the
manifest, and returns the emitted page so the browser can navigate to it. A
loading overlay is shown until the build finishes and the page loads.

Like `emrun`, every response carries the COOP/COEP/CORP headers that make the
origin cross-origin-isolated, so SharedArrayBuffer / AudioWorklet work. The
unit's `.wasm` is served as application/wasm. Stdlib only — no third-party deps.

Usage (normally invoked by the root Makefile's `websim` target):
    websim_server.py --root websim/sim --repo-root . \\
        --projects "platform/nts-1_mkii/waves platform/microkorg2/waves ..." \\
        --open nts-1_mkii/waves/waves.html
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

# Import the manifest writer from the sibling websim/ dir so a successful
# compile can refresh projects.json (flip the unit's "built" flag).
WEBSIM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEBSIM_DIR)
import gen_manifest  # noqa: E402

# A project id is "<platform>/<project>": dir-name characters only, no traversal.
SAFE_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*$")

# How much build output to ship back to the browser on failure.
LOG_TAIL = 6000


def tail(text):
    return text if len(text) <= LOG_TAIL else "…\n" + text[-LOG_TAIL:]


class Handler(SimpleHTTPRequestHandler):
    # Cross-origin isolation: the same headers emrun sends, required for
    # SharedArrayBuffer / AudioWorklet. Applied to every response.
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        super().end_headers()

    def copyfile(self, source, outputfile):
        # Browsers routinely abort in-flight responses (navigation, the
        # compile-on-demand redirect, AudioWorklet/wasm reloads, media range
        # seeks). That surfaces as BrokenPipeError/ConnectionResetError mid-send;
        # it's expected, so don't dump a traceback for it.
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if urlparse(self.path).path == "/api/compile":
            return self.handle_compile()
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path == "/api/compile":
            return self.handle_compile()
        return self.send_error(HTTPStatus.NOT_FOUND)

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_compile(self):
        ctx = self.server.ctx
        q = parse_qs(urlparse(self.path).query)
        pid = gen_manifest.norm_id(unquote((q.get("project") or [""])[0]))
        if not SAFE_ID.match(pid) or ".." in pid or pid not in ctx["projects"]:
            return self.send_json(HTTPStatus.BAD_REQUEST,
                                  {"ok": False, "error": "unknown project: %r" % pid})

        proj_dir = os.path.join(ctx["repo_root"], "platform", pid)
        wasmdir = os.path.abspath(os.path.join(ctx["sim_root"], pid))
        cmd = [ctx["make"], "--no-print-directory", "-C", proj_dir,
               "wasm-build", "WASMDIR=" + wasmdir]

        # Serialize builds: they share one emsdk and the build is the slow part,
        # so there's no win in running them concurrently and plenty of room for
        # contention if we did.
        with ctx["lock"]:
            print("==> compiling %s" % pid)
            proc = subprocess.run(cmd, cwd=ctx["repo_root"],
                                  capture_output=True, text=True)
            log = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode != 0:
                sys.stderr.write(log + "\n")
                return self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR,
                                      {"ok": False, "error": "build failed",
                                       "log": tail(log)})
            # Refresh the manifest so a later visit sees this unit as built.
            gen_manifest.write_manifest(ctx["sim_root"], ctx["repo_root"],
                                        sorted(ctx["projects"]),
                                        can_compile=True, default_id=pid)

        page = gen_manifest.find_page(wasmdir)
        if not page:
            return self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR,
                                  {"ok": False, "error": "no page produced",
                                   "log": tail(log)})
        print("    done: %s/%s" % (pid, page))
        return self.send_json(HTTPStatus.OK, {"ok": True, "page": "%s/%s" % (pid, page)})

    def log_message(self, fmt, *args):
        pass  # keep the console quiet; compiles log themselves


def open_browser(url):
    """Open Chrome if we can find it (parity with emrun --browser chrome)."""
    try:
        webbrowser.get("chrome").open(url)
        return
    except Exception:
        pass
    if sys.platform == "darwin":
        try:
            subprocess.Popen(["open", "-a", "Google Chrome", url])
            return
        except Exception:
            pass
    webbrowser.open(url)


def main():
    ap = argparse.ArgumentParser(description="websim compile-on-demand dev server")
    ap.add_argument("--root", required=True, help="co-serve tree (e.g. websim/sim)")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--projects", default="",
                    help="space-separated platform/<plat>/<proj> paths that may be compiled")
    ap.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    ap.add_argument("--open", default="", help="page path to open in the browser")
    ap.add_argument("--make", default=os.environ.get("MAKE", "make"))
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    ctx = {
        "sim_root": os.path.abspath(args.root),
        "repo_root": os.path.abspath(args.repo_root),
        "projects": {gen_manifest.norm_id(p) for p in args.projects.split()},
        "make": args.make,
        "lock": threading.Lock(),
    }

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port),
                                partial(Handler, directory=ctx["sim_root"]))
    httpd.ctx = ctx
    port = httpd.server_address[1]
    url = "http://localhost:%d/%s" % (port, args.open.lstrip("/"))

    print("==> websim serving %s" % ctx["sim_root"])
    print("==> %s  (Ctrl-C to stop)" % url)
    if not args.no_browser:
        threading.Timer(0.4, lambda: open_browser(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n==> websim server stopped.")


if __name__ == "__main__":
    main()
