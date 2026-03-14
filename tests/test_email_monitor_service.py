import unittest

from app.models.email_monitor_models import EmailMonitorRule
from app.services.email_monitor_service import (
    build_message_hash,
    describe_imap_error,
    normalize_folder_list,
    rule_matches_message,
    select_incremental_uids,
)


class EmailMonitorServiceTestCase(unittest.TestCase):
    def test_rule_matches_sender_subject_and_body_keywords(self):
        rule = EmailMonitorRule(
            name='Financeiro',
            sender_pattern='*@stripe.com',
            subject_pattern='invoice',
            body_keywords_json=['paid', 'receipt'],
            folder_pattern='INBOX',
        )

        reason = rule_matches_message(
            rule,
            folder_name='INBOX',
            sender='Stripe Billing billing@stripe.com',
            subject='Your invoice is ready',
            body_text='The receipt was paid successfully.',
        )

        self.assertIsNotNone(reason)
        self.assertIn('remetente', reason or '')
        self.assertIn('assunto', reason or '')
        self.assertIn('palavras-chave', reason or '')

    def test_incremental_uid_selection_respects_last_seen_and_batch_limit(self):
        all_uids = [10, 11, 12, 13, 14, 15]
        selected = select_incremental_uids(all_uids, last_seen_uid=12, batch_size=2)
        self.assertEqual(selected, [14, 15])

    def test_message_hash_prefers_message_id_when_available(self):
        first = build_message_hash('<abc@example.com>', 'a@example.com', 'x', None, 'preview 1')
        second = build_message_hash('<abc@example.com>', 'b@example.com', 'y', None, 'preview 2')
        self.assertEqual(first, second)

    def test_normalize_folder_list_removes_duplicates_and_blanks(self):
        folders = normalize_folder_list(['INBOX', ' Financeiro ', '', 'INBOX'])
        self.assertEqual(folders, ['INBOX', 'Financeiro'])

    def test_describe_imap_error_translates_gmail_auth_failure(self):
        error = describe_imap_error(
            Exception(b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'),
            imap_host='imap.gmail.com',
            imap_port=993,
            use_ssl=True,
        )
        self.assertIn('Gmail', error)
        self.assertIn('senha de app', error)


if __name__ == '__main__':
    unittest.main()
