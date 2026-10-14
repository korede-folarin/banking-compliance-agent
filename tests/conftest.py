import pytest

from src import config
from src.monitoring import audit


@pytest.fixture(autouse=True)
def audit_logs_in_tmp(tmp_path, monkeypatch):
    """
    Tests never write to the real LOG_DIR (docs/audit_logging_design.md,
    section 3): any audit run a test starts, directly or through a CLI entry
    point such as run_eval main, logs under the test's own temp directory.
    A run a test leaves open is closed so it can't leak into the next test.
    """
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "audit_logs")
    yield
    audit._run = None
    audit._context.clear()
