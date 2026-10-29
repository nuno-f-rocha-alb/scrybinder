"""Matchups for a Pauper deck against the saved metagame (see pauper.py). Neither source publishes win rates, so this reads the cards instead:
what each archetype's main deck is made of (a share of graveyard cards, artifacts, fliers, burn, small creatures, a colour...), what its
sideboard brings in against you, and which cards answer which of those things. A card's `rel` against an archetype says how much of that
archetype it answers, from 0 (nothing) up; the numbers are estimates read from card text, good enough to rank, not to quote."""
import json
import re

from . import deckrules, decks, pauper, suggest

SIDE = 15  # a Pauper sideboard
NEED = 4.0  # copies of fully relevant cards that cover an archetype in the sideboard plan; more adds nothing
FLOOR = 0.15  # a covered archetype still counts a little, so the plan fills its slots instead of stopping
MARGIN = 1.5  # a card of yours is swapped only for one adding this many times as much
MAX_SWAPS = 6
REPEAT = 0.8
CAP = 1.5  # one copy counts for at most this much against an archetype, however many things it answers there
WEAK = 0.35  # a situational main-deck card under this against an archetype is a board-out candidate
LABEL = {"graveyard": "Graveyard", "artifact": "Artifacts", "enchantment": "Enchantments", "flying": "Fliers", "small": "Small creatures",
         "tokens": "Tokens", "burn": "Burn", "creature": "Creatures", "combo": "Combo", "counter": "Counterspells", "removal": "Removal",
         "lifegain": "Life gain", "discard": "Discard", "noncreature": "Non-creature spells"}
COLOR_NAME = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
for _k, _v in COLOR_NAME.items():
    LABEL[f"color:{_k}"] = _v.capitalize() + " cards"
# a share of the spells that counts as fully exposed to the thing that answers it
SAT = {"graveyard": 0.12, "artifact": 0.20, "enchantment": 0.15, "flying": 0.20, "small": 0.35, "tokens": 0.12, "burn": 0.20, "creature": 0.45, "combo": 1.0, "noncreature": 0.5}
SAT.update({f"color:{c}": 0.45 for c in COLOR_NAME})
ANSWERS_TO = {"combo": "Counters and discard", "creature": "Creature removal"}
ANSWERS_TO.update({f"color:{c}": f"Hosers for {n} cards" for c, n in COLOR_NAME.items()})
TRAITS = ("creature", "small", "flying", "artifact", "enchantment", "graveyard", "tokens", "burn", "counter", "removal", "lifegain", "discard", "noncreature")


def _r(p):
    return re.compile(p, re.I)


GRAVE = _r(r"flashback|escape|unearth|dredge|retrace|jump-start|\b(?:from|in) (?:your|a|any|target player's) graveyards?\b")
GRAVE_HATE = _r(r"exile (?:all |each )?graveyards|exile (?:all cards from |target card from |cards? from )?(?:target player's|each player's|all|a|that player's|an opponent's|opponent's) graveyards?"
                r"|from all graveyards|exile target card from a graveyard|exile (?:up to \w+ )?target cards? from (?!your )(?:a |target player's |their |an opponent's )?graveyards?")
BURN = _r(r"deals? (?:\d+|x) damage to (?:any target|target player|each opponent|target opponent|that player|target creature or player|any other target)|damage to any target")
COUNTER = _r(r"counter target")
REMOVAL = _r(r"(?:destroy|exile) target (?:\w+ ){0,3}(?:creature|permanent)|deals? (?:\d+|x) damage to target creature|damage to any target|target creature gets -|gets? -x/-x"
             r"|destroy all (?:\w+ )?creatures|sacrifices? (?:a|target) creature")
LIFE = _r(r"gain (?:\d+|x|twice|that much) life|you gain life")
FOG = _r(r"prevent all (?:combat )?damage that would be dealt (?:this turn|to (?:you|players))|prevent all damage that (?:a|sources)")
DISCARD = _r(r"(?:target player|each opponent|each player|target opponent) discards")
TOKENS = _r(r"creates? (?:[\w-]+ ){0,6}tokens?")
SWEEP = _r(r"damage to each (?:non\w+ )?creature|destroy all (?:\w+ )?creatures|(?:all|each) (?:other )?creatures? (?:you don't control )?gets? -\d+/-\d+|creatures you don't control get -\d+/-\d+")
ART_HATE = _r(r"(?:destroy|exile) (?:target|all|each|up to \w+ target)\b[^.]*\bartifacts?\b")
ENCH_HATE = _r(r"(?:destroy|exile) (?:target|all|each|up to \w+ target)\b[^.]*\benchantments?\b")
FLY_HATE = _r(r"creatures? with flying")
COLOR_HATE = _r(r"counter target (white|blue|black|red|green) spell|(?:destroy|exile) target (white|blue|black|red|green) (?:permanent|creature)|if it's (white|blue|black|red|green)"
                r"|target (white|blue|black|red|green) (?:permanent|creature|spell)")
