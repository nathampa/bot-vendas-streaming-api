from decimal import Decimal
import unittest

from app.models.base import InviteProviderProduto, TipoEntregaProduto
from app.models.produto_models import Produto


class ProdutoInviteProviderTestCase(unittest.TestCase):
    def test_openai_automation_requires_solicita_email_and_openai_provider(self):
        produto = Produto(
            nome="ChatGPT PRO",
            preco=Decimal("29.90"),
            tipo_entrega=TipoEntregaProduto.SOLICITA_EMAIL,
            invite_provider=InviteProviderProduto.OPENAI,
        )

        self.assertTrue(produto.uses_openai_invite_automation())

    def test_openai_provider_is_ignored_for_other_delivery_types(self):
        produto = Produto(
            nome="ChatGPT PRO",
            preco=Decimal("29.90"),
            tipo_entrega=TipoEntregaProduto.AUTOMATICA,
            invite_provider=InviteProviderProduto.OPENAI,
        )

        self.assertFalse(produto.uses_openai_invite_automation())

    def test_none_provider_does_not_enable_openai_automation(self):
        produto = Produto(
            nome="Canva Pro",
            preco=Decimal("19.90"),
            tipo_entrega=TipoEntregaProduto.SOLICITA_EMAIL,
            invite_provider=InviteProviderProduto.NONE,
        )

        self.assertFalse(produto.uses_openai_invite_automation())


if __name__ == "__main__":
    unittest.main()
