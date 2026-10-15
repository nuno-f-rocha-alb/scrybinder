"""Deck lists as plain text: `[N][x] Name [(SET) number] [*F*|*E*] [#tag] [^Tag^]` (*F* foil, *E* etched), compatible with Moxfield / Archidekt / MTGO.
Sections are headers (Commander, Deck, Sideboard, Maybeboard) or, without any header, blank-line blocks (main, then side)."""
import json
import re
import unicodedata

from . import decks

_HEADER = re.compile(r"^(commander|deck|main(?:board| deck)?|side(?:board)?|companion|maybe(?:board)?)s?\s*(?:\(\d+\))?\s*:?$", re.I)
_BOARD = {"commander": "commander", "deck": "main", "main": "main", "mainboard": "main", "main deck": "main", "side": "side",
          "sideboard": "side", "companion": "side", "maybe": "maybe", "maybeboard": "maybe"}
_LINE = re.compile(r"^(?:(\d+)\s*[xX]?\s+)?(.+)$")
_PRINTING = re.compile(r"\(([A-Za-z0-9]{2,6})\)\s*([\w★†-]+)?\s*$")
_FOIL = re.compile(r"\*[A-Za-z]\*")
MAX_LINES = 2000


def parse(text: str) -> list[dict]:
    """Lines of a deck list: {line, text, board, quantity, name, set, number, finish, tags}. Blank and comment lines are dropped."""
    lines = text.lstrip("﻿").splitlines()
    headers = any(_HEADER.match(l.strip()) for l in lines)
    out, board, blocks, seen = [], "main", 0, False
    for i, raw in enumerate(lines, start=1):
        s = raw.strip()
        if not s:
            if not headers and seen and board == "main" and blocks == 0:  # MTGO style: a blank line starts the sideboard
                board, blocks, seen = "side", 1, False
            continue
        if s.startswith(("//", "#")):
            continue
        m = _HEADER.match(s)
        if m:
            board, seen = _BOARD[m.group(1).lower()], False
            continue
        line_board = board
        if s[:3].upper() == "SB:":
            line_board, s = "side", s[3:].strip()
        tags = [t.strip().lower() for t in re.findall(r"\^([^^]+)\^", s)] + [t.lower() for t in re.findall(r"(?<!\S)#([\w-]+)", s)]
        s = re.sub(r"\^[^^]+\^|(?<!\S)#[\w-]+|\[[^\]]*\]", " ", s)
        fm = _FOIL.search(s)
        finish = {"f": "foil", "e": "etched"}.get(fm.group(0)[1].lower()) if fm else None
        s = _FOIL.sub(" ", s).strip()
        m = _LINE.match(s)
        qty, rest = m.groups() if m else (None, "")
        pm = _PRINTING.search(rest)
        name = (rest[:pm.start()] if pm else rest).strip()
        out.append({"line": i, "text": raw.strip(), "board": line_board, "quantity": int(qty) if qty else 1, "name": name,
                    "set": pm.group(1).lower() if pm else None, "number": pm.group(2) if pm else None, "finish": finish, "tags": tags})
        seen = True
    return out


def _norm(name: str) -> str:
    return unicodedata.normalize("NFKD", name.replace("’", "'")).encode("ascii", "ignore").decode().casefold().strip()


def _names(db) -> dict:
    """normalised name -> oracle_id; the front face of a double-faced card works too (the full name wins on a clash)."""
    names = {}
    for oid, name in db.execute("SELECT oracle_id, name FROM oracle_cards"):
        names[_norm(name)] = oid
    for oid, name in db.execute("SELECT oracle_id, name FROM oracle_cards WHERE name LIKE '% // %'"):
        for part in name.split(" // "):
            names.setdefault(_norm(part), oid)
    return names