_BY_NAME = {v: k for k, v in COLOR_NAME.items()}
_ANS: dict = {}  # oracle_id -> answers; card text does not change


def answers_to(tag: str) -> str:
    """How to call the cards that answer `tag`."""
    return ANSWERS_TO.get(tag) or f"Answers to {LABEL[tag].lower()}"


def _kw(row) -> set:
    return {k.lower() for k in json.loads(row["keywords"] or "[]")}


def answers(row) -> dict:
    """{tag: weight} of what a card answers when it is in the sideboard (or main deck)."""
    key = row["oracle_id"]
    if key in _ANS:
        return _ANS[key]
    text, kw, typ = row["oracle_text"] or "", _kw(row), row["type_line"] or ""
    out = {}
    if GRAVE_HATE.search(text):
        out["graveyard"] = 1.0
    if ART_HATE.search(text):
        out["artifact"] = 1.0
    if ENCH_HATE.search(text):
        out["enchantment"] = 1.0
    if FLY_HATE.search(text) and ("damage" in text or "destroy" in text or "exile" in text):
        out["flying"] = 1.0
    elif ("reach" in kw and "Creature" in typ) or re.search(r"gains? reach|and reach", text, re.I):
        out["flying"] = 0.6
    if SWEEP.search(text) or ("overload" in kw and "damage" in text):
        out["small"] = out["tokens"] = 1.0
    if FOG.search(text):
        out["burn"], out["creature"] = 1.0, 0.5
    elif LIFE.search(text) and "Creature" not in typ:
        out["burn"] = 0.4
    if re.search(r"deals? 1 damage to any target", text, re.I):  # a ping: no answer to a real creature, good against the small ones
        out["creature"], out["small"] = 0.4, 0.7
    elif REMOVAL.search(text) and "Creature" not in typ:
        out["creature"] = max(out.get("creature", 0), 1.0)
    if (COUNTER.search(text) and "Creature" not in typ) or (DISCARD.search(text) and "Creature" not in typ):
        out["combo"] = out["noncreature"] = 0.7
    colors = {c for m in COLOR_HATE.finditer(text) for g in m.groups() if g for c in [_BY_NAME[g.lower()]]}
    if colors:  # a hoser's "destroy target permanent / counter target spell" only works on its colour
        out.pop("creature", None)
        out.pop("combo", None)
        out.pop("noncreature", None)
    for c in colors:
        out[f"color:{c}"] = 1.0
    _ANS[key] = out
    return out


def traits(row) -> set:
    """What a card is, for the make-up of an archetype (lands are not counted by the caller)."""
    text, kw, typ = row["oracle_text"] or "", _kw(row), row["type_line"] or ""
    t = set()
    if "Creature" in typ:
        t.add("creature")
        if (row["cmc"] or 0) <= 2:
            t.add("small")
    if "flying" in kw:
        t.add("flying")
    if "Creature" not in typ:
        t.add("noncreature")
    if "Artifact" in typ:
        t.add("artifact")
    if "Enchantment" in typ:
        t.add("enchantment")
    if GRAVE.search(text) and "graveyard" not in answers(row):
        t.add("graveyard")
    if TOKENS.search(text):
        t.add("tokens")
    if BURN.search(text):
        t.add("burn")
    if COUNTER.search(text):
        t.add("counter")
    if REMOVAL.search(text):
        t.add("removal")
    if LIFE.search(text) or "lifelink" in kw:
        t.add("lifegain")
    if DISCARD.search(text):
        t.add("discard")
    for c in json.loads(row["colors"] or "[]"):
        t.add(f"color:{c}")
    return t


