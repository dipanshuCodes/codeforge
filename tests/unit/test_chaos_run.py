import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "chaos_run.py"


def _load():
    spec = importlib.util.spec_from_file_location("chaos_run", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_twenty_of_twenty_answered_under_60_percent_chaos(tmp_path):
    rows = _load().run_chaos(str(tmp_path / "c.db"), rate=0.6, seed=42)
    assert len(rows) == 20 and all(r["answered"] for r in rows)
    for r in rows:  # every answer names its tier, or is an honest refusal with a ticket
        assert r["tier"] or (r["outcome"] == "cannot_generate" and r["ticket"])
    assert all(r["ticket"] for r in rows if r["outcome"] == "cannot_generate")


def test_same_seed_gives_the_same_run(tmp_path):
    m = _load()
    a = m.run_chaos(str(tmp_path / "a.db"), seed=7)
    b = m.run_chaos(str(tmp_path / "b.db"), seed=7)
    assert [(r["outcome"], r["tier"]) for r in a] == [(r["outcome"], r["tier"]) for r in b]
