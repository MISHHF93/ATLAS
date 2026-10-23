#!/usr/bin/env python3
"""Download the official sanctions list files - RUN MANUALLY BY THE OWNER (this is the only networked piece of the
sanctions tooling, deliberately outside the payments package, which never does network I/O).

    python tools/fetch_sanctions_lists.py [--out var/sanctions] [--only CA-SEMA UN OFAC-SDN]
    atlas-payments sanctions-load var/sanctions        # then load them (local files only)

Writes each file plus manifest.json (url, sha256, bytes, fetched_at). The loader refuses files whose sha256 does not
match the manifest. Files are written atomically and only if they parse as XML with the expected root element, so a
captive-portal HTML page or a truncated download never replaces a good list. HTTPS only, certificate verification on,
no credentials needed (all three lists are public)."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

LISTS = {
    "CA-SEMA": ("https://www.international.gc.ca/world-monde/assets/office_docs/international_relations-relations_internationales/"
                "sanctions/sema-lmes.xml", "sema-lmes.xml", "data-set"),
    "UN": ("https://scsanctions.un.org/resources/xml/en/consolidated.xml", "un-consolidated.xml", "CONSOLIDATED_LIST"),
    "OFAC-SDN": ("https://sanctionslistservice.ofac.treas.gov/api/download/sdn.xml", "ofac-sdn.xml", "sdnList"),
}
MAX_BYTES = 200 * 1024 * 1024
UA = "atlas-sanctions-fetch/1.0 (manual owner download)"


def check_xml(data: bytes, root_name: str) -> None:
    if b"<!DOCTYPE" in data[:4096].upper() or b"<!ENTITY" in data.upper():
        raise ValueError("refusing XML with DOCTYPE/ENTITY declarations")
    root = ET.fromstring(data)
    got = root.tag.rsplit("}", 1)[-1]
    if got != root_name:
        raise ValueError(f"unexpected root element <{got}> (wanted <{root_name}>) - not the list file?")


def fetch(url: str, opener=urllib.request.urlopen, timeout: int = 120) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("HTTPS only")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/xml,text/xml"})
    with opener(req, timeout=timeout) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("download too large")
    return data


def run(out: Path, only: list[str] | None = None, opener=urllib.request.urlopen) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {"files": []}
    by_file = {f["file"]: f for f in manifest.get("files", [])}
    results = {}
    for src, (url, fname, root) in LISTS.items():
        if only and src not in only:
            continue
        try:
            data = fetch(url, opener)
            check_xml(data, root)
        except Exception as e:  # keep the previous good file
            results[src] = f"FAILED: {e}"
            continue
        tmp = out / (fname + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, out / fname)
        by_file[fname] = {"source": src, "file": fname, "url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                          "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        results[src] = f"ok {len(data)} bytes sha256={by_file[fname]['sha256'][:16]}..."
    manifest["files"] = sorted(by_file.values(), key=lambda f: f["file"])
    mpath.write_text(json.dumps(manifest, indent=2) + "\n")
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="var/sanctions")
    ap.add_argument("--only", nargs="*", choices=sorted(LISTS))
    a = ap.parse_args(argv)
    res = run(Path(a.out), a.only)
    for k, v in res.items():
        print(f"{k:9s} {v}")
    print(f"next: atlas-payments sanctions-load {a.out}")
    return 0 if all(v.startswith("ok") for v in res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
