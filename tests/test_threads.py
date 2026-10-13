from concurrent.futures import ThreadPoolExecutor

from scrybinder import db as dbmod


def test_one_connection_serves_the_same_query_from_many_threads(tmp_path):
    """The API shares one connection between its worker threads. A cached prepared statement used by two threads at once raised
    "bad parameter or other API misuse" (the deck page asks for three things at the same time, all starting with the same query)."""
    d = dbmod.connect(tmp_path / "t.db")
    d.execute("INSERT INTO decks (name) VALUES ('x')")
    d.commit()

    def work(_):
        for _ in range(300):
            assert d.execute("SELECT * FROM decks WHERE id=?", (1,)).fetchone()["name"] == "x"
        return True

    with ThreadPoolExecutor(8) as pool:
        assert all(pool.map(work, range(8)))
