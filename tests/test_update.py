"""Fixtures pequenas: o atualizador nunca inicia a assistente ou instala pacotes."""

from pathlib import Path
import importlib.util
import shutil
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/atualizar_ivi.py"
SPEC = importlib.util.spec_from_file_location("ivi_local_updater", MODULE_PATH)
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.target = self.root / "new", self.root / "installed"
        for folder, version in ((self.source, "new"), (self.target, "old")):
            (folder / "src/ivi").mkdir(parents=True)
            (folder / "pyproject.toml").write_text('[project]\nname="ivi-assistant"\n', encoding="utf-8")
            (folder / "src/ivi/__init__.py").write_text(version, encoding="utf-8")

    def test_update_preserves_user_data_and_backs_up_changed_code(self):
        sentinels = [".env", ".ivi/memory.sqlite3", ".venv/user.txt", "models/private.bin", "custom-user-data.txt", ".git/config"]
        for name in sentinels:
            path = self.target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"preserve user data")
        (self.source / ".env").write_text("must not copy", encoding="utf-8")
        backup = updater.update_installation(self.source, self.target)
        self.assertEqual((self.target / "src/ivi/__init__.py").read_text(), "new")
        self.assertEqual((backup / "src/ivi/__init__.py").read_text(), "old")
        for name in sentinels:
            self.assertEqual((self.target / name).read_bytes(), b"preserve user data", name)
        self.assertIsNone(updater.update_installation(self.target, self.target))

    def test_invalid_target_is_refused_before_writing(self):
        (self.target / "pyproject.toml").write_text('[project]\nname="unrelated-project"\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "instalacao valida"):
            updater.update_installation(self.source, self.target)
        self.assertEqual((self.target / "src/ivi/__init__.py").read_text(), "old")
        self.assertFalse((self.target / ".ivi-backups").exists())

    def test_symlink_escape_is_refused_before_writing(self):
        outside = self.root / "outside.py"
        outside.write_text("outside sentinel", encoding="utf-8")
        try:
            (self.target / "src/ivi/escape.py").symlink_to(outside)
        except OSError:
            self.skipTest("Criacao de symlinks nao disponivel neste sistema")
        (self.source / "src/ivi/escape.py").write_text("do not write outside", encoding="utf-8")
        with self.assertRaises(ValueError):
            updater.update_installation(self.source, self.target)
        self.assertEqual(outside.read_text(), "outside sentinel")
        self.assertFalse((self.target / ".ivi-backups").exists())

    def test_partial_copy_failure_restores_changed_files(self):
        (self.source / "src/ivi/new_module.py").write_text("new file", encoding="utf-8")
        actual_copy = shutil.copy2
        failed = False

        def copy_then_fail(source, target, *args, **kwargs):
            nonlocal failed
            result = actual_copy(source, target, *args, **kwargs)
            if not failed and Path(source) == self.source / "src/ivi/new_module.py":
                failed = True
                raise OSError("injected partial-copy failure")
            return result

        with patch.object(updater.shutil, "copy2", side_effect=copy_then_fail):
            with self.assertRaisesRegex(RuntimeError, "Arquivos alterados restaurados"):
                updater.update_installation(self.source, self.target)
        self.assertEqual((self.target / "src/ivi/__init__.py").read_text(), "old")
        self.assertFalse((self.target / "src/ivi/new_module.py").exists())
        backups = list((self.target / ".ivi-backups").glob("*/src/ivi/__init__.py"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "old")


if __name__ == "__main__":
    unittest.main()
