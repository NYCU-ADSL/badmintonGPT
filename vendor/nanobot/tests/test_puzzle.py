"""Puzzle answer store: normalization and the n/2-minute wrong-answer cooldown. [badmintonGPT fork]"""

from __future__ import annotations

from nanobot import puzzle


def test_normalize_drops_whitespace_and_folds_full_width() -> None:
    assert puzzle.normalize_answer(" 謎 底\n") == "謎底"
    assert puzzle.normalize_answer("ＡＢＣ") == "ABC"


def test_wrong_answers_cool_down_n_halves_of_a_minute(tmp_path) -> None:
    s = puzzle.PuzzleStore(tmp_path / "p.db")
    try:
        first = s.attempt("a@x", "殺球", "謎底", now=1000.0)
        assert first["accepted"] and not first["correct"]
        assert first["wrong_count"] == 1 and first["retry_after_s"] == 30

        early = s.attempt("a@x", "謎底", "謎底", now=1029.0)
        assert not early["accepted"] and early["retry_after_s"] == 1 and not early["solved"]

        second = s.attempt("a@x", "挑球", "謎底", now=1030.0)
        assert second["wrong_count"] == 2 and second["retry_after_s"] == 60

        third = s.attempt("a@x", "切球", "謎底", now=1090.0)
        assert third["wrong_count"] == 3 and third["retry_after_s"] == 90

        assert s.status("b@x", now=1090.0) == {
            "configured": True, "solved": False, "wrong_count": 0, "retry_after_s": 0,
        }

        ok = s.attempt("a@x", "謎 底", "謎底", now=1180.0)
        assert ok["accepted"] and ok["correct"] and ok["solved"] and ok["retry_after_s"] == 0
        again = s.attempt("a@x", "錯", "謎底", now=1181.0)
        assert not again["accepted"] and again["correct"] and again["wrong_count"] == 3
    finally:
        s.close()


def test_attempts_survive_reopening_the_store(tmp_path) -> None:
    s = puzzle.PuzzleStore(tmp_path / "p.db")
    s.attempt("a@x", "錯", "謎底", now=0.0)
    s.close()
    s = puzzle.PuzzleStore(tmp_path / "p.db")
    try:
        assert s.status("a@x", now=10.0)["retry_after_s"] == 20
    finally:
        s.close()
