"""Name normalisation and fuzzy matching (pure Python): Jaro-Winkler on the full string, on sorted tokens, and a
token-set alignment (handles reordered names, missing middle names, initials). Secondary keys (date of birth,
country, party type) adjust the score and are reported as reasons."""
from __future__ import annotations

import re
import unicodedata

STOP = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "gen", "general", "col", "colonel", "maj", "major", "capt",
        "haji", "hajji", "sheikh", "shaykh", "mullah", "the", "of", "and", "al", "el", "bin", "ibn", "bint", "abu",
        "ltd", "limited", "llc", "inc", "incorporated", "corp", "corporation", "co", "company", "plc", "gmbh", "ag",
        "sa", "sarl", "srl", "bv", "nv", "jsc", "pjsc", "ojsc", "cjsc", "ao", "pao", "ooo", "oao", "zao", "llp", "lp"}
GENERIC = {"holding", "holdings", "group", "bank", "banking", "trading", "trade", "traders", "company", "international", "intl",
           "investment", "investments", "invest", "capital", "shipping", "industries", "industrial", "industry", "enterprise",
           "enterprises", "services", "service", "global", "energy", "oil", "gas", "petroleum", "finance", "financial",
           "management", "partners", "fund", "foundation", "organization", "organisation", "development", "technology",
           "technologies", "tech", "import", "export", "logistics", "marine", "maritime", "construction", "engineering",
           "airlines", "air", "aviation", "commercial", "national", "united", "new", "north", "south", "east", "west",
           "center", "centre", "general", "solutions", "consulting", "resources", "mining", "metals", "products", "systems"}
GENERIC_W = 0.25
TOKEN_FLOOR = 0.84          # token similarity below this counts as no match (stops long shared prefixes carrying a name)
TRANSLIT = str.maketrans({"ß": "ss", "æ": "ae", "ø": "o", "đ": "d", "ł": "l", "þ": "th", "œ": "oe", "ı": "i"})


def normalise(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "").lower().translate(TRANSLIT))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def tokens(name: str) -> list[str]:
    toks = normalise(name).split()
    kept = [t for t in toks if t not in STOP]
    return kept or toks


def jaro(a: str, b: str) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    win = max(la, lb) // 2 - 1
    ma, mb = [False] * la, [False] * lb
    m = 0
    for i, ch in enumerate(a):
        for j in range(max(0, i - win), min(lb, i + win + 1)):
            if not mb[j] and b[j] == ch:
                ma[i] = mb[j] = True
                m += 1
                break
    if not m:
        return 0.0
    t, k = 0, 0
    for i in range(la):
        if ma[i]:
            while not mb[k]:
                k += 1
            t += a[i] != b[k]
            k += 1
    return (m / la + m / lb + (m - t / 2) / m) / 3


def jaro_winkler(a: str, b: str, p: float = 0.1) -> float:
    j = jaro(a, b)
    pre = 0
    for x, y in zip(a[:4], b[:4]):
        if x != y:
            break
        pre += 1
    return j + pre * p * (1 - j)


def _tok_sim(x: str, y: str) -> float:
    if len(x) == 1 or len(y) == 1:                      # initials
        return 0.75 if x[0] == y[0] else 0.0
    ratio = min(len(x), len(y)) / max(len(x), len(y))    # JW over-rewards a short prefix ("north" vs "northwind")
    return jaro_winkler(x, y) * min(1.0, 0.5 + 0.5 * ratio / 0.8)


def _w(t: str) -> float:
    return GENERIC_W if t in GENERIC else 1.0


def token_set(a: list[str], b: list[str]) -> float:
    """Align the shorter token list onto the longer (greedy best match per token); weighted average similarity
    (generic corporate words count 1/4), tokens below TOKEN_FLOOR count as 0, penalised for unmatched tokens."""
    if not a or not b:
        return 0.0
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    used: set[int] = set()
    tot = wsum = 0.0
    for t in short:
        best, bi = 0.0, None
        for i, u in enumerate(long_):
            if i in used:
                continue
            s = _tok_sim(t, u)
            if s > best:
                best, bi = s, i
        if bi is not None:
            used.add(bi)
        w = _w(t)
        tot += w * (best if best >= TOKEN_FLOOR else 0.0)
        wsum += w
    avg = tot / wsum
    cov = sum(_w(t) for t in short) / sum(_w(t) for t in long_)
    if len(short) == 1 and len(long_) > 1:              # single-token name vs multi-token name: weak evidence
        return avg * 0.75
    return avg * (0.85 + 0.15 * min(cov, 1.0))


def name_score(a: str, b: str) -> float:
    return name_score_tokens(tokens(a), tokens(b))


def name_score_tokens(ta: list[str], tb: list[str], floor: float = 0.0) -> float:
    if not ta or not tb:
        return 0.0
    score = token_set(ta, tb)
    if len(ta) == len(tb) or score < floor - 0.5:     # merges only matter for differing token counts
        return round(score, 4)
    for x, y in ((ta, tb), (tb, ta)):                   # spacing variants: "North Wind" vs "Northwind"
        for i in range(len(x) - 1):
            merged = x[:i] + [x[i] + x[i + 1]] + x[i + 2:]
            score = max(score, token_set(merged, y) * 0.97)
    return round(score, 4)


def block_keys(name: str) -> set[str]:
    """Candidate-blocking keys: 3-char prefixes of each token (+ first letter for very short tokens)."""
    return {t[:3] for t in tokens(name) if len(t) >= 2}


def years(dobs) -> set[int]:
    out = set()
    for d in dobs or []:
        for m in re.findall(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)", str(d)):
            out.add(int(m))
    return out


def score_entry(subject: dict, entry: dict) -> tuple[float, str, list[str]]:
    """subject: {"name", "dob", "country", "kind"}; entry: {"names": [...], "dobs": [...], "countries": [...], "kind"}.
    Returns (score, best matching listed name, reasons)."""
    best, best_name = 0.0, ""
    st = subject.get("tokens") or tokens(subject["name"])
    for n, et in zip(entry["names"], entry.get("tokens") or [tokens(n) for n in entry["names"]]):
        s = name_score_tokens(st, et, 0.88)
        if s > best:
            best, best_name = s, n
    reasons = [f"name {best:.2f} vs '{best_name}'"]
    sy, ey = years([subject.get("dob")]), years(entry.get("dobs"))
    if sy and ey:
        if sy & ey:
            best = min(1.0, best + 0.03)
            reasons.append("birth year matches")
        elif min(abs(a - b) for a in sy for b in ey) > 1:
            best -= 0.10
            reasons.append("birth year differs")
    sc = (subject.get("country") or "").upper()
    ecs = {c.upper() for c in entry.get("countries") or [] if len(c) == 2}     # lists mostly use country names
    if sc and ecs:
        if sc in ecs:
            reasons.append(f"country {sc} matches")
        else:
            reasons.append("country differs")
    sk, ek = subject.get("kind"), entry.get("kind")
    if sk and ek and ((sk == "individual") != (ek == "individual")):
        best -= 0.05
        reasons.append(f"party type differs ({sk} vs {ek})")
    return round(max(best, 0.0), 4), best_name, reasons
