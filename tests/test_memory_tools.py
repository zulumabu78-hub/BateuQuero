from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ivi.memory import MemoryStore
from ivi.tools import ToolRegistry, ToolRequest, parse_tool_request, validate_url


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "nested" / "memory.sqlite3"
        self.store = MemoryStore(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_history_persists_and_returns_latest_in_chronological_order(self):
        for index in range(5):
            self.store.add_message("user", str(index))
        restored = MemoryStore(self.path)
        self.assertEqual([row["content"] for row in restored.recent_messages(3)], ["2", "3", "4"])
        restored.clear_history()
        self.assertEqual(self.store.recent_messages(), [])

    def test_explicit_memory_is_independent_from_history_and_parameterized(self):
        payload = "Gosto de jazz'); DROP TABLE messages; --"
        item = self.store.add_memory(payload)
        self.store.add_message("user", "Uma conversa não vira memória automaticamente")
        self.assertEqual([row["content"] for row in self.store.list_memories()], [payload])
        self.store.clear_history()
        self.assertEqual(self.store.list_memories()[0]["id"], item["id"])
        self.assertTrue(self.store.delete_memory(item["id"]))
        self.assertFalse(self.store.delete_memory(item["id"]))

    def test_settings_are_validated_and_persisted_atomically(self):
        self.store.update_settings({"require_wake_word": True, "speech_rate": 0.8})
        self.assertEqual(MemoryStore(self.path).get_settings()["speech_rate"], 0.8)
        self.assertTrue(self.store.get_settings()["require_wake_word"])
        self.assertTrue(self.store.get_settings()["voice_enabled"])
        with self.assertRaises(ValueError):
            self.store.update_settings({"voice_enabled": False, "speech_rate": 20})
        self.assertTrue(self.store.get_settings()["voice_enabled"])
        for invalid in [{"unknown": True}, {"voice_enabled": "false"}, {"speech_rate": True}]:
            with self.assertRaises(ValueError):
                self.store.update_settings(invalid)

    def test_parallel_writes_use_independent_connections(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda number: self.store.add_message("user", f"message {number}"), range(30)))
        self.assertEqual(len(self.store.recent_messages(100)), 30)

    def test_limits_reject_invalid_data(self):
        for role, content in [("tool", "hello"), ("user", " "), ("user", "x" * 16001)]:
            with self.assertRaises(ValueError):
                self.store.add_message(role, content)
        for content in ["", "x" * 2001]:
            with self.assertRaises(ValueError):
                self.store.add_memory(content)
        for limit in [0, 201, True, "30"]:
            with self.assertRaises(ValueError):
                self.store.recent_messages(limit)


class ToolTests(unittest.TestCase):
    def test_parsing_is_inert_and_recognizes_explicit_requests(self):
        with patch("ivi.tools.subprocess.Popen") as process, patch("ivi.tools.webbrowser.open") as browser:
            self.assertEqual(parse_tool_request("I.V.I., abre a calculadora").arguments, {"app": "calculator"})
            self.assertEqual(parse_tool_request("Abrir o bloco de notas, por favor.").arguments, {"app": "notepad"})
            self.assertEqual(parse_tool_request("Abre o Spotify e coloca uma música da Laufey.").arguments, {"query": "Laufey"})
            self.assertEqual(parse_tool_request("pesquisa jazz no Spotify").arguments, {"query": "jazz"})
            process.assert_not_called()
            browser.assert_not_called()

    def test_unknown_commands_cannot_become_shell_commands(self):
        for text in ["abre cmd.exe", "abre calculadora & del C:\\*", "execute powershell", "Explique o que significa abrir Spotify", "abre ../evil.exe"]:
            self.assertIsNone(parse_tool_request(text), text)
        with self.assertRaises(ValueError):
            ToolRegistry(platform="win32").execute(ToolRequest("shell", "", "", {"command": "whoami"}))

    def test_windows_actions_are_denied_on_remote_linux(self):
        with patch("ivi.tools.subprocess.Popen") as process, patch("ivi.tools.webbrowser.open") as browser:
            for text in ["abre calculadora", "abre navegador", "pesquisa Laufey no spotify"]:
                with self.assertRaisesRegex(RuntimeError, "Windows"):
                    ToolRegistry(platform="linux").execute(parse_tool_request(text))
            process.assert_not_called()
            browser.assert_not_called()

    def test_app_command_is_fixed_and_never_uses_a_shell(self):
        with patch("ivi.tools.subprocess.Popen") as process:
            message = ToolRegistry(platform="win32").execute(parse_tool_request("abre calculadora"))
            arguments, options = process.call_args
            self.assertEqual(len(arguments[0]), 1)
            self.assertTrue(arguments[0][0].endswith("calc.exe"))
            self.assertFalse(options["shell"])
            self.assertIn("Calculadora", message)
        with patch("ivi.tools.os.startfile", create=True) as start:
            ToolRegistry(platform="win32").execute(parse_tool_request("abre Spotify"))
            start.assert_called_once_with("spotify:")

    def test_spotify_search_is_encoded_and_does_not_claim_playback(self):
        with patch("ivi.tools.webbrowser.open", return_value=True) as browser:
            message = ToolRegistry(platform="win32").execute(parse_tool_request("pesquisa Laufey & jazz no Spotify"))
            browser.assert_called_once_with("https://open.spotify.com/search/Laufey%20%26%20jazz", new=2)
            self.assertIn("Escolha a faixa", message)

    def test_files_shortcut_only_opens_the_fixed_windows_explorer(self):
        request = parse_tool_request("abrir arquivos")
        self.assertEqual(request.arguments, {"app": "files"})
        with patch("ivi.tools.subprocess.Popen") as process:
            ToolRegistry(platform="win32").execute(request)
            arguments, options = process.call_args
            self.assertEqual(len(arguments[0]), 1)
            self.assertTrue(arguments[0][0].endswith("explorer.exe"))
            self.assertFalse(options["shell"])
        self.assertIsNone(parse_tool_request("abrir arquivos & powershell.exe"))

    def test_url_validation_rejects_protocol_credentials_and_untrusted_hosts(self):
        self.assertEqual(validate_url("https://pt.wikipedia.org/wiki/IA"), "https://pt.wikipedia.org/wiki/IA")
        for url in ["file:///etc/passwd", "javascript:alert(1)", "https://google.com@evil.test", "https://127.0.0.1", "https://www.google.com:9000/", "https://www.google.com\n.evil.test", "https://www.google.com.evil.test/", "https://user:password@www.google.com"]:
            with self.assertRaises(ValueError, msg=url):
                validate_url(url)
            self.assertIsNone(parse_tool_request("abre " + url))
        with patch("ivi.tools.webbrowser.open") as browser:
            with self.assertRaises(ValueError):
                ToolRegistry(platform="win32").execute(ToolRequest("open_url", "", "", {"url": "file:///secret"}))
            browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
