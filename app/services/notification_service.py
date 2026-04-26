import requests

from app.core.config import settings

# Usamos o token da API para montar a URL de envio
BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

def escape_markdown_v2(text: str) -> str:
    """
    Escapa caracteres especiais para o modo MarkdownV2 do Telegram.
    """
    # Lista de caracteres que precisam ser escapados
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    # Adiciona uma barra invertida antes de cada caractere especial
    return "".join(f"\\{char}" if char in escape_chars else char for char in text)

def send_telegram_message(telegram_id: int, message_text: str, parse_mode: str = "MarkdownV2"):
    """
    Envia uma mensagem direta para um usuário do Telegram via HTTP.
    
    Usamos MarkdownV2 para consistência com o bot (ex: `*bold*`, `_italic_`, `` `code` ``).
    """
    payload = {
        "chat_id": telegram_id,
        "text": message_text,
        "parse_mode": parse_mode
    }
    
    # Usamos 'requests' que já está nas dependências da API
    try:
        response = requests.post(TELEGRAM_API_URL, json=payload, timeout=5)
        response.raise_for_status() # Lança erro se for 4xx or 5xx
        
        if response.json().get("ok") is True:
            print(f"Notificação enviada com sucesso para {telegram_id}.")
        else:
            print(f"Erro da API Telegram ao enviar para {telegram_id}: {response.text}")
            
    except requests.exceptions.RequestException as e:
        # Se a API do Telegram estiver fora ou o token for inválido
        print(f"ERRO CRÍTICO ao enviar notificação para {telegram_id}: {e}")
    except Exception as e_geral:
        print(f"Erro inesperado no notification_service: {e_geral}")


def send_openai_invite_sent_message(
    *,
    telegram_id: int,
    email_cliente: str,
    produto_nome: str,
    workspace_name: str | None = None,
):
    produto_f = escape_markdown_v2(produto_nome)
    email_f = escape_markdown_v2(email_cliente)
    workspace_block = ""
    if workspace_name:
        workspace_f = escape_markdown_v2(workspace_name)
        workspace_block = f"\nWorkspace: *{workspace_f}*"

    message = (
        "✅ *Convite enviado com sucesso\\!*"
        f"\n\nO convite do seu acesso para *{produto_f}* foi enviado para:"
        f"\n`{email_f}`"
        f"{workspace_block}"
        "\n\nConfira tambem:"
        "\n\\- caixa principal"
        "\n\\- spam"
        "\n\\- promocoes"
        "\n\\- lixeira"
        "\n\nAssim que receber o email, aceite o convite e depois abra o ChatGPT para usar o espaco de trabalho\\."
    )
    send_telegram_message(telegram_id=telegram_id, message_text=message)


def send_openai_invite_failure_admin_alert(
    *,
    status: str,
    conta_mae_login: str,
    email_cliente: str,
    job_id: str,
    pedido_id: str | None = None,
    produto_nome: str | None = None,
    motivo: str | None = None,
    attempt_count: int | None = None,
    next_retry_at: str | None = None,
):
    admin_id = settings.ADMIN_TELEGRAM_ID
    if not admin_id:
        print("AVISO: ADMIN_TELEGRAM_ID nao configurado; alerta de convite nao enviado.")
        return

    status_f = escape_markdown_v2(status)
    conta_mae_f = escape_markdown_v2(conta_mae_login)
    email_f = escape_markdown_v2(email_cliente)
    job_id_f = escape_markdown_v2(job_id)
    pedido_f = escape_markdown_v2(pedido_id) if pedido_id else "N/A"
    produto_f = escape_markdown_v2(produto_nome) if produto_nome else "Produto nao identificado"
    motivo_f = escape_markdown_v2((motivo or "Falha sem detalhe.").strip())
    tentativa_block = ""
    if attempt_count is not None:
        tentativa_block += f"\nTentativa: *{attempt_count}*"
    if next_retry_at:
        retry_f = escape_markdown_v2(next_retry_at)
        tentativa_block += f"\nProxima tentativa: `{retry_f}`"

    message = (
        "🚨 *Falha no envio automatico de convite*"
        f"\n\nStatus: *{status_f}*"
        f"\nProduto: *{produto_f}*"
        f"\nConta\\-mae: `{conta_mae_f}`"
        f"\nEmail do cliente: `{email_f}`"
        f"\nPedido: `{pedido_f}`"
        f"\nJob: `{job_id_f}`"
        f"{tentativa_block}"
        f"\n\nMotivo:\n{motivo_f}"
    )
    send_telegram_message(telegram_id=admin_id, message_text=message)


def send_openai_member_removal_failure_admin_alert(
    *,
    status: str,
    conta_mae_login: str,
    email_cliente: str,
    job_id: str,
    pedido_id: str | None = None,
    produto_nome: str | None = None,
    motivo: str | None = None,
    attempt_count: int | None = None,
    next_retry_at: str | None = None,
):
    admin_id = settings.ADMIN_TELEGRAM_ID
    if not admin_id:
        print("AVISO: ADMIN_TELEGRAM_ID nao configurado; alerta de remocao nao enviado.")
        return

    status_f = escape_markdown_v2(status)
    conta_mae_f = escape_markdown_v2(conta_mae_login)
    email_f = escape_markdown_v2(email_cliente)
    job_id_f = escape_markdown_v2(job_id)
    pedido_f = escape_markdown_v2(pedido_id) if pedido_id else "N/A"
    produto_f = escape_markdown_v2(produto_nome) if produto_nome else "Produto nao identificado"
    motivo_f = escape_markdown_v2((motivo or "Falha sem detalhe.").strip())
    tentativa_block = ""
    if attempt_count is not None:
        tentativa_block += f"\nTentativa: *{attempt_count}*"
    if next_retry_at:
        retry_f = escape_markdown_v2(next_retry_at)
        tentativa_block += f"\nProxima tentativa: `{retry_f}`"

    message = (
        "🚨 *Falha na remocao automatica do workspace ChatGPT*"
        f"\n\nStatus: *{status_f}*"
        f"\nProduto: *{produto_f}*"
        f"\nConta\\-mae: `{conta_mae_f}`"
        f"\nEmail do cliente: `{email_f}`"
        f"\nPedido: `{pedido_f}`"
        f"\nJob: `{job_id_f}`"
        f"{tentativa_block}"
        f"\n\nMotivo:\n{motivo_f}"
    )
    send_telegram_message(telegram_id=admin_id, message_text=message)
