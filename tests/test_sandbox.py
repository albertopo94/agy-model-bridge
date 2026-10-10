"""Tests ensuring the global test sandbox completely isolates the user's real HOME."""

import os
from pathlib import Path
import unittest

from bridge.setup.lifecycle import uninstall
from tests import REAL_USER_HOME, SANDBOX_HOME


class TestGlobalTestSandbox(unittest.TestCase):
    """Guards against tests ever touching or modifying the real user home."""

    def test_path_home_points_to_sandbox(self):
        self.assertEqual(Path.home(), SANDBOX_HOME)
        self.assertNotEqual(Path.home(), REAL_USER_HOME)

    def test_expanduser_points_to_sandbox(self):
        self.assertEqual(os.path.expanduser("~"), str(SANDBOX_HOME))
        self.assertEqual(os.path.expanduser("~/.gentle-shell"), str(SANDBOX_HOME / ".gentle-shell"))

    def test_environ_points_to_sandbox(self):
        self.assertEqual(os.environ.get("HOME"), str(SANDBOX_HOME))
        state_dir = Path(os.environ.get("AGY_BRIDGE_STATE_DIR", Path.home() / ".agy-bridge"))
        self.assertTrue(str(state_dir).startswith(str(SANDBOX_HOME)))

    def test_uninstall_never_touches_real_user_home(self):
        # Record mtimes or state of any files in real user home if they exist
        gs_real = REAL_USER_HOME / ".gentle-shell" / "agent" / "models.json"
        before_mtime = gs_real.stat().st_mtime if gs_real.exists() else None

        # Execute uninstall with full client restoration enabled
        res = uninstall(restore_configs=True, purge_backups=False)
        self.assertIsInstance(res, dict)

        # Assert real user home was completely untouched
        if gs_real.exists():
            after_mtime = gs_real.stat().st_mtime
            self.assertEqual(before_mtime, after_mtime, "Real Gentle Shell models.json was touched by uninstall()!")
