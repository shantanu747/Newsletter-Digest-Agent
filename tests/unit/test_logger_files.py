"""Unit tests for the timestamped daily log files and 30-day pruning in agent.utils.logger."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

from agent.utils.logger import (
    LOG_RETENTION_DAYS,
    _attach_file_handler,
    _DailyFileHandler,
    prune_old_logs,
)

TODAY = date(2026, 9, 30)


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)


def _touch(path, age_days: float = 0) -> None:
    path.write_text("x")
    midnight = datetime.combine(TODAY, datetime.min.time(), tzinfo=timezone.utc).timestamp()
    ts = midnight - age_days * 86400
    os.utime(path, (ts, ts))


def test_record_creates_dated_file_with_one_json_line(tmp_path):
    handler = _DailyFileHandler(tmp_path, today_fn=lambda: TODAY)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(_record(json.dumps({"event": "hello"})))
    handler.close()

    lines = (tmp_path / "digest-2026-09-30.log").read_text().splitlines()
    assert [json.loads(line) for line in lines] == [{"event": "hello"}]


def test_handler_switches_file_when_date_changes(tmp_path):
    current = [TODAY]
    handler = _DailyFileHandler(tmp_path, today_fn=lambda: current[0])
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(_record("day-one"))
    current[0] = TODAY + timedelta(days=1)
    handler.emit(_record("day-two"))
    handler.close()

    assert (tmp_path / "digest-2026-09-30.log").read_text().splitlines() == ["day-one"]
    assert (tmp_path / "digest-2026-10-01.log").read_text().splitlines() == ["day-two"]


def test_rolling_to_new_date_prunes_expired_logs(tmp_path):
    old = tmp_path / "digest-2026-08-01.log"
    old.write_text("x")
    current = [TODAY]
    handler = _DailyFileHandler(tmp_path, today_fn=lambda: current[0])
    handler.setFormatter(logging.Formatter("%(message)s"))
    current[0] = TODAY + timedelta(days=1)
    handler.emit(_record("roll"))
    handler.close()

    assert not old.exists()


def test_prune_deletes_only_expired_files(tmp_path):
    old_log = tmp_path / f"digest-{TODAY - timedelta(days=31)}.log"
    keep_log = tmp_path / f"digest-{TODAY - timedelta(days=29)}.log"
    old_bak = tmp_path / "agent.log.pre-2026-08-01.bak"
    new_bak = tmp_path / "agent.error.log.pre-2026-09-25.bak"
    agent_log = tmp_path / "agent.log"
    agent_err = tmp_path / "agent.error.log"
    junk = tmp_path / "digest-notadate.log"
    for path in (old_log, keep_log, junk):
        path.write_text("x")
    _touch(old_bak, age_days=LOG_RETENTION_DAYS + 5)
    _touch(new_bak, age_days=5)
    _touch(agent_log, age_days=200)
    _touch(agent_err, age_days=200)

    deleted = prune_old_logs(tmp_path, today=TODAY)

    assert {p.name for p in deleted} == {old_log.name, old_bak.name}
    assert not old_log.exists() and not old_bak.exists()
    for survivor in (keep_log, new_bak, agent_log, agent_err, junk):
        assert survivor.exists()


def test_prune_ignores_missing_dir(tmp_path):
    assert prune_old_logs(tmp_path / "nope", today=TODAY) == []


def test_unwritable_log_dir_is_fail_soft(tmp_path, capsys):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    assert _attach_file_handler(blocker / "logs") is None

    readonly = tmp_path / "ro"
    readonly.mkdir()
    readonly.chmod(0o500)
    try:
        handler = _DailyFileHandler(readonly, today_fn=lambda: TODAY)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_record("dropped"))  # must not raise
        handler.close()
    finally:
        readonly.chmod(0o700)
    assert "Logging error" not in capsys.readouterr().err
