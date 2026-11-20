import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.init_db import init_db

API_KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


class IsolatedTestCase(unittest.TestCase):
    """Runs every test against a fresh temporary database, with no API key set.

    genai.Client is patched to fail loudly, so a test can only reach Gemini through
    an explicit mock of src.agent.genai.Client.
    """

    def setUp(self):
        tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmpdir.cleanup)
        self.db_path = os.path.join(tmpdir.name, "test_mock_data.db")

        env = patch.dict(os.environ, {"PROCUREMENT_DB_PATH": self.db_path})
        env.start()
        self.addCleanup(env.stop)
        for key in API_KEY_VARS:
            os.environ.pop(key, None)

        guard = patch("src.agent.genai.Client", side_effect=AssertionError("Real Gemini client must not be used in tests"))
        guard.start()
        self.addCleanup(guard.stop)

        with contextlib.redirect_stdout(io.StringIO()):
            init_db()

    def set_dummy_api_key(self):
        os.environ["GEMINI_API_KEY"] = "dummy-test-key"
