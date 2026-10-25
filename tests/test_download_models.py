"""Offline download contracts: fixtures are bytes, never executable AI models."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from ivi.download_models import SPECS, download_component, main


REVISION = "a" * 40
PAYLOAD = b"local downloader contract fixture, not an AI model"
PAYLOAD_HASH = hashlib.sha256(PAYLOAD).hexdigest()


def sibling(filename: str, *, checksum: str = PAYLOAD_HASH) -> SimpleNamespace:
    return SimpleNamespace(rfilename=filename, lfs={"sha256": checksum})


def model_info(files: list[SimpleNamespace], *, revision: str = REVISION) -> SimpleNamespace:
    return SimpleNamespace(sha=revision, siblings=files, card_data={"license": "fixture-license"})


class FixtureAPI:
    def __init__(self, infos: dict[str, SimpleNamespace]):
        self.infos = infos
        self.requests: list[tuple[str, dict]] = []

    def model_info(self, repo: str, **kwargs) -> SimpleNamespace:
        self.requests.append((repo, kwargs))
        return self.infos[repo]


class FixtureDownload:
    def __init__(self):
        self.requests: list[dict] = []

    def __call__(self, **kwargs) -> str:
        self.requests.append(kwargs)
        path = Path(kwargs["local_dir"]) / kwargs["filename"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PAYLOAD)
        return str(path)


@contextlib.contextmanager
def hub_module(api: FixtureAPI, download: FixtureDownload):
    module = ModuleType("huggingface_hub")
    module.HfApi = lambda **kwargs: api
    module.hf_hub_download = download
    with patch.dict("sys.modules", {"huggingface_hub": module}):
        yield


@contextlib.contextmanager
def current_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class DownloadModelsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.download = FixtureDownload()
        self.llm_name = SPECS["llm"]["required"][0]
        self.llm_repo = SPECS["llm"]["repo"]

    def _llm_api(self, *, checksum: str = PAYLOAD_HASH) -> FixtureAPI:
        return FixtureAPI({self.llm_repo: model_info([sibling(self.llm_name, checksum=checksum)])})

    def _main(self, args: list[str], api: FixtureAPI) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with hub_module(api, self.download), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(args)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_file_requests_use_resolved_commit_instead_of_mutable_main(self):
        api = self._llm_api()
        with contextlib.redirect_stdout(io.StringIO()):
            result = download_component(api, self.download, "llm", self.root, None)
        self.assertEqual(api.requests[0][1]["revision"], "main")
        self.assertTrue(self.download.requests)
        for request in self.download.requests:
            self.assertEqual(request["revision"], REVISION)
            self.assertIs(request["token"], False)
        self.assertEqual(result["revision"], REVISION)
        self.assertEqual(result["files"][0]["sha256"], PAYLOAD_HASH)
        self.assertEqual(result["repository_license_metadata"], "fixture-license")

    def test_explicit_revision_is_used_for_resolution(self):
        api = self._llm_api()
        with contextlib.redirect_stdout(io.StringIO()):
            download_component(api, self.download, "llm", self.root, "b" * 40)
        self.assertEqual(api.requests[0][1]["revision"], "b" * 40)
        self.assertEqual(self.download.requests[0]["revision"], REVISION)

    def test_missing_required_file_refuses_before_downloading(self):
        api = FixtureAPI({self.llm_repo: model_info([])})
        with self.assertRaisesRegex(RuntimeError, "Arquivos ausentes"):
            download_component(api, self.download, "llm", self.root, None)
        self.assertEqual(self.download.requests, [])

    def test_stt_refuses_missing_vocabulary_before_downloading(self):
        spec = SPECS["stt"]
        api = FixtureAPI({spec["repo"]: model_info([sibling(name) for name in spec["required"]])})
        with self.assertRaisesRegex(RuntimeError, "vocabulary"):
            download_component(api, self.download, "stt", self.root, None)
        self.assertEqual(self.download.requests, [])

    def test_stt_downloads_only_explicit_ctranslate2_files_and_metadata(self):
        spec = SPECS["stt"]
        files = spec["required"] + ["vocabulary.json", "README.md", "pytorch_model.bin", "unsafe.pkl"]
        api = FixtureAPI({spec["repo"]: model_info([sibling(name) for name in files])})
        with contextlib.redirect_stdout(io.StringIO()):
            result = download_component(api, self.download, "stt", self.root, None)
        names = {request["filename"] for request in self.download.requests}
        self.assertEqual(names, set(spec["required"] + ["vocabulary.json", "README.md"]))
        self.assertEqual(len(result["files"]), len(names))

    def test_invalid_registry_commit_refuses_download(self):
        api = FixtureAPI({self.llm_repo: model_info([sibling(self.llm_name)], revision="main")})
        with self.assertRaisesRegex(RuntimeError, "commit verificavel"):
            download_component(api, self.download, "llm", self.root, None)
        self.assertEqual(self.download.requests, [])

    def test_sha_mismatch_quarantines_file_and_does_not_write_success_manifest(self):
        code, stdout, stderr = self._main(["--component", "llm", "--directory", str(self.root)], self._llm_api(checksum="0" * 64))
        self.assertEqual(code, 1)
        self.assertIn("SHA256 invalido", stderr)
        self.assertNotIn("Manifesto:", stdout)
        self.assertFalse((self.root / "manifest.json").exists())
        self.assertFalse((self.root / "llm" / self.llm_name).exists())
        quarantined = list((self.root / "llm").glob(self.llm_name + ".unverified-*"))
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_bytes(), PAYLOAD)

    def test_first_component_failure_preserves_existing_manifest_bytes(self):
        original = '{"components":{"tts":{"revision":"previous","files":[]}},"user_note":"preserve me"}\n'
        (self.root / "manifest.json").write_text(original, encoding="utf-8")
        api = FixtureAPI({self.llm_repo: model_info([])})
        code, _, _ = self._main(["--component", "llm", "--directory", str(self.root)], api)
        self.assertEqual(code, 1)
        self.assertEqual((self.root / "manifest.json").read_text("utf-8"), original)

    def test_later_component_failure_preserves_previous_and_completed_components(self):
        previous_tts = {"revision": "previous-tts", "files": [{"path": "tts/existing.onnx"}]}
        (self.root / "manifest.json").write_text(json.dumps({"components": {"tts": previous_tts}}), encoding="utf-8")
        api = self._llm_api()
        api.infos[SPECS["stt"]["repo"]] = model_info([])
        code, stdout, stderr = self._main(["--directory", str(self.root)], api)
        self.assertEqual(code, 1)
        saved = json.loads((self.root / "manifest.json").read_text("utf-8"))["components"]
        self.assertEqual(saved["tts"], previous_tts)
        self.assertEqual(saved["llm"]["revision"], REVISION)
        self.assertNotIn("stt", saved)
        self.assertIn("Arquivos ausentes", stderr)
        self.assertNotIn("Manifesto:", stdout)

    def test_success_does_not_create_or_overwrite_dotenv(self):
        environment_file = self.root / ".env"
        original = "IVI_CPU_THREADS=1\nUSER_SETTING=preserve\n"
        environment_file.write_text(original, encoding="utf-8")
        with current_directory(self.root):
            code, stdout, stderr = self._main(["--component", "llm", "--directory", str(self.root / "models")], self._llm_api())
        self.assertEqual(code, 0, stderr)
        self.assertEqual(environment_file.read_text("utf-8"), original)
        self.assertIn("IVI_LLM_MODEL=", stdout)
        self.assertIn("nenhum arquivo .env foi alterado", stdout)

    def test_invalid_existing_manifest_is_preserved(self):
        original = '{"components": ["not-a-map"]}'
        (self.root / "manifest.json").write_text(original, encoding="utf-8")
        code, _, stderr = self._main(["--component", "llm", "--directory", str(self.root)], self._llm_api())
        self.assertEqual(code, 1)
        self.assertIn("formato invalido", stderr)
        self.assertEqual((self.root / "manifest.json").read_text("utf-8"), original)
        self.assertEqual(self.download.requests, [])

    def test_list_is_offline_and_does_not_create_output_directory(self):
        target = self.root / "must-not-be-created"
        output = io.StringIO()
        with patch.dict("sys.modules", {"huggingface_hub": None}), contextlib.redirect_stdout(output):
            code = main(["--list", "--directory", str(target)])
        self.assertEqual(code, 0)
        self.assertIn(self.llm_repo, output.getvalue())
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
