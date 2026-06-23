#!/usr/bin/env python3
"""Generate the websim co-serve manifest (projects.json) and a landing index.html.

`make websim-all` builds every (or a chosen subset of) websim project into a
single tree:

    <sim-root>/<platform>/<project>/<page>.html   (+ .js/.wasm/assets)

This script scans that tree for the built pages, reads each project's WEBSIM_SHELL
from its source Makefile, and writes:

    <sim-root>/projects.json   consumed by scripts/websim-selector.js
    <sim-root>/index.html      redirects to a sensible default project

The page filename is whatever emcc emitted (PROJECT from config.mk, which can
differ from the directory name — e.g. dummy-masterfx/ -> dummy_master.html), so
we discover it by scanning rather than assuming.

Usage: gen_manifest.py <sim-root> [<repo-root>]
"""
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
    pages = [f for f in os.listdir(proj_dir)
             if f.endswith(".html") and f != "index.html"]
    return sorted(pages)[0] if pages else None


def collect_devices(sim_root, repo_root):
    devices = {}  # platform -> {id, name, projects: [...]}
    for platform in sorted(os.listdir(sim_root)):
        plat_dir = os.path.join(sim_root, platform)
        if not os.path.isdir(plat_dir):
            continue
        for project in sorted(os.listdir(plat_dir)):
            proj_dir = os.path.join(plat_dir, project)
            if not os.path.isdir(proj_dir):
                continue
            page = find_page(proj_dir)
            if not page:
                continue
            dev = devices.setdefault(platform, {
                "id": platform,
                "name": DEVICE_NAMES.get(platform, platform),
                "projects": [],
            })
            dev["projects"].append({
                "name": project,
                "page": "%s/%s/%s" % (platform, project, page),
                "shell": read_shell(repo_root, platform, project),
            })

    ordered = [devices.pop(p) for p in DEVICE_ORDER if p in devices]
    ordered += [devices[p] for p in sorted(devices)]
    return ordered


def pick_default(devices):
    pages = [p["page"] for d in devices for p in d["projects"]]
    for pref in DEFAULT_PAGE_PREFS:
        for page in pages:
            if page.startswith(pref + "/"):
                return page
    return pages[0] if pages else None


def write_index(sim_root, default_page):
    if default_page:
        head = '<meta http-equiv="refresh" content="0; url=%s">\n' \
               '<script>location.replace(%s);</script>' \
               % (default_page, json.dumps(default_page))
        body = 'Loading the websim launcher… <a href="%s">continue</a>' % default_page
    else:
        head = ""
        body = "No websim projects were built. Run <code>make websim-all</code>."
    html = (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        "<title>logue-sdk websim</title>\n%s\n</head>\n<body>%s</body>\n</html>\n"
        % (head, body)
    )
    with open(os.path.join(sim_root, "index.html"), "w") as f:
        f.write(html)


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: gen_manifest.py <sim-root> [<repo-root>]")
    sim_root = sys.argv[1]
    repo_root = sys.argv[2] if len(sys.argv) > 2 else "."

    devices = collect_devices(sim_root, repo_root)
    with open(os.path.join(sim_root, "projects.json"), "w") as f:
        json.dump({"devices": devices}, f, indent=2)
        f.write("\n")

    write_index(sim_root, pick_default(devices))

    n_projects = sum(len(d["projects"]) for d in devices)
    print("wrote %s (%d device(s), %d project(s))"
          % (os.path.join(sim_root, "projects.json"), len(devices), n_projects))


if __name__ == "__main__":
    main()
