"""Alerta por correo de la página «Predecir»: si alguna celda supera el umbral, envía un correo.

El correo lleva las coordenadas de la celda más probable, el rango de latitud y longitud de la zona
sobre el umbral, un enlace a OpenStreetMap y, adjunto, un recorte del mapa de OpenStreetMap con las
celdas pintadas en la escala del visor. Se envía con Amazon SES desde la máquina del visor, con el
rol de la instancia (permiso ``ses:SendRawEmail`` limitado al remitente).

Variables de entorno (todas opcionales):

- ``ALERT_THRESHOLD``: umbral de probabilidad, entre 0 y 1 (por defecto 0.95).
- ``ALERT_EMAIL_FROM``: remitente verificado en SES.
- ``ALERT_EMAIL_TO``: destinatarios separados por comas. Mientras la cuenta de SES esté en modo
  sandbox, cada destinatario debe estar verificado en SES; a los que no lo estén no les llega.
- ``ALERT_REGION``: región de SES (por defecto us-east-1).
"""

import datetime as dt
import io
import math
import os
import urllib.request
from collections.abc import Callable
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from typing import Protocol
from zoneinfo import ZoneInfo

import numpy as np

THRESHOLD = 0.95
SENDER = "sjurado@das.uchile.cl"
RECIPIENTS = (
    "sjurado@das.uchile.cl",
    "bryanfabian4@gmail.com",
    "nicolas.e.delgado.a@gmail.com",
    "renato.gutierrez.maulme@gmail.com",
)
REGION = "us-east-1"

# Misma escala que «Mapa del modelo»: viridis en cinco tramos de 20 puntos porcentuales.
COLORS = (
    (0x44, 0x01, 0x54),
    (0x3B, 0x52, 0x8B),
    (0x21, 0x91, 0x8C),
    (0x5E, 0xC9, 0x62),
    (0xFD, 0xE7, 0x25),
)
TILE = 256
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
# La política de uso de los tiles de OpenStreetMap pide un User-Agent que identifique la aplicación.
USER_AGENT = "mesocyclonic-viewer/1.0 (alertas de Predecir; contacto: sjurado@das.uchile.cl)"
CHILE = ZoneInfo("America/Santiago")


class SesClient(Protocol):
    """Lo que se usa del cliente ``sesv2`` de boto3 (permite pasar uno falso en las pruebas)."""

    def send_email(self, **kwargs: object) -> dict: ...


def threshold() -> float:
    """Umbral de probabilidad (``ALERT_THRESHOLD`` o 0.95)."""
    return float(os.environ.get("ALERT_THRESHOLD", THRESHOLD))


def recipients() -> list[str]:
    """Destinatarios (``ALERT_EMAIL_TO`` o los del equipo)."""
    raw = os.environ.get("ALERT_EMAIL_TO", "")
    return [x.strip() for x in raw.split(",") if x.strip()] or list(RECIPIENTS)


def sender() -> str:
    """Remitente verificado en SES (``ALERT_EMAIL_FROM`` o el del equipo)."""
    return os.environ.get("ALERT_EMAIL_FROM", SENDER)


def hotspot(prob: np.ndarray, lat: np.ndarray, lon: np.ndarray, thr: float) -> dict | None:
    """Celda más probable y extensión de la zona con probabilidad ≥ ``thr``; ``None`` si no hay.

    ``prob`` tiene forma ``(len(lat), len(lon))``. Los valores no finitos se ignoran.
    """
    p = np.where(np.isfinite(prob), prob, -np.inf)
    hot = p >= thr
    if not hot.any():
        return None
    i, j = np.unravel_index(int(np.argmax(p)), p.shape)
    rows, cols = np.nonzero(hot)
    return {
        "prob": float(p[i, j]),
        "lat": float(lat[i]),
        "lon": float(lon[j]),
        "cells": int(hot.sum()),
        "lat_range": (float(lat[rows].min()), float(lat[rows].max())),
        "lon_range": (float(lon[cols].min()), float(lon[cols].max())),
    }


