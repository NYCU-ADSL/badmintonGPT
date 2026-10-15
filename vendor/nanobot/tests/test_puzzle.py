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
            "surveyed": False, "surveyed_at": None, "stamp_code": None,
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


GOOD_SURVEY = {
    "fit": "5", "tried_other": "yes", "other_fit": "3", "overall": "4",
    "recommend": "4", "role": "player", "level": "casual", "human_eval": "yes",
    "contact_email": " me@uni.edu ", "suggestion": "  想看雙打數據 ",
}


def test_survey_validation() -> None:
    answers, bad = puzzle.validate_survey(GOOD_SURVEY)
    assert bad is None and answers == {
        "tried_other": "yes", "role": "player", "level": "casual", "fit": 5,
        "other_fit": 3, "overall": 4, "recommend": 4, "human_eval": "yes",
        "contact_email": "me@uni.edu", "suggestion": "想看雙打數據",
    }
    # other_fit is only asked (and kept) after "yes"
    answers, bad = puzzle.validate_survey({**GOOD_SURVEY, "tried_other": "no", "other_fit": ""})
    assert bad is None and "other_fit" not in answers
    assert puzzle.validate_survey({**GOOD_SURVEY, "other_fit": ""}) == (None, "other_fit")
    assert puzzle.validate_survey({**GOOD_SURVEY, "fit": "6"}) == (None, "fit")
    assert puzzle.validate_survey({**GOOD_SURVEY, "recommend": "0"}) == (None, "recommend")
    assert puzzle.validate_survey({**GOOD_SURVEY, "recommend": "-1"}) == (None, "recommend")
    assert "speed" not in puzzle.validate_survey({**GOOD_SURVEY, "speed": "3"})[0]
    assert puzzle.validate_survey({**GOOD_SURVEY, "role": "boss"}) == (None, "role")
    assert puzzle.validate_survey({**GOOD_SURVEY, "human_eval": ""}) == (None, "human_eval")
    for bad_email in ("", "me", "me@uni", "a b@uni.edu", "x" * 250 + "@u.edu"):
        assert puzzle.validate_survey({**GOOD_SURVEY, "contact_email": bad_email}) == (
            None, "contact_email")
    answers, bad = puzzle.validate_survey({**GOOD_SURVEY, "human_eval": "no", "contact_email": "x"})
    assert bad is None and "contact_email" not in answers
    assert puzzle.validate_survey({**GOOD_SURVEY, "suggestion": ""})[1] is None
    too_long = "字" * (puzzle.SURVEY_TEXT_MAX_CHARS + 1)
    assert puzzle.validate_survey({**GOOD_SURVEY, "suggestion": too_long}) == (None, "suggestion")


def test_survey_only_after_solving_and_only_once(tmp_path) -> None:
    s = puzzle.PuzzleStore(tmp_path / "p.db")
    try:
        answers, _ = puzzle.validate_survey(GOOD_SURVEY)
        early = s.submit_survey("a@x", answers, now=10.0)
        assert not early["ok"] and early["reason"] == "unsolved" and not early["surveyed"]

        s.attempt("a@x", "謎底", "謎底", now=20.0)
        assert s.status("a@x")["surveyed"] is False
        done = s.submit_survey("a@x", answers, now=30.0)
        assert done["ok"] and done["surveyed"] and done["surveyed_at"] == 30.0

        again = s.submit_survey("a@x", {**answers, "fit": 1}, now=40.0)
        assert again["ok"] and again["surveyed_at"] == 30.0
        rows = s.export_rows()
        assert len(rows) == 1 and rows[0]["fit"] == 5 and rows[0]["solved_at"] == 20.0
        assert rows[0]["wrong_count"] == 0 and rows[0]["suggestion"] == "想看雙打數據"
    finally:
        s.close()


