import unittest

from app.services.conta_mae_invite_service import (
    extract_workspace_name_from_html,
    normalize_workspace_name,
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


if __name__ == "__main__":
    unittest.main()
