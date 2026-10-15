"""Pruebas de la verificación de credenciales (``scripts/app/awsauth.py``), sin red ni AWS."""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "app"))
sys.path.insert(0, str(ROOT / "tests"))

import awsauth  # noqa: E402
from app_synthetic import NoNetworkMixin  # noqa: E402

ARN = "arn:aws:sts::123456789012:assumed-role/rol/sesion"


def _session(identity: dict | None = None, error: Exception | None = None) -> mock.MagicMock:
    """Sesión falsa cuyo cliente STS devuelve ``identity`` o lanza ``error``."""
    session = mock.MagicMock()
    session.get_config_variable.return_value = None
    client = session.create_client.return_value
    if error is not None:
        client.get_caller_identity.side_effect = error
    else:
        client.get_caller_identity.return_value = identity
    return session


def _expired() -> ClientError:
    """Error de STS para un token de sesión expirado."""
    return ClientError(
        {"Error": {"Code": "ExpiredTokenException", "Message": "expired"}}, "GetCallerIdentity"
    )


class CheckTest(NoNetworkMixin):
    """``check`` devuelve el ARN o termina con un mensaje que nombra el perfil."""

    def test_success_returns_arn_with_default_region(self) -> None:
        """Con credenciales válidas devuelve el ARN y usa us-east-1 si el perfil no tiene región."""
        session = _session(identity={"Arn": ARN, "Account": "123456789012"})
        with mock.patch.object(awsauth.botocore.session, "Session", return_value=session) as cls:
            self.assertEqual(awsauth.check("gpu"), ARN)
        cls.assert_called_once_with(profile="gpu")
        session.create_client.assert_called_once_with("sts", region_name="us-east-1")

    def test_expired_token_names_profile(self) -> None:
        """Un token expirado termina con código 2 y un mensaje con el perfil y la causa."""
        session = _session(error=_expired())
        stderr = io.StringIO()
        with (
            mock.patch.object(awsauth.botocore.session, "Session", return_value=session),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(awsauth.CredentialsError) as ctx,
        ):
            awsauth.check("gpu")
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(ctx.exception.profile, "gpu")
        self.assertIn("perfil 'gpu'", str(ctx.exception))
        self.assertIn("ExpiredTokenException", str(ctx.exception))
        self.assertIn("perfil 'gpu'", stderr.getvalue())

    def test_none_profile_is_reported_as_default(self) -> None:
        """Sin perfil el mensaje dice 'default'."""
        session = _session(error=_expired())
        with (
            mock.patch.object(awsauth.botocore.session, "Session", return_value=session) as cls,
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(awsauth.CredentialsError) as ctx,
        ):
            awsauth.check(None)
        cls.assert_called_once_with(profile=None)
        self.assertIn("perfil 'default'", str(ctx.exception))

    def test_missing_profile_fails_without_network(self) -> None:
        """Un perfil inexistente (botocore real, sin red) termina con CredentialsError."""
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(awsauth.CredentialsError) as ctx,
        ):
            awsauth.check("perfil-que-no-existe-xyz")
        self.assertIn("perfil 'perfil-que-no-existe-xyz'", str(ctx.exception))
        self.assertIn("no existe", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
