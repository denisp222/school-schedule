import sys
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Importing app.server must never open the user's working project, even before
# individual API fixtures replace its store.
_test_data=tempfile.TemporaryDirectory(prefix='raspisanie-tests-')
os.environ['SCHEDULE_DATA']=_test_data.name

# Unit tests exercise the in-process solver implementation. Dedicated worker
# tests call calculate() and test the real process boundary separately.
import pytest

@pytest.fixture(autouse=True)
def direct_solver_for_unit_tests(monkeypatch):
    monkeypatch.setenv('SCHEDULE_SOLVER_WORKER','1')
