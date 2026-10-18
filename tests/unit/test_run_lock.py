"""Unit tests for the single-instance run lock (agent/utils/run_lock.py)."""

import subprocess
import sys
import textwrap

from agent.utils.run_lock import single_instance


class TestSingleInstance:
    def test_acquires_when_free(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEWSLETTER_LOCK_PATH", str(tmp_path / "agent.lock"))
        with single_instance() as acquired:
            assert acquired is True

    def test_creates_missing_parent_dir(self, tmp_path, monkeypatch):
        lock = tmp_path / "nested" / "agent.lock"
        monkeypatch.setenv("NEWSLETTER_LOCK_PATH", str(lock))
        with single_instance():
            assert lock.exists()

    def test_second_holder_in_same_process_is_refused(self, tmp_path, monkeypatch):
        """flock locks are per open file description, so a nested open is refused too."""
        monkeypatch.setenv("NEWSLETTER_LOCK_PATH", str(tmp_path / "agent.lock"))
        with single_instance() as first:
            with single_instance() as second:
                assert first is True
                assert second is False

    def test_reacquirable_after_release(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEWSLETTER_LOCK_PATH", str(tmp_path / "agent.lock"))
        with single_instance():
            pass
        with single_instance() as acquired:
            assert acquired is True

    def test_other_process_is_refused_while_held(self, tmp_path, monkeypatch):
        lock = tmp_path / "agent.lock"
        monkeypatch.setenv("NEWSLETTER_LOCK_PATH", str(lock))
        probe = textwrap.dedent(
            """
            from agent.utils.run_lock import single_instance
            with single_instance() as acquired:
                print(acquired)
            """
        )
        with single_instance():
            out = subprocess.run(
                [sys.executable, "-c", probe], capture_output=True, text=True, check=True
            ).stdout
        assert out.strip().splitlines()[-1] == "False"

    def test_logs_skip_when_held(self, tmp_path, monkeypatch, mocker):
        monkeypatch.setenv("NEWSLETTER_LOCK_PATH", str(tmp_path / "agent.lock"))
        mock_log = mocker.patch("agent.utils.run_lock.log")
        with single_instance():
            with single_instance():
                pass
        mock_log.warning.assert_called_once_with(
            "run_skipped_already_running", lock_path=str(tmp_path / "agent.lock")
        )
