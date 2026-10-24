import pytest

from src import config
from src.monitoring import audit


@pytest.fixture(autouse=True)
def audit_logs_in_tmp(tmp_path):
    """
    Tests never write to the real LOG_DIR (docs/audit_logging_design.md,
    section 3): any audit run a test starts, directly or through a CLI entry
    point such as run_eval main, logs under the test's own temp directory.
    A run a test leaves open is closed so it can't leak into the next test.

    Its own MonkeyPatch, not the shared `monkeypatch` fixture: a test that
    calls monkeypatch.undo() would otherwise undo this too and log to the
    real ./logs (found 2026-10-23: test_check_retry_logging_only_observes).
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "LOG_DIR", tmp_path / "audit_logs")
        yield
    audit._run = None
    audit._context.clear()


@pytest.fixture(autouse=True, scope="session")
def real_log_dir_untouched():
    """Fails the session if any test wrote to the real LOG_DIR."""
    index = config.LOG_DIR / "index.jsonl"
    before = index.read_bytes() if index.exists() else b""
    yield
    after = index.read_bytes() if index.exists() else b""
    assert after == before, f"a test wrote an audit run to the real {index}"
