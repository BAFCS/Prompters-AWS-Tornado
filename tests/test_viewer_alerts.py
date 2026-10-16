"""Pruebas de viewer_app/alerts.py: umbral, recorte de OpenStreetMap y correo (sin red ni AWS)."""

import email
import io
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "viewer"))

from viewer_app import alerts  # noqa: E402


def grid() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Grilla pequeña con un foco de 97 % en (-37, -72) y el resto bajo."""
    lat = np.arange(-35.0, -39.25, -0.25)
    lon = np.arange(-74.0, -69.75, 0.25)
    prob = np.full((len(lat), len(lon)), 0.3)
    i, j = int(np.argmin(abs(lat + 37))), int(np.argmin(abs(lon + 72)))
    prob[i, j] = 0.97
    prob[i, j + 1] = 0.96
    return prob, lat, lon


def fake_tile(z: int, x: int, y: int) -> bytes:
    """Un tile gris liso, como si viniera de OpenStreetMap."""
    out = io.BytesIO()
    Image.new("RGB", (256, 256), (220, 230, 220)).save(out, format="PNG")
    return out.getvalue()


class FakeSes:
    """Cliente SES falso: guarda lo enviado y falla con un destinatario dado."""

    def __init__(self, fail: str = "") -> None:
        self.sent: list[dict] = []
        self.fail = fail

    def send_email(self, **kwargs: object) -> dict:
        to = kwargs["Destination"]["ToAddresses"][0]  # type: ignore[index]
        if to == self.fail:
            raise RuntimeError("Email address is not verified")
        self.sent.append(kwargs)
        return {"MessageId": f"id-{len(self.sent)}"}


class HotspotTests(unittest.TestCase):
    def test_finds_max_and_extent(self) -> None:
        prob, lat, lon = grid()
        z = alerts.hotspot(prob, lat, lon, 0.95)
        assert z is not None
        self.assertAlmostEqual(z["prob"], 0.97)
        self.assertEqual((z["lat"], z["lon"]), (-37.0, -72.0))
        self.assertEqual(z["cells"], 2)
        self.assertEqual(z["lon_range"], (-72.0, -71.75))

    def test_none_below_threshold(self) -> None:
        prob, lat, lon = grid()
        self.assertIsNone(alerts.hotspot(prob, lat, lon, 0.98))

    def test_ignores_nan(self) -> None:
        prob, lat, lon = grid()
        prob[0, 0] = np.nan
        z = alerts.hotspot(prob, lat, lon, 0.95)
        assert z is not None
        self.assertAlmostEqual(z["prob"], 0.97)


class CropTests(unittest.TestCase):
    def test_png_with_marker(self) -> None:
        prob, lat, lon = grid()
        z = alerts.hotspot(prob, lat, lon, 0.95)
        assert z is not None
        png = alerts.crop_map(prob, lat, lon, z, 0.25, 0.95, fetch=fake_tile)
        img = Image.open(io.BytesIO(png))
        self.assertGreater(img.width, 100)
        self.assertGreater(img.height, 100)
        # El marcador del máximo es rojo (230, 57, 70): tiene que aparecer en el recorte.
        px = np.asarray(img.convert("RGB")).reshape(-1, 3)
        self.assertTrue(((px[:, 0] > 200) & (px[:, 1] < 90) & (px[:, 2] < 100)).any())

    def test_tiles_unavailable_still_returns_png(self) -> None:
        prob, lat, lon = grid()
        z = alerts.hotspot(prob, lat, lon, 0.95)
        assert z is not None

        def broken(z: int, x: int, y: int) -> bytes:
            raise OSError("sin red")

        png = alerts.crop_map(prob, lat, lon, z, 0.25, 0.95, fetch=broken)
        self.assertTrue(png.startswith(b"\x89PNG"))


class MessageTests(unittest.TestCase):
    def test_message_has_coordinates_and_attachment(self) -> None:
        prob, lat, lon = grid()
        z = alerts.hotspot(prob, lat, lon, 0.95)
        assert z is not None
        raw = alerts.message(z, fake_tile(0, 0, 0), "GOES-16 C13", 0.95, "a@b.cl")
        msg = email.message_from_bytes(raw)
        self.assertIn(
            "97.0 %", str(email.header.make_header(email.header.decode_header(msg["Subject"])))
        )
        self.assertEqual(msg["To"], "a@b.cl")
        text = next(p for p in msg.walk() if p.get_content_type() == "text/plain").get_payload(
            decode=True
        )
        self.assertIn(b"latitud -37,00, longitud -72,00", text)
        self.assertIn(b"openstreetmap.org/?mlat=-37.0000&mlon=-72.0000", text)
        names = [p.get_filename() for p in msg.walk() if p.get_filename()]
        self.assertIn("alerta_-37.00_-72.00.png", names)


class AlertTests(unittest.TestCase):
    def test_one_email_per_recipient_and_failures_isolated(self) -> None:
        prob, lat, lon = grid()
        ses = FakeSes(fail="b@b.cl")
        orig_send, orig_crop = alerts.send, alerts.crop_map
        alerts.send = lambda raw, to, client=None: orig_send(raw, to, ses)  # type: ignore[assignment]
        alerts.crop_map = lambda *a, **k: fake_tile(0, 0, 0)  # type: ignore[assignment]
        env = {"ALERT_EMAIL_TO": "a@b.cl, b@b.cl", "ALERT_THRESHOLD": "0.95"}
        import os

        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            out = alerts.alert(prob, lat, lon, 0.25, "prueba")
        finally:
            alerts.send, alerts.crop_map = orig_send, orig_crop
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        assert out is not None
        self.assertEqual(out["sent"], ["a@b.cl"])
        self.assertIn("b@b.cl", out["failed"])
        self.assertEqual(len(ses.sent), 1)

    def test_no_alert_below_threshold(self) -> None:
        prob, lat, lon = grid()
        prob[prob > 0.5] = 0.5
        self.assertIsNone(alerts.alert(prob, lat, lon, 0.25, "prueba"))


if __name__ == "__main__":
    unittest.main()