def resolve(db, items: list[dict]) -> tuple[list[dict], list[dict]]:
    """(resolved, skipped): each resolved item gets oracle_id and scryfall_id (the printing, when set and number match);
    its finish stays only when that printing comes in it."""
    names, ok, skipped = _names(db), [], []
    for it in items:
        bad = None
        if not it["name"]:
            bad = "no card name"
        elif it["quantity"] < 1:
            bad = "quantity must be at least 1"
        else:
            try:
                decks._tags(it["tags"])
            except ValueError as e:
                bad = str(e)
        if bad:
            skipped.append({"line": it["line"], "text": it["text"], "reason": bad})
            continue
        oid = sid = None
        if it["set"] and it["number"]:
            for num in dict.fromkeys((it["number"], it["number"].lstrip("0"))):
                row = db.execute("SELECT c.id, c.oracle_id FROM cards c JOIN oracle_cards o ON o.oracle_id = c.oracle_id"
                                 " WHERE c.set_code=? AND c.collector_number=? LIMIT 1", (it["set"], num)).fetchone()
                if row:
                    sid, oid = row["id"], row["oracle_id"]
                    break
        by_name = names.get(_norm(it["name"]))
        if oid is None or (by_name is not None and by_name != oid):  # no such printing, or it is another card: trust the name
            oid, sid = by_name, None
        if oid is None:
            skipped.append({"line": it["line"], "text": it["text"], "reason": f"unknown card: {it['name']}"})
            continue
        finish = it.get("finish")
        if finish and sid:
            fin = db.execute("SELECT finishes FROM cards WHERE id=?", (sid,)).fetchone()
            finish = finish if fin and finish in json.loads(fin["finishes"] or "[]") else None
        ok.append({**it, "oracle_id": oid, "scryfall_id": sid, "finish": finish if sid else None})
    return ok, skipped


def import_text(db, deck_id: int, text: str, dry_run: bool = False) -> dict:
    """Add the cards of a list to a deck. `dry_run` only reports. Returns {lines, cards, skipped}."""
    decks._deck(db, deck_id)
    items = parse(text)
    if len(items) > MAX_LINES:
        raise ValueError(f"a deck list has at most {MAX_LINES} lines")
    ok, skipped = resolve(db, items)
    if not dry_run:
        for it in ok:
            decks.add_card(db, deck_id, it["oracle_id"], it["quantity"], it["board"], it["scryfall_id"], it["tags"], it["finish"])
    return {"lines": len(ok) + len(skipped), "cards": sum(i["quantity"] for i in ok), "skipped": skipped,
            "preview": [{"line": i["line"], "board": i["board"], "quantity": i["quantity"], "name": i["name"]} for i in ok]}


def export_text(db, deck_id: int, maybe: bool = False) -> str:
    """`N Name (SET) number [*F*|*E*] [#tag]` per card, in Commander / Deck / Sideboard (/ Maybeboard) sections."""
    decks._deck(db, deck_id)
    printings = {r[0]: (r[1], r[2]) for r in db.execute(
        "SELECT c.id, c.set_code, c.collector_number FROM cards c WHERE c.id IN"
        " (SELECT scryfall_id FROM deck_cards WHERE deck_id=? AND scryfall_id IS NOT NULL)", (deck_id,))}
    sections = {"commander": [], "main": [], "side": [], "maybe": []}
    for c in decks.cards(db, deck_id):
        line = f"{c['quantity']} {c['name']}"
        if c["scryfall_id"] in printings:
            line += " ({}) {}".format(printings[c["scryfall_id"]][0].upper(), printings[c["scryfall_id"]][1])
            line += {"foil": " *F*", "etched": " *E*"}.get(c["finish"], "")
        sections[c["board"]].append(line + "".join(f" ^{t}^" if " " in t else f" #{t}" for t in c["tags"]))
    titles = (("commander", "Commander"), ("main", "Deck"), ("side", "Sideboard"), ("maybe", "Maybeboard"))
    return "\n\n".join(f"{t}\n" + "\n".join(sections[b]) for b, t in titles if sections[b] and (b != "maybe" or maybe)) + "\n"
