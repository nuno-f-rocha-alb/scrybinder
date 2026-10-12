"""Import ManaBox; export ManaBox / Moxfield / Cardmarket. Everything derives from the stored scryfall_id."""
import csv
import io

from . import collection

_COND_IN = {"near_mint": "NM", "lightly_played": "LP", "moderately_played": "MP", "heavily_played": "HP",
            "damaged": "DMG"}
_COND_MB = {v: k for k, v in _COND_IN.items()}
_FINISH_IN = {"normal": "nonfoil", "foil": "foil", "etched": "etched"}
_FINISH_MB = {v: k for k, v in _FINISH_IN.items()}
_COND_MOX = {"NM": "Near Mint", "LP": "Good (Lightly Played)", "MP": "Played", "HP": "Heavily Played",
             "DMG": "Damaged"}
# Cardmarket: NM/EX/GD/LP/PL/PO. ponytail: approximate MTG->Cardmarket mapping, adjustable here.
_COND_CM = {"NM": "NM", "LP": "EX", "MP": "GD", "HP": "PL", "DMG": "PO"}
_LANG_CM = {"en": 1, "fr": 2, "de": 3, "es": 4, "it": 5, "zhs": 6, "ja": 7, "pt": 8, "ru": 9, "ko": 10, "zht": 11}

MANABOX_COLS = ["Name", "Set code", "Set name", "Collector number", "Foil", "Rarity", "Quantity", "ManaBox ID",
                "Scryfall ID", "Purchase price", "Misprint", "Altered", "Signed", "Condition", "Language", "Proxy",
                "Purchase price currency", "Added"]
_B = lambda v: "true" if v else "false"  # noqa: E731


def import_manabox(db, text: str, location: str = "") -> dict:
    """Returns {imported, cards, skipped:[(line, reason)]}. Unknown ids (missing bulk data) are skipped."""
    rd = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    missing = {"Scryfall ID", "Quantity"} - set(rd.fieldnames or [])
    if missing:
        raise ValueError(f"This does not look like a ManaBox CSV (missing columns: {', '.join(sorted(missing))})")
    known = {r[0] for r in db.execute("SELECT id FROM cards")}
    out = {"imported": 0, "cards": 0, "skipped": []}
    with db:
        for i, r in enumerate(rd, start=2):
            sid = (r.get("Scryfall ID") or "").strip()
            if sid not in known:
                out["skipped"].append((i, f"{r.get('Name', '?')}: scryfall_id not in the database (update the bulk data)"))
                continue
            try:
                q = int(r["Quantity"])
                price = float(r["Purchase price"]) if r.get("Purchase price") else None
                collection.add(
                    db, scryfall_id=sid, quantity=q, location=location,
                    finish=_FINISH_IN.get(r.get("Foil", "normal"), "nonfoil"),
                    condition=_COND_IN.get(r.get("Condition", "near_mint"), "NM"),
                    language=(r.get("Language") or "en"),
                    altered=r.get("Altered") == "true", signed=r.get("Signed") == "true",
                    misprint=r.get("Misprint") == "true", proxy=r.get("Proxy") == "true",
                    purchase_price=price, purchase_currency=r.get("Purchase price currency") or "EUR",
                    manabox_id=int(r["ManaBox ID"]) if r.get("ManaBox ID") else None,
                    added_at=(r.get("Added") or None))
            except (ValueError, KeyError) as e:
                out["skipped"].append((i, f"{r.get('Name', '?')}: {e}"))
                continue
            out["imported"] += 1
            out["cards"] += q
    return out


def _rows(db, location):
    sql = ("SELECT c.*, k.name, k.set_code, k.set_name, k.collector_number, k.rarity, k.cardmarket_id,"
           " k.eur, k.eur_foil, k.eur_etched FROM collection c JOIN cards k ON k.id=c.scryfall_id")
    args = []
    if location is not None:
        sql += " WHERE c.location=?"
        args.append(location)
    return db.execute(sql + " ORDER BY k.name, k.set_code", args).fetchall()


def _csv(cols, rows) -> str:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    w.writerows(rows)
    return buf.getvalue()


def export_manabox(db, location=None) -> str:
    return _csv(MANABOX_COLS, [
        [r["name"], r["set_code"].upper(), r["set_name"], r["collector_number"], _FINISH_MB[r["finish"]],
         r["rarity"], r["quantity"], r["manabox_id"] if r["manabox_id"] is not None else "", r["scryfall_id"],
         "" if r["purchase_price"] is None else str(r['purchase_price']), _B(r["misprint"]), _B(r["altered"]),
         _B(r["signed"]), _COND_MB[r["condition"]], r["language"], _B(r["proxy"]), r["purchase_currency"] or "EUR",
         r["added_at"]] for r in _rows(db, location)])


def export_moxfield(db, location=None) -> str:
    cols = ["Count", "Tradelist Count", "Name", "Edition", "Condition", "Language", "Foil", "Tags",
            "Last Modified", "Collector Number", "Alter", "Proxy", "Purchase Price"]
    return _csv(cols, [
        [r["quantity"], 0, r["name"], r["set_code"], _COND_MOX[r["condition"]], r["language"],
         "" if r["finish"] == "nonfoil" else r["finish"], r["location"], r["added_at"], r["collector_number"],
         "True" if r["altered"] else "", "True" if r["proxy"] else "",
         "" if r["purchase_price"] is None else f"{r['purchase_price']:.2f}"] for r in _rows(db, location)])


def export_cardmarket(db, location=None) -> str:
    """Cardmarket stock list. Rows without a cardmarket_id cannot be exported and are left out."""
    cols = ["cardmarketId", "quantity", "name", "set", "setCode", "cn", "condition", "language", "isFoil",
            "isPlayset", "isSigned", "price", "comments"]
    rows = []
    for r in _rows(db, location):
        if not r["cardmarket_id"] or r["language"] not in _LANG_CM:  # no id or unmapped language: omit rather than export wrongly
            continue
        cur = {"foil": r["eur_foil"], "etched": r["eur_etched"]}.get(r["finish"], r["eur"])
        rows.append([r["cardmarket_id"], r["quantity"], r["name"], r["set_name"], r["set_code"].upper(),
                     r["collector_number"], _COND_CM[r["condition"]], _LANG_CM[r["language"]],
                     "true" if r["finish"] != "nonfoil" else "false", "false", _B(r["signed"]),
                     "" if cur is None else f"{cur:.2f}", r["notes"]])
    return _csv(cols, rows)


EXPORTERS = {"manabox": export_manabox, "moxfield": export_moxfield, "cardmarket": export_cardmarket}
