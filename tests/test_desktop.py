"""Windows launcher contracts with mocks; no desktop hardware validation."""

from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, call, patch

from ivi import __version__
from ivi.config import Settings
from ivi import desktop


class DesktopTests(unittest.TestCase):
    def test_windows_shutdown_gives_owned_server_time_to_close_its_model(self):
        from unittest.mock import Mock
        process = Mock()
        process.poll.return_value = None
        with patch.object(desktop.sys, "platform", "win32"), patch.object(desktop.signal, "CTRL_BREAK_EVENT", 12345, create=True):
            desktop._stop_owned_server(process)
        process.send_signal.assert_called_once_with(12345)
        process.wait.assert_called_once_with(timeout=35)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def setUp(self):
        self.stack = ExitStack()
        self.temporary = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.settings = Settings(data_dir=self.temporary / "data", port=18765)
        self.url = "http://127.0.0.1:18765"
        self.browser = self.temporary / "Program Files" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        self.status = {"name": "I.V.I.", "version": __version__}
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.stack.enter_context(redirect_stdout(self.stdout))
        self.stack.enter_context(redirect_stderr(self.stderr))

    def tearDown(self):
        self.stack.close()

    def patch(self, name, *arguments, **keywords):
        return self.stack.enter_context(patch("ivi.desktop." + name, *arguments, **keywords))

    def test_browser_discovery_uses_standard_locations_and_prefers_edge(self):
        x86 = self.temporary / "Program Files (x86)"
        programs = self.temporary / "Program Files"
        local = self.temporary / "AppData" / "Local"
        edge = local / "Microsoft/Edge/Application/msedge.exe"
        chrome = programs / "Google/Chrome/Application/chrome.exe"
        edge.parent.mkdir(parents=True)
        chrome.parent.mkdir(parents=True)
        edge.write_bytes(b"fixture, not an executable")
        chrome.write_bytes(b"fixture, not an executable")
        with patch.dict(desktop.os.environ, {"PROGRAMFILES(X86)": str(x86), "PROGRAMFILES": str(programs), "LOCALAPPDATA": str(local)}, clear=True):
            self.assertEqual(desktop.find_browser(), edge)
            edge.unlink()
            self.assertEqual(desktop.find_browser(), chrome)
            chrome.unlink()
            self.assertIsNone(desktop.find_browser())

    def test_browser_command_preserves_paths_as_single_arguments_and_fullscreen(self):
        profile = self.temporary / "profile with spaces"
        command = desktop.build_browser_command(self.browser, self.url + "/", profile)
        self.assertEqual(command[0], str(self.browser))
        self.assertIn("--app=" + self.url, command)
        self.assertIn("--start-fullscreen", command)
        self.assertIn("--user-data-dir=" + str(profile), command)
        self.assertEqual(sum(argument.startswith("--user-data-dir=") for argument in command), 1)
        for local in ["http://localhost:18765", "http://[::1]:18765"]:
            self.assertIn("--app=" + local, desktop.build_browser_command(self.browser, local, profile))

    def test_browser_command_rejects_remote_urls_credentials_paths_and_bad_ports(self):
        for url in [
            "https://127.0.0.1:18765", "http://evil.example:18765", "file:///etc/passwd",
            "http://user:pass@127.0.0.1:18765", "http://127.0.0.1:18765/other",
            "http://127.0.0.1:18765/?redirect=evil", "http://127.0.0.1:18765/#fragment",
            "http://127.0.0.1:80", "http://127.0.0.1:99999", "http://127.0.0.1:bad",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                desktop.build_browser_command(self.browser, url, self.temporary)

    def test_actual_loopback_status_checks_name_version_and_invalid_payloads(self):
        response = {"status": 200, "body": json.dumps(self.status).encode()}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(response["status"])
                self.end_headers()
                self.wfile.write(response["body"])

            def log_message(self, *arguments):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            self.assertEqual(desktop.read_server_status(url), self.status)
            self.assertTrue(desktop.server_ready(url))
            for body in [b"not json", b"[]", b"x" * 65537]:
                response["body"] = body
                self.assertIsNone(desktop.read_server_status(url))
            for payload in [{"name": "other", "version": __version__}, {"name": "I.V.I.", "version": "0.0-old"}]:
                response["body"] = json.dumps(payload).encode()
                self.assertFalse(desktop.server_ready(url))
            response["status"] = 503
            self.assertIsNone(desktop.read_server_status(url))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_windows_guard_precedes_network_browser_and_process_actions(self):
        self.patch("sys.platform", "linux")
        status = self.patch("read_server_status")
        process = self.patch("subprocess.Popen")
        browser = self.patch("webbrowser.open")
        with self.assertRaisesRegex(RuntimeError, "Windows"):
            desktop.launch(self.settings)
        status.assert_not_called()
        process.assert_not_called()
        browser.assert_not_called()

    def test_status_probe_refuses_redirects_instead_of_following_other_destinations(self):
        followed = []
        payload = json.dumps(self.status).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/api/status":
                    self.send_response(302)
                    self.send_header("Location", "/redirect-target")
                    self.end_headers()
                else:
                    followed.append(self.path)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(payload)

            def log_message(self, *arguments):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        try:
            self.assertIsNone(desktop.read_server_status(f"http://127.0.0.1:{server.server_port}"))
            self.assertEqual(followed, [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_reusing_matching_server_never_stops_or_waits_for_it(self):
        self.patch("sys.platform", "win32")
        self.patch("read_server_status", return_value=self.status)
        self.patch("find_browser", return_value=self.browser)
        process = self.patch("subprocess.Popen")
        stop = self.patch("_stop_owned_server")
        self.assertEqual(desktop.launch(self.settings), 0)
        process.assert_called_once()
        arguments, options = process.call_args
        self.assertIn("--start-fullscreen", arguments[0])
        self.assertFalse(options["shell"])
        process.return_value.wait.assert_not_called()
        stop.assert_not_called()

    def test_incompatible_or_occupied_listener_is_not_replaced(self):
        self.patch("sys.platform", "win32")
        process = self.patch("subprocess.Popen")
        status = self.patch("read_server_status", return_value={"name": "I.V.I.", "version": "old"})
        with self.assertRaisesRegex(RuntimeError, "outra versão"):
            desktop.launch(self.settings)
        status.return_value = None
        self.patch("_port_available", return_value=False)
        with self.assertRaisesRegex(RuntimeError, "ocupada"):
            desktop.launch(self.settings)
        process.assert_not_called()

    def test_owned_server_start_uses_explicit_python_argv_and_cleans_only_it(self):
        self.patch("sys.platform", "win32")
        self.patch("read_server_status", return_value=None)
        self.patch("_port_available", return_value=True)
        ready = self.patch("server_ready", side_effect=[False, True])
        self.patch("time.sleep")
        self.patch("find_browser", return_value=self.browser)
        owned, browser_process = MagicMock(), MagicMock()
        owned.poll.return_value = None
        owned.wait.return_value = 0
        process = self.patch("subprocess.Popen", side_effect=[owned, browser_process])
        stop = self.patch("_stop_owned_server")
        self.assertEqual(desktop.launch(self.settings), 0)
        self.assertEqual(process.call_count, 2)
        arguments, options = process.call_args_list[0]
        self.assertEqual(arguments[0], [desktop.sys.executable, "-m", "ivi", "--port", "18765"])
        self.assertFalse(options["shell"])
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertTrue((self.settings.data_dir / "desktop-server.log").is_file())
        self.assertEqual(ready.call_count, 2)
        owned.wait.assert_called_once_with()
        browser_process.wait.assert_not_called()
        stop.assert_called_once_with(owned)

    def test_failed_owned_start_returns_diagnostic_and_cleans_owned_process(self):
        self.patch("sys.platform", "win32")
        self.patch("read_server_status", return_value=None)
        self.patch("_port_available", return_value=True)
        self.patch("server_ready", return_value=False)
        owned = MagicMock()
        owned.poll.return_value = 1
        self.patch("subprocess.Popen", return_value=owned)
        stop = self.patch("_stop_owned_server")
        browser = self.patch("find_browser")
        with self.assertRaisesRegex(RuntimeError, "não iniciou"):
            desktop.launch(self.settings)
        browser.assert_not_called()
        stop.assert_called_once_with(owned)

    def test_startup_timeout_still_cleans_owned_process(self):
        self.patch("sys.platform", "win32")
        self.patch("read_server_status", return_value=None)
        self.patch("_port_available", return_value=True)
        self.patch("server_ready", return_value=False)
        self.patch("time.monotonic", side_effect=[0, 21])
        owned = MagicMock()
        owned.poll.return_value = None
        self.patch("subprocess.Popen", return_value=owned)
        stop = self.patch("_stop_owned_server")
        with self.assertRaisesRegex(RuntimeError, "demorou"):
            desktop.launch(self.settings)
        stop.assert_called_once_with(owned)

    def test_missing_or_failed_app_browser_falls_back_without_claiming_fullscreen(self):
        self.patch("sys.platform", "win32")
        self.patch("read_server_status", return_value=self.status)
        finder = self.patch("find_browser", return_value=None)
        browser = self.patch("webbrowser.open", return_value=True)
        self.assertEqual(desktop.launch(self.settings), 0)
        browser.assert_called_once_with(self.url, new=1)
        self.assertIn("Use o botão Tela cheia", self.stdout.getvalue())
        finder.return_value = self.browser
        self.patch("subprocess.Popen", side_effect=OSError("browser unavailable"))
        self.assertEqual(desktop.launch(self.settings), 0)
        self.assertEqual(browser.call_count, 2)
        browser.return_value = False
        with self.assertRaisesRegex(RuntimeError, "Não consegui abrir o navegador"):
            desktop.launch(self.settings)

    def test_stop_helper_terminates_then_kills_only_if_timeout(self):
        owned = MagicMock()
        owned.poll.return_value = None
        owned.wait.side_effect = [subprocess.TimeoutExpired("server", 8), 0]
        desktop._stop_owned_server(owned)
        owned.terminate.assert_called_once_with()
        owned.kill.assert_called_once_with()
        self.assertEqual(owned.wait.call_args_list, [call(timeout=8), call(timeout=5)])
        exited = MagicMock()
        exited.poll.return_value = 0
        desktop._stop_owned_server(exited)
        exited.terminate.assert_not_called()
        exited.kill.assert_not_called()

    def test_main_reports_setup_errors_with_nonzero_result(self):
        self.patch("Settings.from_env", side_effect=ValueError("invalid local configuration"))
        self.assertEqual(desktop.main(), 1)
        self.assertIn("invalid local configuration", self.stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