def profile(lines, rows) -> dict:
    """{tag: share of the non-land copies of the main deck that have it} plus avg_cmc."""
    copies, cmc, count = 0, 0.0, {}
    for it in lines:
        r = rows[it["oracle_id"]]
        if it["board"] != "main" or "Land" in (r["type_line"] or ""):
            continue
        copies += it["quantity"]
        cmc += (r["cmc"] or 0) * it["quantity"]
        for t in traits(r):
            count[t] = count.get(t, 0) + it["quantity"]
    return {"shares": {t: n / copies for t, n in count.items()} if copies else {}, "avg_cmc": round(cmc / copies, 2) if copies else 0.0, "spells": copies}


def style(name: str, cat: str, shares: dict, avg_cmc: float) -> tuple[str, bool]:
    """(style, estimated): the site's own category when it gives one, else a guess from the make-up and the name."""
    if cat:
        return {"Aggro": "aggro", "Control": "control", "Combo": "combo"}.get(cat, "midrange"), False
    if re.search(r"storm|combo|spy|synthesizer|cycle", name, re.I):
        return "combo", True
    if shares.get("counter", 0) >= 0.15:
        return "control", True
    if avg_cmc <= 2.4 and shares.get("creature", 0) + shares.get("burn", 0) >= 0.5:
        return "aggro", True
    return "midrange", True


def exposure(prof: dict, sty: str, tag: str) -> float:
    """How exposed an archetype is to what answers `tag`, 0 to 1."""
    share = 1.0 if tag == "combo" and sty == "combo" else 0.0 if tag == "combo" else prof["shares"].get(tag, 0.0)
    return min(1.0, share / SAT[tag])


def rel(ans: dict, prof: dict, sty: str) -> tuple[float, list]:
    """(how much of the archetype a card with these `answers` answers, the reasons as [(tag, exposure)])."""
    why = [(t, w * exposure(prof, sty, t)) for t, w in ans.items() if t in SAT]
    why = [(t, e) for t, e in why if e > 0]
    return sum(e for _, e in why), sorted(why, key=lambda x: -x[1])


_SELECT = "o.oracle_id, o.name, o.mana_cost, o.cmc, o.type_line, o.colors, o.color_identity, o.oracle_text, o.keywords, o.produced_mana"


def _load(db, oids) -> dict:
    oids, rows = list(oids), {}
    for k in range(0, len(oids), 400):
        mark = ",".join("?" * len(oids[k:k + 400]))
        rows.update({r["oracle_id"]: r for r in db.execute(f"SELECT {_SELECT} FROM oracle_cards o WHERE o.oracle_id IN ({mark})", oids[k:k + 400])})
    return rows


def _copies(row) -> int:
    return deckrules.copy_limit({"type_line": row["type_line"], "oracle_text": row["oracle_text"]}, 4) or 4