def _color(pct: float) -> tuple[int, int, int]:
    """Color de la escala del visor para un porcentaje de 0 a 100."""
    return COLORS[min(4, max(0, int(pct // 20)))]


def _px(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Coordenadas de píxel (Web Mercator) de ``lat``/``lon`` en el nivel de zoom ``zoom``."""
    n = TILE * 2**zoom
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def _fetch_tile(z: int, x: int, y: int) -> bytes:
    """Descarga un tile de OpenStreetMap."""
    req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (URL fija de OSM)
        return resp.read()


def crop_map(
    prob: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    spot: dict,
    step: float,
    thr: float = THRESHOLD,
    fetch: Callable[[int, int, int], bytes] = _fetch_tile,
) -> bytes:
    """PNG con un recorte de OpenStreetMap de la zona sobre el umbral, con margen y el máximo marcado.

    Solo se pintan las celdas con probabilidad ≥ ``thr``; un rectángulo rojo encierra la zona y un
    punto rojo marca la celda más probable. El zoom se elige para que el recorte mida unos 640 px de
    ancho. Si no se puede bajar algún tile, ese trozo queda gris y el resto sigue igual.
    """
    from PIL import Image, ImageDraw

    (s_lat, n_lat), (w_lon, e_lon) = spot["lat_range"], spot["lon_range"]
    margin = max(0.5, 0.25 * max(n_lat - s_lat, e_lon - w_lon))
    north, south = n_lat + step / 2 + margin, s_lat - step / 2 - margin
    west, east = w_lon - step / 2 - margin, e_lon + step / 2 + margin
    zoom = max(5, min(10, int(math.log2(640 * 360 / (TILE * (east - west))))))
    x0, y0 = _px(north, west, zoom)
    x1, y1 = _px(south, east, zoom)
    tx0, ty0, tx1, ty1 = int(x0 // TILE), int(y0 // TILE), int(x1 // TILE), int(y1 // TILE)
    canvas = Image.new("RGB", ((tx1 - tx0 + 1) * TILE, (ty1 - ty0 + 1) * TILE), (200, 200, 200))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            try:
                tile = Image.open(io.BytesIO(fetch(zoom, tx, ty))).convert("RGB")
                canvas.paste(tile, ((tx - tx0) * TILE, (ty - ty0) * TILE))
            except Exception:  # noqa: BLE001 (sin red o tile no disponible: queda gris)
                pass
    ox, oy = tx0 * TILE, ty0 * TILE
    img = canvas.crop((int(x0 - ox), int(y0 - oy), int(x1 - ox), int(y1 - oy))).convert("RGBA")
    bx, by = x0, y0

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    h = step / 2
    for i, la in enumerate(lat):
        for j, lo in enumerate(lon):
            v = prob[i, j]
            if not np.isfinite(v) or v < thr:
                continue
            ax, ay = _px(la + h, lo - h, zoom)
            cx, cy = _px(la - h, lo + h, zoom)
            draw.rectangle((ax - bx, ay - by, cx - bx, cy - by), fill=(*_color(v * 100), 110))
    img = Image.alpha_composite(img, layer)

    draw = ImageDraw.Draw(img)
    ax, ay = _px(n_lat + h, w_lon - h, zoom)
    cx, cy = _px(s_lat - h, e_lon + h, zoom)
    draw.rectangle((ax - bx, ay - by, cx - bx, cy - by), outline=(230, 57, 70, 255), width=3)
    mx, my = _px(spot["lat"], spot["lon"], zoom)
    mx, my = mx - bx, my - by
    draw.ellipse(
        (mx - 9, my - 9, mx + 9, my + 9),
        fill=(230, 57, 70, 255),
        outline=(255, 255, 255, 255),
        width=3,
    )
    text = "© OpenStreetMap contributors"
    tw = draw.textlength(text)
    draw.rectangle(
        (img.width - tw - 10, img.height - 18, img.width, img.height), fill=(255, 255, 255, 200)
    )
    draw.text((img.width - tw - 5, img.height - 15), text, fill=(30, 30, 30, 255))
    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def _fmt(x: float) -> str:
    """Número con coma decimal y dos decimales, como en el resto del visor."""
    return f"{x:.2f}".replace(".", ",")


def message(
    spot: dict, png: bytes, origen: str, thr: float, to: str, now: dt.datetime | None = None
) -> bytes:
    """Correo MIME para ``to`` (texto, HTML con el recorte y el PNG adjunto), para ``SendRawEmail``."""
    now = (now or dt.datetime.now(dt.UTC)).astimezone(CHILE)
    pct = spot["prob"] * 100
    la, lo = spot["lat"], spot["lon"]
    osm = f"https://www.openstreetmap.org/?mlat={la:.4f}&mlon={lo:.4f}#map=9/{la:.4f}/{lo:.4f}"
    (s_lat, n_lat), (w_lon, e_lon) = spot["lat_range"], spot["lon_range"]
    subject = f"[Demo] Alerta de tornado: {pct:.1f} % en {_fmt(la)}, {_fmt(lo)}"
    lines = [
        f"El modelo de la página «Predecir» marcó una probabilidad de {pct:.1f} % "
        f"(umbral {thr * 100:.0f} %).",
        "",
        f"Punto más probable: latitud {_fmt(la)}, longitud {_fmt(lo)}",
        f"Zona sobre el umbral: latitud {_fmt(s_lat)} a {_fmt(n_lat)}, "
        f"longitud {_fmt(w_lon)} a {_fmt(e_lon)} ({spot['cells']} celdas de 0,25°)",
        f"Imagen de entrada: {origen}",
        f"Hora del envío: {now:%d-%m-%Y %H:%M} hora de Chile",
        f"OpenStreetMap: {osm}",
        "",
        "Demostración con un modelo de ejemplo: el índice no es una probabilidad calibrada ni un "
        "pronóstico oficial.",
    ]
    text = "\n".join(lines)
    cid = make_msgid(domain="mesocyclonic")
    rows = "".join(f"<p style='margin:4px 0'>{x}</p>" for x in lines[2:6])
    html = (
        "<div style='font-family:system-ui,sans-serif;color:#0E1A2C'>"
        f"<h2 style='margin:0 0 8px'>⚠️ Alerta de tornado: {pct:.1f} %</h2>"
        f"<p>{lines[0]}</p>{rows}"
        f"<p><a href='{osm}'>Abrir en OpenStreetMap</a></p>"
        f"<img src='cid:{cid[1:-1]}' alt='Recorte de OpenStreetMap con la zona de la alerta' "
        "style='max-width:100%;border:1px solid #BDD4D6;border-radius:6px'>"
        f"<p style='color:#465463;font-size:13px'>{lines[-1]}</p></div>"
    )

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender()
    msg["To"] = to
    msg["Date"] = formatdate(localtime=False)
    related = MIMEMultipart("related")
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text, "plain", "utf-8"))
    alt.attach(MIMEText(html, "html", "utf-8"))
    related.attach(alt)
    inline = MIMEImage(png, "png")
    inline.add_header("Content-ID", cid)
    inline.add_header("Content-Disposition", "inline", filename="zona_alerta.png")
    related.attach(inline)
    msg.attach(related)
    adjunto = MIMEApplication(png, "png")
    adjunto.add_header(
        "Content-Disposition", "attachment", filename=f"alerta_{la:.2f}_{lo:.2f}.png"
    )
    msg.attach(adjunto)
    return msg.as_bytes()


def send(raw: bytes, to: str, client: SesClient | None = None) -> str:
    """Envía el correo ``raw`` a ``to`` con Amazon SES; devuelve el ``MessageId``."""
    ses: SesClient
    if client is None:
        import boto3

        ses = boto3.client("sesv2", region_name=os.environ.get("ALERT_REGION", REGION))  # type: ignore[assignment]
    else:
        ses = client
    resp = ses.send_email(
        FromEmailAddress=sender(),
        Destination={"ToAddresses": [to]},
        Content={"Raw": {"Data": raw}},
    )
    return resp["MessageId"]


def alert(
    prob: np.ndarray, lat: np.ndarray, lon: np.ndarray, step: float, origen: str
) -> dict | None:
    """Si alguna celda supera el umbral, arma y envía el correo; devuelve el resultado o ``None``.

    Se envía un correo por destinatario, para que uno sin verificar en SES (modo sandbox) no
    bloquee a los demás. El resultado trae ``spot`` (la zona), ``png`` (el recorte), ``sent`` (los
    destinatarios a los que salió) y ``failed`` (destinatario → error).
    """
    thr = threshold()
    spot = hotspot(prob, lat, lon, thr)
    if spot is None:
        return None
    png = crop_map(prob, lat, lon, spot, step, thr)
    out: dict = {"spot": spot, "png": png, "threshold": thr, "sent": [], "failed": {}}
    for to in recipients():
        try:
            send(message(spot, png, origen, thr, to), to)
            out["sent"].append(to)
        except Exception as e:  # noqa: BLE001 (se informa en la página; no rompe la predicción)
            out["failed"][to] = str(e)
    return out
