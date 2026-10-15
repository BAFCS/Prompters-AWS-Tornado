"""Verificación de credenciales AWS por perfil antes de cualquier escritura (Req. 4.11 y 8.12).

``check`` llama a ``sts:GetCallerIdentity`` con ``botocore.session.Session(profile=profile)``. Si el
perfil no existe, no hay credenciales, expiraron o STS no responde, escribe en stderr un mensaje que
nombra el perfil (``default`` si es ``None``) y lanza ``CredentialsError`` (``SystemExit`` con
código 2), de modo que el programa termina antes de escribir nada.
"""

from __future__ import annotations

import sys

import botocore.session
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
    ProfileNotFound,
)

DEFAULT_REGION = "us-east-1"
EXIT_CODE = 2


class CredentialsError(SystemExit):
    """Credenciales AWS ausentes, inválidas o expiradas para un perfil; termina con código 2."""

    def __init__(self, profile: str, message: str) -> None:
        """Guarda el perfil y el mensaje; el código de salida es ``EXIT_CODE``."""
        super().__init__(EXIT_CODE)
        self.profile = profile
        self.message = message

    def __str__(self) -> str:
        """Devuelve el mensaje (no el código de salida)."""
        return self.message


def _detail(exc: Exception) -> str:
    """Describe la causa de la falla en una frase corta."""
    if isinstance(exc, ProfileNotFound):
        return "el perfil no existe en la configuración de AWS"
    if isinstance(exc, NoCredentialsError):
        return "no se encontraron credenciales"
    if isinstance(exc, PartialCredentialsError):
        return "las credenciales están incompletas"
    if isinstance(exc, EndpointConnectionError):
        return "no se pudo contactar a STS para validarlas"
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        if code.startswith("ExpiredToken"):
            return f"el token expiró ({code})"
        return f"STS las rechazó ({code or 'error desconocido'})"
    return f"{type(exc).__name__}: {exc}"


def check(profile: str | None) -> str:
    """Llama a ``sts:GetCallerIdentity`` con el perfil y devuelve el ARN de la identidad.

    Si las credenciales no existen, son inválidas o expiraron, escribe en stderr
    "credenciales inválidas o expiradas para el perfil '<perfil>'; renueva y reintenta" con la causa
    y lanza ``CredentialsError``. La región es la del perfil o ``us-east-1``.
    """
    name = profile or "default"
    try:
        session = botocore.session.Session(profile=profile)
        region = session.get_config_variable("region") or DEFAULT_REGION
        client = session.create_client("sts", region_name=region)
        return str(client.get_caller_identity()["Arn"])
    except (BotoCoreError, ClientError) as exc:
        message = (
            f"credenciales inválidas o expiradas para el perfil '{name}'; renueva y reintenta"
            f" ({_detail(exc)})"
        )
        print(message, file=sys.stderr)
        raise CredentialsError(name, message) from exc
