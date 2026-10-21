import pytest

from scrybinder import collection, decks, trades


def _cards(db):
    return [r[0] for r in db.execute("SELECT id FROM cards WHERE id != 'dfc-1' ORDER BY id LIMIT 2")]


def _qty(db, sid, **kw):
    return db.execute("SELECT COALESCE(SUM(quantity),0) FROM collection WHERE scryfall_id=? AND proxy=0", (sid,)).fetchone()[0]


def test_draft_changes_nothing_and_confirm_moves_copies(db):
    a, b = _cards(db)
    row = collection.add(db, scryfall_id=a, quantity=3, location="Box")
    t = trades.create(db, "Rui", "at the shop", 2)
    trades.add_out(db, t, row, 2)
    trades.add_in(db, t, b, 4, finish="foil")
    assert _qty(db, a) == 3 and _qty(db, b) == 0  # still a draft
    g = trades.get(db, t)
    assert g["out_cards"] == 2 and g["in_cards"] == 4
    assert (g["out_value"], g["in_value"], g["net"]) == (3.0, 12.0, 11.0)  # 2×1.50 out, 4×3.00 in, +2 cash
    assert g["out"][0]["available"] == 3
    trades.confirm(db, t)
    assert _qty(db, a) == 1 and _qty(db, b) == 4
    assert trades.get(db, t)["status"] == "done"


def test_full_row_leaves_and_incoming_merges_with_a_price(db):
    a, b = _cards(db)
    row = collection.add(db, scryfall_id=a, quantity=1)
    collection.add(db, scryfall_id=b, quantity=1, location="Bin")
    t = trades.create(db)
    trades.add_out(db, t, row)
    line = trades.add_in(db, t, b, 2, location="Bin", price=0.75)
    trades.confirm(db, t)
    assert _qty(db, a) == 0
    r = db.execute("SELECT quantity, purchase_price FROM collection WHERE scryfall_id=?", (b,)).fetchone()
    assert (r["quantity"], r["purchase_price"]) == (3, 0.75)
    assert line


def test_deck_held_copy_blocks_confirm_and_nothing_is_applied(db):
    a, b = _cards(db)
    oid = db.execute("SELECT oracle_id FROM cards WHERE id=?", (a,)).fetchone()[0]
    row = collection.add(db, scryfall_id=a, quantity=2)
    d = decks.create(db, "D")
    decks.assign(db, d, decks.add_card(db, d, oid, 1), [{"collection_id": row, "quantity": 1}])
    other = collection.add(db, scryfall_id=b, quantity=1)
    t = trades.create(db)
    trades.add_out(db, t, other)
    trades.add_out(db, t, row, 2)
    trades.add_in(db, t, b, 5)
    with pytest.raises(ValueError, match="only 1 free"):
        trades.confirm(db, t)
    assert _qty(db, a) == 2 and _qty(db, b) == 1
    assert trades.get(db, t)["status"] == "draft"


def test_proxy_and_done_trades_are_rejected(db):
    a, b = _cards(db)
    px = collection.add(db, scryfall_id=a, proxy=1)
    row = collection.add(db, scryfall_id=b)
    t = trades.create(db)
    with pytest.raises(ValueError, match="proxy"):
        trades.add_out(db, t, px)
    with pytest.raises(ValueError, match="no cards"):
        trades.confirm(db, t)
    trades.add_out(db, t, row)
    trades.confirm(db, t)
    for fn in (lambda: trades.add_out(db, t, row), lambda: trades.confirm(db, t)):
        with pytest.raises(ValueError, match="already done"):
            fn()
    trades.delete(db, t)  # history entry: the collection stays as it is
    assert _qty(db, b) == 0


def test_in_line_validation_and_duplicate_sum(db):
    a, _ = _cards(db)
    t = trades.create(db)
    with pytest.raises(ValueError):
        trades.add_in(db, t, a, 1, finish="etched")
    with pytest.raises(ValueError):
        trades.add_in(db, t, a, 0)
    i = trades.add_in(db, t, a, 1)
    assert trades.add_in(db, t, a, 2) == i
    assert trades.get(db, t)["in"][0]["quantity"] == 3
    trades.edit_line(db, t, "in", i, quantity=5, finish="foil")
    assert (trades.get(db, t)["in"][0]["quantity"], trades.get(db, t)["in"][0]["finish"]) == (5, "foil")
    trades.delete_line(db, t, "in", i)
    assert trades.get(db, t)["in"] == []


def test_done_trade_keeps_its_prices_and_rejects_non_text(db):
    a, b = _cards(db)
    row = collection.add(db, scryfall_id=a)
    t = trades.create(db)
    trades.add_out(db, t, row)
    with pytest.raises(ValueError, match="location"):
        trades.add_in(db, t, b, 1, location=5)
    trades.confirm(db, t)
    db.execute("UPDATE cards SET eur=9.0 WHERE id=?", (a,))  # the market moves afterwards
    assert trades.get(db, t)["out_value"] == 1.5


def test_untracked_card_goes_out_without_touching_the_collection(db):
    a, b = _cards(db)
    own = collection.add(db, scryfall_id=b)
    t = trades.create(db)
    x = trades.add_extra(db, t, a, 2, finish="foil")
    trades.add_out(db, t, own)
    g = trades.get(db, t)
    assert [l["untracked"] for l in g["out"]] == [1, 0] or [l["untracked"] for l in g["out"]] == [0, 1]
    assert g["out_value"] == 7.5  # 2 foil at 3.00 + 1 at 1.50
    trades.edit_line(db, t, "out", x, quantity=1, finish="nonfoil")
    trades.confirm(db, t)
    assert _qty(db, a) == 0 and _qty(db, b) == 0  # the untracked card was never in the collection
    assert trades.get(db, t)["traded_on"]


def test_trade_date(db):
    t = trades.create(db)
    trades.update(db, t, date="2026-09-30")
    assert trades.get(db, t)["traded_on"] == "2026-09-30"
    with pytest.raises(ValueError, match="date"):
        trades.update(db, t, date="yesterday")
