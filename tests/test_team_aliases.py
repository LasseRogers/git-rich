import csv

from gitrich.odds.link import ALIASES


def test_aliases_are_well_formed():
    with open(ALIASES, newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ["oddspapi_name", "team_name"]
        rows = list(reader)
    names = [r["oddspapi_name"] for r in rows]
    assert all(r["oddspapi_name"].strip() and r["team_name"].strip() for r in rows), "empty name"
    assert all(r["oddspapi_name"] == r["oddspapi_name"].strip() for r in rows), "stray whitespace"
    assert len(names) == len(set(names)), "an odds name is mapped twice"
    assert all(r["oddspapi_name"] != r["team_name"] for r in rows), "an alias that maps a name to itself"
