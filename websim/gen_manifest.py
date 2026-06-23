#!/usr/bin/env python3
"""Generate the websim co-serve manifest (projects.json) and a landing index.html.

Two callers produce the manifest:

* `make websim-all` builds *every* project into a single tree and scans it:

      <sim-root>/<platform>/<project>/<page>.html   (+ .js/.wasm/assets)

  Run as `gen_manifest.py <sim-root> <repo-root>` (no --projects) it lists only
  the projects already built under <sim-root>.

* `make websim` builds just the requested project but lists *all* wasm-capable
  projects so the in-page Project combobox can offer every unit; the ones that
  aren't built yet are compiled on demand by websim/scripts/websim_server.py.
  Run as `gen_manifest.py <sim-root> <repo-root> --projects "<list>" --can-compile
  --default <id>`, where <list> is space-separated `platform/<plat>/<proj>` paths.

Each project entry is `{id, name, shell, built, page}`:
  id     "<platform>/<project>"  — stable key; also the dir under platform/
  name   project directory name  — shown in the combobox
  shell  osc | fx | xypad        — read from the project's Makefile
  built  bool                    — whether a page exists under <sim-root>
  page   "<platform>/<project>/<page>.html" or null when not built

The page filename is whatever emcc emitted (PROJECT from config.mk, which can
differ from the directory name — e.g. dummy-masterfx/ -> dummy_master.html), so
we discover it by scanning rather than assuming.

Usage: gen_manifest.py <sim-root> [<repo-root>]
                       [--projects "<paths>"] [--can-compile] [--default <id>]
"""
import argparse
import json
import os
import re
import sys

# Platform dir -> friendly device name shown in the combobox.
DEVICE_NAMES = {
    "nts-1_mkii": "NTS-1 mkII",
    "nts-3_kaoss": "NTS-3 kaoss",
    "microkorg2": "microKORG2",
    "drumlogue": "drumlogue",
    "nutekt-digital": "Nutekt Digital (NTS-1 mkI)",
    "minilogue-xd": "minilogue xd",
    "prologue": "prologue",
}

# Left-to-right device order in the combobox; unknown platforms are appended.
DEVICE_ORDER = [
    "nts-1_mkii", "nts-3_kaoss", "microkorg2", "drumlogue",
    "nutekt-digital", "minilogue-xd", "prologue",
]

# Preferred landing project (first match that was actually built wins).
DEFAULT_PAGE_PREFS = ["nts-1_mkii/waves", "microkorg2/waves"]


def norm_id(path):
    """'platform/microkorg2/waves' -> 'microkorg2/waves' (also tolerates a bare id)."""
    p = path.strip().strip("/")
    if p.startswith("platform/"):
        p = p[len("platform/"):]
    return p


def read_shell(repo_root, platform, project):
    """Return the unit's shell ('osc' | 'fx' | 'xypad') from its Makefile."""
    mk = os.path.join(repo_root, "platform", platform, project, "Makefile")
    try:
        with open(mk) as f:
            for line in f:
                m = re.match(r"\s*WEBSIM_SHELL\s*:?=\s*(\S+)", line)
                if m:
                    return m.group(1).strip().replace(".html", "")
    except OSError:
        pass
    return "osc"


def find_page(proj_dir):
    """The emcc-emitted HTML page in a built project dir (excludes index.html)."""
    try:
        pages = [f for f in os.listdir(proj_dir)
                 if f.endswith(".html") and f != "index.html"]
    except OSError:
        return None
    return sorted(pages)[0] if pages else None


def project_entry(sim_root, repo_root, platform, project):
    page = find_page(os.path.join(sim_root, platform, project))
    return {
        "id": "%s/%s" % (platform, project),
        "name": project,
        "shell": read_shell(repo_root, platform, project),
        "built": page is not None,
        "page": ("%s/%s/%s" % (platform, project, page)) if page else None,
    }


