import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

import requests

from app.core.config import settings


class AsaasGatewayError(Exception):
    def __init__(self, message: str, *, status_code: Optional[int] = None, payload: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}


class AsaasService:
    def __init__(self) -> None:
        if not settings.ASAAS_ACCESS_TOKEN:
            raise AsaasGatewayError("ASAAS_ACCESS_TOKEN não configurado.")

    def _headers(self) -> Dict[str, str]:
        return {
            "accept": "application/json",
            "content-type": "application/json",
            "access_token": settings.ASAAS_ACCESS_TOKEN,
            "User-Agent": settings.ASAAS_USER_AGENT,
        }

    def _build_url(self, path: str) -> str:
        base = settings.ASAAS_API_BASE_URL.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{base}{suffix}"

    def _extract_error_message(self, payload: Any) -> str:
        if isinstance(payload, dict):
            errors = payload.get("errors")
            if isinstance(errors, list) and errors:
                first_error = errors[0]
                if isinstance(first_error, dict):
                    description = first_error.get("description")
                    if description:
                        return str(description)
            for key in ("message", "error", "description"):
                if payload.get(key):
                    return str(payload[key])
        return "Erro inesperado ao comunicar com o Asaas."

    def _request(self, method: str, path: str, *, expected_status: Optional[int] = None, json: Optional[dict] = None) -> dict:
        response = requests.request(
            method,
            self._build_url(path),
            headers=self._headers(),
            json=json,
            timeout=settings.ASAAS_REQUEST_TIMEOUT_SECONDS,
        )

        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {}

        if expected_status and response.status_code != expected_status:
            raise AsaasGatewayError(
                self._extract_error_message(payload),
                status_code=response.status_code,
                payload=payload,
            )

        if not response.ok:
            raise AsaasGatewayError(
                self._extract_error_message(payload),
                status_code=response.status_code,
                payload=payload,
            )

        return payload if isinstance(payload, dict) else {}

    def ensure_customer(self, *, nome: str, email: str, external_reference: str, cpf_cnpj: Optional[str] = None, existing_customer_id: Optional[str] = None) -> str:
        if existing_customer_id:
            return existing_customer_id

        payload = {
            "name": nome[:100],
            "email": email,
            "externalReference": external_reference,
        }
        if cpf_cnpj:
            payload["cpfCnpj"] = cpf_cnpj
        customer = self._request("POST", "/customers", expected_status=200, json=payload)
        customer_id = customer.get("id")
        if not customer_id:
            raise AsaasGatewayError("Asaas não retornou o ID do cliente.", payload=customer)
        return str(customer_id)

    def create_pix_payment(
        self,
        *,
        customer_id: str,
        value: Decimal,
        due_date: datetime.date,
        description: str,
        external_reference: str,
    ) -> dict:
        payload = {
            "customer": customer_id,
            "billingType": "PIX",
            "value": float(value),
            "dueDate": due_date.isoformat(),
            "description": description[:500],
            "externalReference": external_reference,
        }
        return self._request("POST", "/payments", expected_status=200, json=payload)

    def get_pix_qr_code(self, payment_id: str) -> dict:
        return self._request("GET", f"/payments/{payment_id}/pixQrCode", expected_status=200)

    def get_payment(self, payment_id: str) -> dict:
        return self._request("GET", f"/payments/{payment_id}", expected_status=200)


    def delete_payment(self, payment_id: str) -> dict:
        return self._request("DELETE", f"/payments/{payment_id}", expected_status=200)
