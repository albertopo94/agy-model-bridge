import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class TestInstallScript(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.install_dir = self.root / "core"
        self.bin_dir = self.root / "bin"
        self.install_sh = Path(__file__).resolve().parent.parent / "install.sh"

        # Initialize a git repo with a broken remote so git pull will fail
        self.install_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(self.install_dir)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.install_dir), "remote", "add", "origin", "https://invalid.example.com/repo.git"],
            check=True,
            capture_output=True,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_install_update_failure_exits_with_error_english(self):
        env = os.environ.copy()
        env["AGY_BRIDGE_DIR"] = str(self.install_dir)
        env["AGY_BRIDGE_BIN"] = str(self.bin_dir)
        env["AGY_LANG"] = "en"

        res = subprocess.run(
            ["bash", str(self.install_sh)],
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(res.returncode, 0, "install.sh should exit with non-zero on git pull failure")
        combined_output = res.stdout + res.stderr
        self.assertIn("Failed to update existing repository", combined_output)
        self.assertNotIn("installed successfully", combined_output)

    def test_install_update_failure_exits_with_error_spanish(self):
        env = os.environ.copy()
        env["AGY_BRIDGE_DIR"] = str(self.install_dir)
        env["AGY_BRIDGE_BIN"] = str(self.bin_dir)
        env["AGY_LANG"] = "es"

        res = subprocess.run(
            ["bash", str(self.install_sh)],
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(res.returncode, 0, "install.sh should exit with non-zero on git pull failure")
        combined_output = res.stdout + res.stderr
        self.assertIn("Falló la actualización del repositorio", combined_output)
        self.assertNotIn("instalado correctamente", combined_output)


    def test_install_update_success(self):
        remote_repo = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote_repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.install_dir), "remote", "set-url", "origin", str(remote_repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.install_dir), "checkout", "-b", "main"], check=True, capture_output=True)
        dummy_file = self.install_dir / "README.md"
        dummy_file.write_text("dummy", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.install_dir), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.install_dir), "-c", "user.name=Test", "-c", "user.email=test@test.com", "commit", "-m", "init"],
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "-C", str(self.install_dir), "push", "-u", "origin", "main"], check=True, capture_output=True)

        env = os.environ.copy()
        env["AGY_BRIDGE_DIR"] = str(self.install_dir)
        env["AGY_BRIDGE_BIN"] = str(self.bin_dir)
        env["AGY_LANG"] = "en"

        res = subprocess.run(
            ["bash", str(self.install_sh)],
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 0)
        combined_output = res.stdout + res.stderr
        self.assertIn("installed successfully", combined_output)
        self.assertTrue((self.bin_dir / "agy-bridge").exists())


if __name__ == "__main__":
    unittest.main()