def collect_devices(sim_root, repo_root, project_ids=None):
    """Group projects by device.

    With `project_ids` (the make-target paths), list every one of them, marking
    each built or not. Without it, scan `sim_root` and list only built projects.
    """
    if project_ids:
        pairs = [tuple(norm_id(p).split("/", 1))
                 for p in project_ids if "/" in norm_id(p)]
    else:
        pairs = []
        for platform in sorted(os.listdir(sim_root)):
            plat_dir = os.path.join(sim_root, platform)
            if not os.path.isdir(plat_dir):
                continue
            for project in sorted(os.listdir(plat_dir)):
                if os.path.isdir(os.path.join(plat_dir, project)):
                    pairs.append((platform, project))

    devices = {}
    for platform, project in pairs:
        entry = project_entry(sim_root, repo_root, platform, project)
        # In scan mode a dir without a page isn't a project — skip it.
        if project_ids is None and not entry["built"]:
            continue
        dev = devices.setdefault(platform, {
            "id": platform,
            "name": DEVICE_NAMES.get(platform, platform),
            "projects": [],
        })
        dev["projects"].append(entry)

    for d in devices.values():
        d["projects"].sort(key=lambda p: p["name"])

    ordered = [devices.pop(p) for p in DEVICE_ORDER if p in devices]
    ordered += [devices[p] for p in sorted(devices)]
    return ordered


def pick_default(devices, default_id=None):
    built = [p for d in devices for p in d["projects"] if p["built"] and p["page"]]
    if default_id:
        nid = norm_id(default_id)
        for p in built:
            if p["id"] == nid:
                return p["page"]
    for pref in DEFAULT_PAGE_PREFS:
        for p in built:
            if p["page"].startswith(pref + "/"):
                return p["page"]
    return built[0]["page"] if built else None


def write_index(sim_root, default_page):
    if default_page:
        head = '<meta http-equiv="refresh" content="0; url=%s">\n' \
               '<script>location.replace(%s);</script>' \
               % (default_page, json.dumps(default_page))
        body = 'Loading the websim launcher… <a href="%s">continue</a>' % default_page
    else:
        head = ""
        body = "No websim projects were built. Run <code>make websim</code>."
    html = (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        "<title>logue-sdk websim</title>\n%s\n</head>\n<body>%s</body>\n</html>\n"
        % (head, body)
    )
    with open(os.path.join(sim_root, "index.html"), "w") as f:
        f.write(html)


def write_manifest(sim_root, repo_root=".", project_ids=None,
                   can_compile=False, default_id=None):
    """Write projects.json + index.html; return (n_devices, n_projects)."""
    devices = collect_devices(sim_root, repo_root, project_ids)
    manifest = {"devices": devices}
    if can_compile:
        manifest["canCompile"] = True
    with open(os.path.join(sim_root, "projects.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    write_index(sim_root, pick_default(devices, default_id))
    return len(devices), sum(len(d["projects"]) for d in devices)


def main():
    ap = argparse.ArgumentParser(description="Generate the websim manifest.")
    ap.add_argument("sim_root")
    ap.add_argument("repo_root", nargs="?", default=".")
    ap.add_argument("--projects", default="",
                    help="space-separated platform/<plat>/<proj> paths to list "
                         "(default: scan sim_root for built projects)")
    ap.add_argument("--can-compile", action="store_true",
                    help="mark the manifest as backed by a compile-on-demand server")
    ap.add_argument("--default", default=None,
                    help="project id to prefer as the landing page")
    args = ap.parse_args()

    project_ids = args.projects.split() or None
    ndev, nproj = write_manifest(args.sim_root, args.repo_root, project_ids,
                                 args.can_compile, args.default)
    print("wrote %s (%d device(s), %d project(s))"
          % (os.path.join(args.sim_root, "projects.json"), ndev, nproj))


if __name__ == "__main__":
    main()