def analyse(db, deck_id: int, source: str, data_dir) -> dict:
    """The matchup picture of a Pauper deck against a source's saved metagame:
    {fetched, colors, deck:{shares, avg_cmc, spells}, labels, field:[archetype...], plan:[card...], cuts:[card...]}.
    Each archetype of `field` has its make-up (`shares`, `avg_cmc`, `style`), `expect` (the answers its lists bring, main and side), `threats`
    (what of your deck they hit), `board_in` / `board_out` (what to bring in and what could come out against it) and `cover` (how well your
    sideboard answers it). `plan` is a suggested sideboard of up to 15 cards chosen to cover the field by metagame share."""
    if decks._deck(db, deck_id)["format"] != "pauper":
        raise ValueError("the metagame is for Pauper decks")
    saved = pauper.load(source, data_dir)
    if not saved:
        return {"fetched": None, "colors": "", "deck": {"shares": {}, "avg_cmc": 0, "spells": 0}, "labels": LABEL, "field": [], "plan": [], "cuts": []}
    lists = pauper._resolved(db, saved)
    mine = [{"oracle_id": o, "board": b, "quantity": q} for o, b, q in db.execute(
        "SELECT oracle_id, board, SUM(quantity) FROM deck_cards WHERE deck_id=? AND board IN ('main','side') GROUP BY oracle_id, board", (deck_id,))]
    rows = _load(db, {it["oracle_id"] for ls in lists for it in ls} | {m["oracle_id"] for m in mine})
    identity = set()
    for m in mine:
        r = rows[m["oracle_id"]]
        if m["board"] == "main" and "Land" not in (r["type_line"] or ""):
            identity |= set(json.loads(r["color_identity"] or "[]"))
    deck_prof = profile(mine, rows)
    in_main = {m["oracle_id"]: m["quantity"] for m in mine if m["board"] == "main"}
    in_side = {m["oracle_id"]: m["quantity"] for m in mine if m["board"] == "side"}

    field = []
    for d, ls in zip(saved["decks"], lists):
        prof = profile(ls, rows)
        sty, est = style(d["name"], d["cat"], prof["shares"], prof["avg_cmc"])
        field.append({"id": d["id"], "name": d["name"], "meta": d["meta"], "colors": pauper._colors(ls, rows), "style": sty, "style_estimated": est,
                      "avg_cmc": prof["avg_cmc"], "shares": {t: round(s, 3) for t, s in prof["shares"].items()}, "_prof": prof, "_lines": ls})

    # what each archetype's lists bring against you (their main deck and sideboard), and what of your deck that hits
    def hates(ls):
        out = {}
        for it in ls:
            for t in answers(rows[it["oracle_id"]]):
                if t in SAT:
                    e = out.setdefault(t, {"main": 0, "side": 0, "cards": {}})
                    e[it["board"]] += it["quantity"]
                    e["cards"][rows[it["oracle_id"]]["name"]] = e["cards"].get(rows[it["oracle_id"]]["name"], 0) + it["quantity"]
        return out

    # the pool: pauper-legal cards that answer something and that the deck could play (its colours; lands in any deck)
    pool = {}
    for r in db.execute(f"SELECT {_SELECT} FROM oracle_cards o WHERE json_extract(o.legalities, '$.pauper') = 'legal'"):
        typ = r["type_line"] or ""
        if "Basic Land" in typ or not answers(r):
            continue
        if identity and "Land" not in typ and not set(json.loads(r["color_identity"] or "[]")) <= identity:
            continue
        pool[r["oracle_id"]] = r
    for oid in list(in_main) + list(in_side):
        if oid in rows and answers(rows[oid]):
            pool.setdefault(oid, rows[oid])
    room = {o: _copies(r) - in_main.get(o, 0) for o, r in pool.items()}  # copies still allowed in the sideboard
    have = suggest._have(db, list(pool))
    shown = {}  # cards that appear in the result, with their data

    def card(oid, **extra):
        if oid not in shown:
            r = pool.get(oid) or rows[oid]
            h = have.get(oid) or {"owned": 0, "assigned": 0, "print": None}
            shown[oid] = {"oracle_id": oid, "name": r["name"], "mana_cost": r["mana_cost"], "cmc": r["cmc"], "owned": h["owned"], "free": max(h["owned"] - h["assigned"], 0),
                          "image_id": h["print"] or suggest.newest_print(db, oid)}
        return {**shown[oid], **extra}

    def shown_name(oid):
        return (pool.get(oid) or rows[oid])["name"]

    relmat = {}  # (archetype index, oracle_id) -> (rel, why)
    for i, a in enumerate(field):
        for oid, r in pool.items():
            v, why = rel(answers(r), a["_prof"], a["style"])
            if v > 0:
                relmat[i, oid] = (v, why)

    def reasons(why, limit=3):
        return [{"tag": t, "label": LABEL[t], "exposure": round(e, 2)} for t, e in why[:limit]]

    for i, a in enumerate(field):
        h = hates(a["_lines"])
        a["expect"] = sorted(({"tag": t, "label": answers_to(t), "main": e["main"], "side": e["side"], "cards": [{"name": n, "quantity": q} for n, q in sorted(e["cards"].items())]}
                              for t, e in h.items() if t != "creature" or e["side"]), key=lambda x: -(x["side"] * 2 + x["main"]))
        threats = []
        for t, e in h.items():
            mine_share = deck_prof["shares"].get(t, 0.0)
            if mine_share > 0 and t not in ("creature", "combo") and (e["main"] + e["side"]):
                threats.append({"tag": t, "label": LABEL[t], "your_share": round(mine_share, 2), "their_main": e["main"], "their_side": e["side"],
                                "cards": [{"name": n, "quantity": q} for n, q in sorted(e["cards"].items())]})
        a["threats"] = sorted(threats, key=lambda x: -(x["your_share"] * (x["their_side"] + x["their_main"])))
        ranked = sorted(((v, oid) for (j, oid), (v, _) in relmat.items() if j == i and room[oid] > 0), key=lambda x: (-x[0], have[x[1]]["owned"] == 0, x[1]))
        a["board_in"] = [card(oid, rel=round(v, 2), copies=min(room[oid], 4 if v >= 1.0 else 2 if v >= 0.6 else 1), in_side=in_side.get(oid, 0),
                              reasons=reasons(relmat[i, oid][1])) for v, oid in ranked[:8]]
        out = []
        for oid, q in in_main.items():
            r = rows[oid]
            if answers(r):
                v, _ = rel(answers(r), a["_prof"], a["style"])
                if v < WEAK:
                    out.append(card(oid, quantity=q, rel=round(v, 2)))
        a["board_out"] = sorted(out, key=lambda x: (x["rel"], x["name"]))
        a["cover"] = round(sum(q * min(relmat.get((i, oid), (0, 0))[0], CAP) for oid, q in in_side.items()), 2)

    # the sideboard plan. Your sideboard is where it starts: empty slots get the best card for the field, and a card of yours is swapped only for
    # one that adds MARGIN times as much, each archetype needing less the better it is covered. A card whose text was not understood stays.
    sparse: dict = {}
    for (i, oid), (v, _) in relmat.items():
        sparse.setdefault(oid, []).append((i, min(v, CAP)))
    metas = [a["meta"] for a in field]
    plan_q = dict(in_side)
    got = [0.0] * len(field)

    def move(oid, step):
        plan_q[oid] = plan_q.get(oid, 0) + step
        for i, v in sparse.get(oid, ()):
            got[i] += step * v

    def worth(oid, n):  # what the n-th copy of `oid` adds on top of what is covered
        g = sum(metas[i] * v * max(FLOOR, 1 - got[i] / NEED) for i, v in sparse.get(oid, ()))
        return g * (1.1 if have[oid]["owned"] else 1.0) * REPEAT ** n if oid in have else 0.0

    def best_new(skip=None):
        best, best_gain = None, 0.0
        for oid in pool:
            if oid == skip or plan_q.get(oid, 0) >= max(room[oid], in_side.get(oid, 0)):
                continue
            g = worth(oid, plan_q.get(oid, 0))
            if g > best_gain or (g == best_gain and best is not None and g > 0 and oid < best):
                best, best_gain = oid, g
        return best, best_gain

    for oid, q in in_side.items():
        for i, v in sparse.get(oid, ()):
            got[i] += q * v
    while sum(plan_q.values()) < SIDE:
        b, g = best_new()
        if b is None or g < 1e-6:
            break
        move(b, 1)
    swaps, removed = [], {}
    for _ in range(MAX_SWAPS):
        pair = None
        for o in in_side:
            if removed.get(o, 0) >= in_side[o] or plan_q.get(o, 0) <= 0 or o not in pool:
                continue  # not a card of yours still in the plan, or one whose text was not understood
            move(o, -1)
            loss = worth(o, plan_q.get(o, 0))
            b, g = best_new(skip=o)
            move(o, 1)
            if b is not None and g >= MARGIN * loss and g > 0 and (pair is None or g - loss > pair[0]):
                pair = (g - loss, o, b)
        if pair is None:
            break
        _, o, b = pair
        move(o, -1)
        move(b, 1)
        removed[o] = removed.get(o, 0) + 1
        swaps.append((o, b))
    replaces: dict = {}
    for o, b in swaps:
        replaces.setdefault(b, []).append(shown_name(o))
    plan = []
    for oid, q in plan_q.items():
        if q <= 0:
            continue
        helps = sorted(((metas[i] * v, field[i]["name"]) for i, v in sparse.get(oid, ())), reverse=True)[:3]
        plan.append(card(oid, quantity=q, in_side=in_side.get(oid, 0), helps=[n for _, n in helps], replaces=replaces.get(oid, [])))
    plan.sort(key=lambda c: (c["in_side"] >= c["quantity"], -c["quantity"], c["name"]))  # the new cards first
    cuts = [card(oid, quantity=q - plan_q.get(oid, 0)) for oid, q in in_side.items() if plan_q.get(oid, 0) < q]
    for a in field:
        del a["_prof"], a["_lines"]
    return {"fetched": saved["fetched"], "colors": "".join(c for c in "WUBRG" if c in identity),
            "deck": {"shares": {t: round(s, 3) for t, s in deck_prof["shares"].items()}, "avg_cmc": deck_prof["avg_cmc"], "spells": deck_prof["spells"]},
            "labels": LABEL, "field": field, "plan": plan, "cuts": cuts}
