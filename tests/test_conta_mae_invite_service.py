import unittest
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace

from app.services.conta_mae_invite_service import (
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
