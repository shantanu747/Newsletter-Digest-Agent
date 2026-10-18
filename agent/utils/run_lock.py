"""Single-instance run lock — stops two agent processes from running the pipeline at once.

Two launchd jobs (or a launchd job plus a manual run) firing together would otherwise
fetch the same unread emails, summarize them twice, and send duplicate digests and
Signals reports. The lock is an advisory `fcntl.flock` on a file under `data/`; the OS
releases it when the holding process exits, including on a crash, so it never goes stale.
"""
from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent.utils.logger import get_logger

_LOCK_PATH_ENV = "NEWSLETTER_LOCK_PATH"
_DEFAULT_LOCK_PATH = "data/agent.lock"

log = get_logger(__name__)


def _lock_path() -> Path:
    return Path(os.environ.get(_LOCK_PATH_ENV) or _DEFAULT_LOCK_PATH)


@contextmanager
def single_instance() -> Iterator[bool]:
    """Yield True if this process holds the run lock, False if another process does.

    Never blocks: a caller that gets False should skip its run, not wait.
    """
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.warning("run_skipped_already_running", lock_path=str(path))
            yield False
            return
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(f"{os.getpid()}\n")
            fh.flush()
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
