import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "antrix_app"))


@pytest.fixture(scope="session")
def root():
    return ROOT


@pytest.fixture(scope="session")
def detections():
    """A small real slice of cleaned FIRMS data."""
    path = ROOT / "firms_clean.csv"
    if not path.exists():
        pytest.skip("firms_clean.csv not built yet")
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def final():
    # The root copy is a local build product; the gzipped app copy is committed.
    for path in (ROOT / "firms_final.csv", ROOT / "antrix_app" / "firms_final.csv.gz"):
        if path.exists():
            return pd.read_csv(path, low_memory=False)
    pytest.skip("firms_final.csv not built yet")


@pytest.fixture(scope="session")
def client():
    import app as flask_app
    flask_app.app.config["TESTING"] = True
    return flask_app.app.test_client()
