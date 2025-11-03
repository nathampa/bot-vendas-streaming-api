import requests
from app.core.config import settings
import html

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