"""Deck legality: pure functions over a list of cards, no database.

A card is a dict with name, quantity, board (main / side / commander / maybe), type_line, oracle_text, keywords,
color_identity and legalities (Scryfall's {format: legal | not_legal | banned | restricted}) and game_changer.
`check` returns {"problems": [{severity, card, rule, message}], "counts", "game_changers", "legal"}.
Cards on the `maybe` board are ignored. The `casual` format has no deck rules: only a reference format's per-card legality."""
import re

SIXTY = ("standard", "pioneer", "modern", "legacy", "vintage", "pauper")  # 60-card formats with a 15-card sideboard
_NUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}
_COPIES = re.compile(r"a deck can have (any number of|only one|up to (\w+)) cards? named", re.I)


def _problem(severity, card, rule, message):
    return {"severity": severity, "card": card, "rule": rule, "message": message}


def copy_limit(card: dict, default: int):
    """Copies of a card a deck may hold (None = any number): basic lands and "any number / up to N / only one" cards."""
    t = card.get("type_line") or ""
    if "Basic" in t and "Land" in t:
        return None
    m = _COPIES.search(card.get("oracle_text") or "")
    if not m:
        return default
    what = m.group(1).lower()
    return None if what == "any number of" else 1 if what == "only one" else _NUM.get(m.group(2).lower(), default)


def _front(card):
    return (card.get("type_line") or "").split(" // ")[0]


def _eligible_commander(card) -> bool:
    t = _front(card)
    return ("Legendary" in t and ("Creature" in t or "Vehicle" in t)) or "can be your commander" in (card.get("oracle_text") or "").lower()


def _pair_ok(a, b) -> bool:
    """Whether two different cards may be commanders together: Partner, Partner with, Friends forever, Background, Doctor."""
    if a["name"] == b["name"]:
        return False
    ka, kb = ({k.lower() for k in c.get("keywords") or []} for c in (a, b))
    ta, tb = ((c.get("oracle_text") or "").lower() for c in (a, b))
    plain = lambda k: "partner" in k and "partner with" not in k  # "Partner with" cards also list "Partner"
    if plain(ka) and plain(kb):
        return True
    if "partner with" in ka and "partner with" in kb and f"partner with {b['name'].lower()}" in ta and f"partner with {a['name'].lower()}" in tb:
        return True
    if "friends forever" in ta and "friends forever" in tb:
        return True
    for x, y, ky in ((a, b, ka), (b, a, kb)):
        if "choose a background" in ky and "Background" in (y.get("type_line") or ""):
            return True
        if "doctor's companion" in ky and "Doctor" in (y.get("type_line") or ""):
            return True
    return False


def _commanders(cs, problems) -> list:
    cmd = [c for c in cs if c["board"] == "commander"]
    heads = [c for c in cmd for _ in range(c["quantity"])]
    if not heads:
        problems.append(_problem("error", None, "commander", "Choose a commander"))
    elif len(heads) > 2:
        problems.append(_problem("error", None, "commander", f"A deck has at most 2 commanders, this one has {len(heads)}"))
    elif len(heads) == 2:
        if not _pair_ok(*heads):
            problems.append(_problem("error", None, "commander",
                                     f"{heads[0]['name']} and {heads[1]['name']} cannot be commanders together"))
    elif not _eligible_commander(heads[0]):
        problems.append(_problem("error", heads[0]["name"], "commander",
                                 f"{heads[0]['name']} cannot be a commander (a legendary creature, or says so)"))
    return cmd


def check(fmt: str, cards: list[dict], reference: str | None = None) -> dict:
    cs = [c for c in cards if c["board"] != "maybe"]
    problems = []
    counts = {b: sum(c["quantity"] for c in cs if c["board"] == b) for b in ("main", "side", "commander")}
    key = reference if fmt == "casual" else fmt
    named = {}
    for c in cs:
        named.setdefault(c["name"], []).append(c)

    for c in cs:  # per-card legality in the format
        status = (c.get("legalities") or {}).get(key) if key else None
        if status in ("banned", "not_legal"):
            problems.append(_problem("error", c["name"], status, f"{c['name']} is {status.replace('_', ' ')} in {key}"))

    if fmt != "casual":
        default = 1 if fmt == "commander" else 4
        for name, group in named.items():
            n = sum(c["quantity"] for c in group)
            limit = copy_limit(group[0], default)
            if (group[0].get("legalities") or {}).get(key) == "restricted":
                limit = 1 if limit is None else min(limit, 1)
            if limit is not None and n > limit:
                rule = "restricted" if (group[0].get("legalities") or {}).get(key) == "restricted" else "copies"
                problems.append(_problem("error", name, rule, f"{name}: {n} copies, at most {limit} allowed"))

    if fmt in SIXTY:
        if counts["main"] < 60:
            problems.append(_problem("error", None, "size", f"The main deck has {counts['main']} cards, at least 60 are needed"))
        elif counts["main"] > 60:
            problems.append(_problem("warning", None, "size", f"The main deck has {counts['main']} cards (60 is the minimum)"))
        if counts["side"] > 15:
            problems.append(_problem("error", None, "size", f"The sideboard has {counts['side']} cards, at most 15"))
        if counts["commander"]:
            problems.append(_problem("warning", None, "size", "This format has no commander"))
    elif fmt == "commander":
        total = counts["main"] + counts["commander"]
        if total != 100:
            problems.append(_problem("error", None, "size", f"The deck has {total} cards, exactly 100 are needed"))
        if counts["side"]:
            problems.append(_problem("error", None, "size", "Commander has no sideboard"))
        identity = {i for c in _commanders(cs, problems) for i in c.get("color_identity") or []}
        for c in cs:
            out = sorted(set(c.get("color_identity") or []) - identity)
            if c["board"] != "commander" and out:
                problems.append(_problem("error", c["name"], "color_identity",
                                         f"{c['name']} has {''.join(out)} outside the commander's colour identity"))

    return {"problems": problems, "counts": counts, "game_changers": sum(c["quantity"] for c in cs if c.get("game_changer")),
            "legal": not any(p["severity"] == "error" for p in problems)}
