"""Run tests in a disposable cwd so no real trading state can be changed."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.environ.update(BROKER="paper", TRADING_ENABLED="false", DATABASE_URL="sqlite://", NEWS_FILTER_ENABLED="false")
sys.path.insert(0, str(root))
with tempfile.TemporaryDirectory(prefix="tajari-tests-") as tmp:
    os.chdir(tmp)
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
