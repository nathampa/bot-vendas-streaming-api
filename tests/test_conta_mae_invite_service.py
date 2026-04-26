import unittest
import datetime
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace

from app.services import conta_mae_invite_service as invite_service
from app.services.conta_mae_invite_service import (
    conta_mae_session_within_retention,
    delete_conta_mae_session_storage,
    extract_workspace_name_from_html,
    generate_fstr_workspace_name,
    get_conta_mae_workspace_name,
    normalize_workspace_name,
    write_workspace_rename_marker,
)


class ContaMaeInviteServiceTestCase(unittest.TestCase):
    def test_normalize_workspace_name_discards_navigation_label(self):
        self.assertIsNone(normalize_workspace_name("Back to chat"))

    def test_normalize_workspace_name_extracts_name_from_invite_header(self):
        self.assertEqual(
            normalize_workspace_name("Invite members to the Netcourrier workspace"),
            "Netcourrier",
        )

    def test_extract_workspace_name_from_html_reads_workspace_payload(self):
        html_content = """
        <script>
        window.__reactRouterContext.streamController.enqueue(
            "[\\"workspaceName\\",\\"Netcourrier\\"]"
        );
        </script>
        """

        self.assertEqual(extract_workspace_name_from_html(html_content), "Netcourrier")

    def test_extract_workspace_name_from_html_reads_escaped_workspace_payload(self):
        html_content = '\\"workspaceName\\",\\"Netcourrier\\"'

        self.assertEqual(extract_workspace_name_from_html(html_content), "Netcourrier")

    def test_generate_fstr_workspace_name_uses_expected_prefix_and_suffix(self):
        self.assertRegex(generate_fstr_workspace_name(), r"^FStr[#_-]\d{4,6}$")

    def test_get_conta_mae_workspace_name_reads_session_marker(self):
        with tempfile.TemporaryDirectory() as session_path:
            write_workspace_rename_marker(Path(session_path), "FStr#1234")
            conta = SimpleNamespace(session_storage_path=session_path)

            self.assertEqual(get_conta_mae_workspace_name(conta), "FStr#1234")

    def test_conta_mae_session_within_retention_uses_expiration_plus_30_days(self):
        reference_date = datetime.date(2026, 4, 26)
        self.assertTrue(
            conta_mae_session_within_retention(
                SimpleNamespace(data_expiracao=datetime.date(2026, 3, 28)),
                reference_date,
            )
        )
        self.assertFalse(
            conta_mae_session_within_retention(
                SimpleNamespace(data_expiracao=datetime.date(2026, 3, 27)),
                reference_date,
            )
        )

    def test_delete_conta_mae_session_storage_removes_directory_inside_session_root(self):
        original_root = invite_service.settings.OPENAI_INVITE_SESSION_ROOT
        try:
            with tempfile.TemporaryDirectory() as root:
                invite_service.settings.OPENAI_INVITE_SESSION_ROOT = root
                session_path = Path(root) / "conta_mae_1"
                session_path.mkdir()
                (session_path / "state.txt").write_text("ok", encoding="utf-8")
                conta = SimpleNamespace(session_storage_path=str(session_path))

                result = delete_conta_mae_session_storage(conta)

                self.assertEqual(result["status"], "CLEANED")
                self.assertIsNone(conta.session_storage_path)
                self.assertFalse(session_path.exists())
        finally:
            invite_service.settings.OPENAI_INVITE_SESSION_ROOT = original_root

    def test_delete_conta_mae_session_storage_skips_paths_outside_session_root(self):
        original_root = invite_service.settings.OPENAI_INVITE_SESSION_ROOT
        try:
            with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside_root:
                invite_service.settings.OPENAI_INVITE_SESSION_ROOT = root
                session_path = Path(outside_root) / "conta_mae_1"
                session_path.mkdir()
                conta = SimpleNamespace(session_storage_path=str(session_path))

                result = delete_conta_mae_session_storage(conta)

                self.assertEqual(result["status"], "SKIPPED")
                self.assertEqual(conta.session_storage_path, str(session_path))
                self.assertTrue(session_path.exists())
        finally:
            invite_service.settings.OPENAI_INVITE_SESSION_ROOT = original_root


class OpenAIInviteHostRunnerExtractionTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runner_path = Path(__file__).resolve().parents[1] / "scripts" / "openai_invite_host_runner.py"
        spec = importlib.util.spec_from_file_location("openai_invite_host_runner", runner_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        cls.runner = module

    def test_runner_discards_navigation_label(self):
        self.assertIsNone(self.runner.normalize_workspace_name("Back to chat"))

    def test_runner_extracts_name_from_invite_header(self):
        self.assertEqual(
            self.runner.normalize_workspace_name("Invite members to the Netcourrier workspace"),
            "Netcourrier",
        )

    def test_runner_extracts_workspace_name_from_html_payload(self):
        html_content = """
        <script>
        window.__reactRouterContext.streamController.enqueue(
            "[\\"workspaceName\\",\\"Netcourrier\\"]"
        );
        </script>
        """

        self.assertEqual(self.runner.extract_workspace_name_from_html(html_content), "Netcourrier")

    def test_runner_extracts_workspace_name_from_escaped_payload(self):
        html_content = '\\"workspaceName\\",\\"Netcourrier\\"'

        self.assertEqual(self.runner.extract_workspace_name_from_html(html_content), "Netcourrier")

    def test_runner_generate_fstr_workspace_name_uses_expected_prefix_and_suffix(self):
        self.assertRegex(self.runner.generate_fstr_workspace_name(), r"^FStr[#_-]\d{4,6}$")

    def test_runner_builds_home_url_from_members_url(self):
        self.assertEqual(
            self.runner.build_openai_home_url("https://chatgpt.com/admin?locale=pt-BR"),
            "https://chatgpt.com/?locale=pt-BR",
        )


if __name__ == "__main__":
    unittest.main()
