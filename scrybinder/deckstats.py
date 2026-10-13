"""Deck statistics: pure functions over the cards of a deck (as `decks.cards` returns them).
Only the main deck and the commander board count; the sideboard and maybe board are left out."""
import re
from statistics import median

COLORS = "WUBRG"
BOARDS = ("main", "commander")
# primary type of a card (front face): the first of these found in its type line
TYPES = ("land", "creature", "planeswalker", "battle", "artifact", "enchantment", "instant", "sorcery")
PERMANENTS = {"creature", "planeswalker", "battle", "artifact", "enchantment"}
CURVE_MAX = 7  # the last bucket is 7 or more
WARN_PIPS = 0.15  # a colour with at least this share of the symbols ...
WARN_RATIO = 0.6  # ... and fewer than this fraction of that share in mana sources gets a warning


def primary_type(card: dict) -> str:
    t = (card.get("type_line") or "").split(" // ")[0].lower()
    return next((x for x in TYPES if x in t), "other")


def pips(mana_cost: str) -> dict:
    """Coloured symbols of a mana cost: a hybrid symbol counts for each of its colours, generic and Phyrexian parts do not."""
    out = {}
    for sym in re.findall(r"\{([^}]+)\}", mana_cost or ""):
        for part in sym.split("/"):
            if part in COLORS or part == "C":
                out[part] = out.get(part, 0) + 1
    return out


def _ordered(d: dict, keys=COLORS + "C") -> dict:
    return {k: d.get(k, 0) for k in keys}


def compute(cards: list[dict]) -> dict:
    cs = [c for c in cards if c["board"] in BOARDS]
    has_commander = any(c["board"] == "commander" for c in cs)
    totals = {b: sum(c["quantity"] for c in cards if c["board"] == b) for b in ("main", "side", "commander", "maybe")}
    types, tags, symbols, sources, land_sources = {}, {}, {}, {}, {}
    curve = {i: {"permanents": 0, "spells": 0} for i in range(CURVE_MAX + 1)}
    cmcs, spell_cmcs, price, identity, game_changers = [], [], 0.0, set(), 0
    for c in cs:
        q, kind = c["quantity"], primary_type(c)
        types[kind] = types.get(kind, 0) + q
        for t in c.get("tags") or []:
            tags[t] = tags.get(t, 0) + q
        for col, n in pips(c.get("mana_cost")).items():
            symbols[col] = symbols.get(col, 0) + n * q
        for col in c.get("produced_mana") or []:
            if col in COLORS or col == "C":
                sources[col] = sources.get(col, 0) + q
                if kind == "land":
                    land_sources[col] = land_sources.get(col, 0) + q
        cmc = int(c.get("cmc") or 0)
        cmcs += [cmc] * q
        if kind != "land":
            spell_cmcs += [cmc] * q
            curve[min(cmc, CURVE_MAX)]["permanents" if kind in PERMANENTS else "spells"] += q
        price += (c.get("price") or 0) * q
        game_changers += q if c.get("game_changer") else 0
        if c["board"] == "commander" or not has_commander:
            identity |= set(c.get("color_identity") or [])

    total_pips, total_src = sum(symbols.values()), sum(land_sources.get(k, 0) for k in COLORS) or 0
    warnings = []
    for col in COLORS:
        share = symbols.get(col, 0) / total_pips if total_pips else 0
        have = land_sources.get(col, 0) / total_src if total_src else 0
        if share >= WARN_PIPS and have < share * WARN_RATIO:
            warnings.append({"color": col, "pips_share": round(share, 2), "sources_share": round(have, 2)})

    return {
        "totals": totals,
        "curve": [{"cmc": i, **curve[i]} for i in range(CURVE_MAX + 1)],
        "cmc": {"average": round(sum(spell_cmcs) / len(spell_cmcs), 2) if spell_cmcs else 0,
                "median": median(spell_cmcs) if spell_cmcs else 0,
                "average_with_lands": round(sum(cmcs) / len(cmcs), 2) if cmcs else 0,
                "median_with_lands": median(cmcs) if cmcs else 0},
        "types": {t: types[t] for t in (*TYPES, "other") if t in types},
        "lands": types.get("land", 0),
        "pips": _ordered(symbols),
        "sources": _ordered(sources),
        "land_sources": _ordered(land_sources),
        "color_warnings": warnings,
        "tags": dict(sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))),
        "color_identity": [c for c in COLORS if c in identity],
        "game_changers": game_changers,
        "price": round(price, 2),
    }