def test_staff_list_and_stamp_code_parsing(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_PUZZLE_STAFF", "Staff@X.org, @crew.org")
    assert puzzle.is_staff("staff@x.org") and puzzle.is_staff("anyone@crew.org")
    assert not puzzle.is_staff("player@x.org") and not puzzle.is_staff(None)
    monkeypatch.delenv("NANOBOT_PUZZLE_STAFF")
    assert not puzzle.is_staff("staff@x.org")
    assert puzzle.normalize_stamp_code("https://h/puzzle-staff.html#c=Ab-_9") == "Ab-_9"
    assert puzzle.normalize_stamp_code(" Ab-_9 ") == "Ab-_9"
    assert puzzle.normalize_stamp_code("１２ ３４") == "1234"


def test_scan_counts_and_returns_the_survey(tmp_path) -> None:
    s = puzzle.PuzzleStore(tmp_path / "p.db")
    try:
        s.attempt("a@x", "謎底", "謎底", now=1.0)
        answers, _ = puzzle.validate_survey(GOOD_SURVEY)
        code = s.submit_survey("a@x", answers, now=2.0)["stamp_code"]
        assert puzzle.STAMP_CODE_RE.fullmatch(code) and len(code) == 4
        assert s.status("a@x")["stamp_code"] == code
        assert s.scan("nope") is None

        first = s.scan(code, now=10.0)
        assert first["email"] == "a@x" and first["scan_count"] == 1
        assert first["first_scanned_at"] == 10.0 and first["answers"]["role"] == "player"
        second = s.scan(code, now=20.0)
        assert second["scan_count"] == 2 and second["first_scanned_at"] == 10.0
        assert s.export_rows()[0]["scan_count"] == 2
    finally:
        s.close()


def test_survey_table_from_before_the_staff_qr_is_migrated(tmp_path) -> None:
    import sqlite3

    db = sqlite3.connect(tmp_path / "p.db")
    db.executescript(
        "CREATE TABLE puzzle_attempts (email TEXT PRIMARY KEY, wrong_count INTEGER NOT NULL DEFAULT 0,"
        " locked_until REAL NOT NULL DEFAULT 0, solved_at REAL);"
        "CREATE TABLE puzzle_surveys (email TEXT PRIMARY KEY, submitted_at REAL NOT NULL,"
        " answers TEXT NOT NULL);"
        "INSERT INTO puzzle_attempts VALUES ('a@x', 0, 0, 1.0);"
        "INSERT INTO puzzle_surveys VALUES ('a@x', 2.0, '{\"role\": \"fan\"}');"
    )
    db.commit()
    db.close()
    s = puzzle.PuzzleStore(tmp_path / "p.db")
    try:
        status = s.status("a@x")
        assert status["surveyed"] and status["stamp_code"]
        assert s.scan(status["stamp_code"])["answers"] == {"role": "fan"}
    finally:
        s.close()
    puzzle.PuzzleStore(tmp_path / "p.db").close()  # second open: already migrated, no error


def test_stamp_codes_are_never_handed_out_twice(tmp_path, monkeypatch) -> None:
    s = puzzle.PuzzleStore(tmp_path / "p.db")
    try:
        answers, _ = puzzle.validate_survey(GOOD_SURVEY)
        s.attempt("a@x", "謎底", "謎底", now=1.0)
        first = s.submit_survey("a@x", answers, now=2.0)["stamp_code"]
        assert s.submit_survey("a@x", answers, now=3.0)["stamp_code"] == first  # resubmit keeps it
        s._db.execute("DELETE FROM puzzle_surveys")  # what deleting the responses does
        # leave only the deleted code and one other free: the new survey must get the other one
        s._db.executemany(
            "INSERT INTO puzzle_stamp_codes VALUES (?)",
            [(str(n),) for n in range(1000, 10000) if str(n) not in (first, "4321")],
        )
        assert s.submit_survey("a@x", answers, now=4.0)["stamp_code"] == "4321" != first
        s.attempt("b@x", "謎底", "謎底", now=5.0)
        assert len(s.submit_survey("b@x", answers, now=6.0)["stamp_code"]) == 5  # 4 digits used up
    finally:
        s.close()


def test_long_stamp_codes_from_the_first_version_become_numbers(tmp_path) -> None:
    import sqlite3

    db = sqlite3.connect(tmp_path / "p.db")
    db.executescript(
        "CREATE TABLE puzzle_attempts (email TEXT PRIMARY KEY, wrong_count INTEGER NOT NULL DEFAULT 0,"
        " locked_until REAL NOT NULL DEFAULT 0, solved_at REAL);"
        "CREATE TABLE puzzle_surveys (email TEXT PRIMARY KEY, submitted_at REAL NOT NULL,"
        " answers TEXT NOT NULL, stamp_code TEXT NOT NULL UNIQUE,"
        " scan_count INTEGER NOT NULL DEFAULT 0, first_scanned_at REAL);"
        "INSERT INTO puzzle_surveys VALUES ('a@x', 2.0, '{}', 'Xk3_9fQa-Lm2PzR7', 1, 9.0);"
        "INSERT INTO puzzle_surveys VALUES ('b@x', 3.0, '{}', '5678', 0, NULL);"
    )
    db.commit()
    db.close()
    s = puzzle.PuzzleStore(tmp_path / "p.db")
    try:
        code = s.status("a@x")["stamp_code"]
        assert len(code) == 4 and code != "5678"
        assert s.scan(code)["scan_count"] == 2  # the scan history moves with it
        assert s.status("b@x")["stamp_code"] == "5678"
    finally:
        s.close()
