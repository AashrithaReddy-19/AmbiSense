"""Test-suite isolation.

The application's default DATABASE_URL points at the repo's real ambisense.db
(see backend/app/config.py). Without this override, every test run writes
users/sessions/etc. directly into that file, which both pollutes real data
and causes UNIQUE-constraint failures on repeated runs. This module sets
DATABASE_URL to a fresh, throwaway SQLite file before any test module (or
backend.app.* module) is imported, so pydantic-settings picks it up on the
first call to get_settings().
"""

import os
import tempfile
from pathlib import Path

_TEST_DB = Path(tempfile.gettempdir()) / "ambisense_pytest.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"

# Uploaded videos, generated reports, logs and classroom reference images are
# also isolated; otherwise every run leaves fixture artifacts in the real
# videos/ and reports/ folders (Settings creates these directories on import).
_TEST_ARTIFACTS = Path(tempfile.gettempdir()) / "ambisense_pytest_artifacts"
for _name, _env in (("videos", "UPLOAD_DIR"), ("reports", "REPORT_DIR"), ("logs", "LOG_DIR"), ("references", "CLASSROOM_REFERENCE_DIR")):
    _folder = _TEST_ARTIFACTS / _name
    _folder.mkdir(parents=True, exist_ok=True)
    os.environ[_env] = str(_folder)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Rate-limit counters are process-wide; every test starts with a clean slate."""
    from backend.app.services.rate_limit import reset_rate_limits

    reset_rate_limits()
    yield
