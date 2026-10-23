"""Parsers for official sanctions list files (local files only; namespace- and field-variation tolerant).

* CA-SEMA: Global Affairs Canada "Consolidated Canadian Autonomous Sanctions List" (SEMA + JVCFOA), sema-lmes.xml:
  <data-set><record> with Country (regime), Schedule, Item, DateOfListing, LastName, GivenName, Aliases,
  DateOfBirthOrShipBuildDate, EntityOrShip, TitleOrShip, ShipIMONumber. Field names are matched loosely
  (case/punctuation-insensitive, several known spellings) because the file has changed shape over time.
* UN: UN Security Council Consolidated List, consolidated.xml: <CONSOLIDATED_LIST dateGenerated=...> with
  <INDIVIDUALS><INDIVIDUAL> and <ENTITIES><ENTITY>.
* OFAC-SDN: US Treasury OFAC SDN list, sdn.xml: <sdnList> (namespace varies by publication) with <sdnEntry>.
Each parser returns {"source", "published", "entries": [{"uid", "kind", "name", "names", "dobs", "countries",
"programs", "listed_on", "low_quality_aliases"}]}."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from atlas.ledgers.banking.iso20022.common import XMLError, local, safe_parse

SOURCES = {"CA-SEMA": "Canada Consolidated Autonomous Sanctions List (SEMA/JVCFOA)",
           "UN": "UN Security Council Consolidated List", "OFAC-SDN": "OFAC Specially Designated Nationals"}
DEFAULT_FILES = {"CA-SEMA": "sema-lmes.xml", "UN": "un-consolidated.xml", "OFAC-SDN": "ofac-sdn.xml"}


def _key(tag: str) -> str:
    return re.sub(r"[^a-z]", "", local(tag).lower())


def _kids(e, *names):
    want = {re.sub(r"[^a-z]", "", n.lower()) for n in names}
    return [c for c in list(e) if _key(c.tag) in want]


def _t(e, *names) -> str:
    for c in _kids(e, *names):
        if c.text and c.text.strip():
            return " ".join(c.text.split())
    return ""


def _all_t(e, *names) -> list[str]:
    return [" ".join(c.text.split()) for c in _kids(e, *names) if c.text and c.text.strip()]


def _desc(e, name):
    k = re.sub(r"[^a-z]", "", name.lower())
    return [x for x in e.iter() if _key(x.tag) == k]


def _entry(uid, kind, name, aliases=(), dobs=(), countries=(), programs=(), listed_on="", low=()):
    names = []
    for n in [name, *aliases]:
        n = " ".join(str(n).split())
        if n and n not in names:
            names.append(n)
    return {"uid": str(uid), "kind": kind, "name": name, "names": names, "dobs": [d for d in dobs if d],
            "countries": sorted({c for c in countries if c}), "programs": sorted({p for p in programs if p}),
            "listed_on": listed_on, "low_quality_aliases": list(low)}


# ---------------------------------------------------------------- Canada (SEMA / JVCFOA)
def parse_sema(root) -> dict:
    records = [r for r in root.iter() if _key(r.tag) == "record"]
    out = []
    if not records:                                    # tolerate an <individual>/<entity> layout
        records = [r for r in root.iter() if _key(r.tag) in ("individual", "entity")]
    for r in records:
        last = _t(r, "LastName", "FamilyName", "Surname")
        given = _t(r, "GivenName", "GivenNames", "FirstName")
        ent = _t(r, "EntityOrShip", "Entity", "EntityName", "Name") if not (last or given) else ""
        imo = _t(r, "ShipIMONumber", "IMONumber")
        if not (last or given or ent):
            continue
        kind = "vessel" if imo else ("individual" if (last or given) else "entity")
        name = f"{given} {last}".strip() if (last or given) else ent
        raw_alias = _t(r, "Aliases", "Alias", "AKA") or ""
        aliases = [a.strip() for a in re.split(r"[;,|\n]", raw_alias) if a.strip()] + _all_t(r, "alias")[1:]
        if last and given:
            aliases.append(f"{last} {given}")
        country = _t(r, "Country", "Regime", "country")
        uid = f"{country}/{_t(r, 'Schedule')}/{_t(r, 'Item', 'ItemNumber')}".strip("/") or name
        out.append(_entry(uid, kind, name, aliases, [_t(r, "DateOfBirthOrShipBuildDate", "DateOfBirth", "DOB")],
                          [], [f"SEMA/JVCFOA {country}".strip()], _t(r, "DateOfListing", "ListedOn")))
    return {"source": "CA-SEMA", "published": root.get("date") or root.get("dateGenerated") or "", "entries": out}


# ---------------------------------------------------------------- UN
def _un_dobs(e):
    out = []
    for d in _desc(e, "INDIVIDUAL_DATE_OF_BIRTH"):
        v = _t(d, "DATE") or _t(d, "YEAR") or "-".join(x for x in (_t(d, "FROM_YEAR"), _t(d, "TO_YEAR")) if x)
        if v:
            out.append(v)
    return out


def parse_un(root) -> dict:
    out = []
    for e in _desc(root, "INDIVIDUAL"):
        name = " ".join(x for x in (_t(e, "FIRST_NAME"), _t(e, "SECOND_NAME"), _t(e, "THIRD_NAME"), _t(e, "FOURTH_NAME")) if x)
        good, low = [], []
        for a in _desc(e, "INDIVIDUAL_ALIAS"):
            n = _t(a, "ALIAS_NAME")
            if n:
                (low if _t(a, "QUALITY").lower() == "low" else good).append(n)
        countries = [_t(n, "VALUE") for n in _desc(e, "NATIONALITY")] + [_t(a, "COUNTRY") for a in _desc(e, "INDIVIDUAL_ADDRESS")]
        out.append(_entry(_t(e, "REFERENCE_NUMBER") or _t(e, "DATAID"), "individual", name, good, _un_dobs(e),
                          countries, [_t(e, "UN_LIST_TYPE")], _t(e, "LISTED_ON"), low))
    for e in _desc(root, "ENTITY"):
        name = _t(e, "FIRST_NAME") or _t(e, "NAME")
        good, low = [], []
        for a in _desc(e, "ENTITY_ALIAS"):
            n = _t(a, "ALIAS_NAME")
            if n:
                (low if _t(a, "QUALITY").lower() == "low" else good).append(n)
        countries = [_t(a, "COUNTRY") for a in _desc(e, "ENTITY_ADDRESS")]
        out.append(_entry(_t(e, "REFERENCE_NUMBER") or _t(e, "DATAID"), "entity", name, good, [], countries,
                          [_t(e, "UN_LIST_TYPE")], _t(e, "LISTED_ON"), low))
    return {"source": "UN", "published": root.get("dateGenerated", ""), "entries": out}


# ---------------------------------------------------------------- OFAC SDN
def parse_ofac(root) -> dict:
    out = []
    pub = ""
    for p in _desc(root, "publshInformation"):
        pub = _t(p, "Publish_Date")
    for e in _desc(root, "sdnEntry"):
        t = _t(e, "sdnType").lower()
        kind = "individual" if t == "individual" else "vessel" if t == "vessel" else "entity"
        name = " ".join(x for x in (_t(e, "firstName"), _t(e, "lastName")) if x)
        good, low = [], []
        for a in _desc(e, "aka"):
            n = " ".join(x for x in (_t(a, "firstName"), _t(a, "lastName")) if x)
            if n:
                (low if _t(a, "category").lower() == "weak" else good).append(n)
        dobs = [_t(d, "dateOfBirth") for d in _desc(e, "dateOfBirthItem")]
        countries = [_t(a, "country") for a in _desc(e, "address")] + [_t(n, "country") for n in _desc(e, "nationality")] + \
            [_t(n, "country") for n in _desc(e, "citizenship")]
        progs = [p.text.strip() for p in _desc(e, "program") if p.text]
        out.append(_entry(_t(e, "uid"), kind, name, good, dobs, countries, progs, "", low))
    return {"source": "OFAC-SDN", "published": pub, "entries": out}


def detect(root) -> str:
    k = _key(root.tag)
    if k == "dataset" or any(_key(c.tag) == "record" for c in list(root)[:3]):
        return "CA-SEMA"
    if k == "consolidatedlist":
        return "UN"
    if k == "sdnlist":
        return "OFAC-SDN"
    raise XMLError(f"unrecognised sanctions list format (root <{local(root.tag)}>)")


def parse_file(path: str | Path, expected_sha256: str | None = None) -> dict:
    b = Path(path).read_bytes()
    sha = hashlib.sha256(b).hexdigest()
    if expected_sha256 and sha != expected_sha256:
        raise XMLError(f"{Path(path).name}: sha256 does not match the download manifest (file changed after download)")
    root = safe_parse(b)
    src = detect(root)
    doc = {"CA-SEMA": parse_sema, "UN": parse_un, "OFAC-SDN": parse_ofac}[src](root)
    if not doc["entries"]:
        raise XMLError(f"{Path(path).name}: no entries parsed ({src}); refusing to load an empty list")
    doc.update(sha256=sha, file=Path(path).name, bytes=len(b))
    return doc


def parse_dir(directory: str | Path) -> list[dict]:
    """Parse every *.xml in a directory, verifying sha256 against manifest.json when present."""
    d = Path(directory)
    manifest = {}
    if (d / "manifest.json").exists():
        manifest = {f["file"]: f["sha256"] for f in json.loads((d / "manifest.json").read_text()).get("files", [])}
    docs = [parse_file(p, manifest.get(p.name)) for p in sorted(d.glob("*.xml"))]
    if not docs:
        raise FileNotFoundError(f"no sanctions list XML files in {d}")
    return docs


SAMPLE_DIR = Path(__file__).resolve().parent / "sample_lists"
