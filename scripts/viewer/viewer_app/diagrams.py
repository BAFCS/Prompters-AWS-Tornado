"""Los dos diagramas de la página «Problema», dibujados a mano en SVG.

Se dibujan con ``st.image`` (un SVG como imagen): ``st.html`` sanea el SVG. Dentro de una imagen no
hay JavaScript ni variables CSS de la página, así que cada SVG lleva su propia hoja de estilo con la
paleta del modo activo de ``theme``; las animaciones CSS (el giro de los rodillos) sí funcionan.
"""

import math

from viewer_app import theme

_TEXT = (
    f"text{{font-family:{theme.MONO}; font-size:12px; fill:var(--muted)}}"
    " text.lbl{font-size:12.5px; fill:var(--ink-2)}"
    f" text.big{{font-family:{theme.SANS}; font-size:14px; font-weight:600}}"
)

# Mesociclogénesis en cuatro etapas: ``data-stage`` (1–4) elige qué capas se ven y dónde van los rodillos.
_CSS_MC = """
.sp{transform-box:view-box; transform-origin:0 0; transition:transform 1.5s cubic-bezier(.45,.05,.3,1)}
.sp .fs{transform:scaleY(.30); transform-origin:0 0}
.sp .orbit{fill:none; stroke:var(--severe); stroke-width:2.4; opacity:.45}
.sp .spin{transform-origin:0 0; animation:spin var(--spd,7s) linear infinite}
.sp .spin circle{fill:var(--severe)}
@keyframes spin{from{transform:rotate(0deg)} to{transform:rotate(360deg)}}
.lay{transition:opacity .9s ease}
.lay.off{opacity:0}
@media (prefers-reduced-motion:reduce){ .sp .spin{animation:none} .sp,.lay{transition-duration:.01ms} }

#mcSvg[data-stage="1"] .sp{ transform:translate(calc(244px + var(--i)*70px), 268px) rotate(90deg) }
#mcSvg[data-stage="2"] .sp{ transform:translate(calc(328px + var(--i)*16px), calc(318px - var(--i)*32px)) rotate(45deg) }
#mcSvg[data-stage="3"] .sp{ transform:translate(364px, calc(340px - var(--i)*50px)) rotate(0deg) scale(.88,1) }
#mcSvg[data-stage="4"] .sp{ transform:translate(364px, calc(340px - var(--i)*50px)) rotate(0deg) scale(.64,1) }
#mcSvg[data-stage="1"]{ --spd:7s } #mcSvg[data-stage="2"]{ --spd:4.6s }
#mcSvg[data-stage="3"]{ --spd:2.4s } #mcSvg[data-stage="4"]{ --spd:1.2s }
#mcSvg[data-stage="2"] #updraftG, #mcSvg[data-stage="3"] #updraftG, #mcSvg[data-stage="4"] #updraftG,
#mcSvg[data-stage="3"] #cloudG, #mcSvg[data-stage="4"] #cloudG,
#mcSvg[data-stage="3"] #convG, #mcSvg[data-stage="4"] #convG,
#mcSvg[data-stage="4"] #senseG,
#mcSvg[data-stage="1"] #lab1, #mcSvg[data-stage="2"] #lab2, #mcSvg[data-stage="4"] #lab4{ opacity:1 }
#mcSvg[data-stage="3"] #shearG, #mcSvg[data-stage="4"] #shearG{ opacity:0 }
#mcSvg[data-stage="2"] #shearG{ opacity:.45 }
"""

_MC_BODY = """
      <line x1="40" y1="378" x2="720" y2="378" stroke="var(--line)" stroke-width="2"/>
      <path d="M40 378 L720 378 L720 392 L40 392 Z" fill="var(--surface-2)"/>
      <g class="lay" opacity=".85">
        <line x1="62" y1="96" x2="62" y2="378" stroke="var(--line)" stroke-width="1.5"/>
        <line x1="57" y1="378" x2="67" y2="378" stroke="var(--line)" stroke-width="1.5"/><text x="46" y="374" text-anchor="end">0</text>
        <line x1="57" y1="308" x2="67" y2="308" stroke="var(--line)" stroke-width="1.5"/><text x="46" y="312" text-anchor="end">2</text>
        <line x1="57" y1="238" x2="67" y2="238" stroke="var(--line)" stroke-width="1.5"/><text x="46" y="242" text-anchor="end">4</text>
        <line x1="57" y1="168" x2="67" y2="168" stroke="var(--line)" stroke-width="1.5"/><text x="46" y="172" text-anchor="end">6</text>
        <line x1="57" y1="98"  x2="67" y2="98"  stroke="var(--line)" stroke-width="1.5"/><text x="46" y="102" text-anchor="end">8</text>
        <text x="62" y="80" text-anchor="middle" font-size="10.5">km</text>
      </g>
      <g class="lay off" id="cloudG">
        <path d="M262 168 C250 150 258 128 282 124 C286 100 320 88 344 100 C358 82 396 80 410 100 C438 92 466 108 462 132 C488 136 494 160 478 172 Z" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="1.6" opacity=".9"/>
        <path d="M212 170 L520 170 C548 170 556 186 534 192 L200 192 C176 190 184 172 212 170 Z" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="1.6" opacity=".75"/>
        <path d="M352 96 C356 78 382 76 388 94 C400 88 410 98 404 104 L344 104 Z" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="1.6"/>
        <text class="lbl" x="418" y="80" fill="var(--accent)">tope nuboso elevado</text>
        <line x1="414" y1="84" x2="392" y2="92" stroke="var(--accent)" stroke-width="1.2"/>
        <text class="lbl" x="196" y="208" fill="var(--muted)">yunque: nube extendida</text>
        <path d="M280 300 L452 300 C462 300 462 312 452 312 L280 312 C270 312 270 300 280 300 Z" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="1.4" opacity=".8"/>
      </g>
      <g class="lay" id="shearG">
        <g stroke-linecap="round">
          <path d="M96 352 L152 352" stroke="var(--warm)" stroke-width="4"/><path d="M144 346 L154 352 L144 358" fill="none" stroke="var(--warm)" stroke-width="4"/>
          <path d="M96 306 L186 306" stroke="var(--warm)" stroke-width="4"/><path d="M178 300 L188 306 L178 312" fill="none" stroke="var(--warm)" stroke-width="4"/>
          <path d="M96 260 L232 260" stroke="var(--muted)" stroke-width="4"/><path d="M224 254 L234 260 L224 266" fill="none" stroke="var(--muted)" stroke-width="4"/>
          <path d="M96 214 L286 214" stroke="var(--cold)" stroke-width="4"/><path d="M278 208 L288 214 L278 220" fill="none" stroke="var(--cold)" stroke-width="4"/>
          <path d="M96 168 L348 168" stroke="var(--cold)" stroke-width="4"/><path d="M340 162 L350 168 L340 174" fill="none" stroke="var(--cold)" stroke-width="4"/>
        </g>
        <text class="lbl" x="96" y="140" fill="var(--cold)">el viento se acelera con la altura</text>
      </g>
      <g class="lay off" id="updraftG">
        <path d="M336 374 C332 300 334 240 344 176 L386 176 C392 240 394 300 392 374 Z" fill="var(--accent)" opacity=".14"/>
        <path d="M364 372 L364 150" stroke="var(--accent)" stroke-width="5" stroke-linecap="round"/>
        <path d="M348 168 L364 144 L380 168" fill="none" stroke="var(--accent)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
        <text class="lbl" x="416" y="244" fill="var(--accent)">corriente</text>
        <text class="lbl" x="416" y="260" fill="var(--accent)">ascendente</text>
      </g>
      <g class="lay off" id="convG">
        <g stroke="var(--warm)" stroke-width="3.5" stroke-linecap="round" fill="none">
          <path d="M196 358 L296 358"/><path d="M288 352 L298 358 L288 364"/>
          <path d="M532 358 L432 358"/><path d="M440 352 L430 358 L440 364"/>
        </g>
        <text class="lbl" x="176" y="338" fill="var(--ink-2)">aire que converge</text>
        <text class="lbl" x="552" y="338" fill="var(--ink-2)" text-anchor="end">aire que converge</text>
      </g>
      <g id="spinners">
        <g class="sp" style="--i:0"><g class="fs"><circle class="orbit" r="46"/><g class="spin"><circle cx="46" cy="0" r="6"/><circle cx="-23" cy="39.8" r="6"/><circle cx="-23" cy="-39.8" r="6"/></g></g></g>
        <g class="sp" style="--i:1"><g class="fs"><circle class="orbit" r="46"/><g class="spin"><circle cx="46" cy="0" r="6"/><circle cx="-23" cy="39.8" r="6"/><circle cx="-23" cy="-39.8" r="6"/></g></g></g>
        <g class="sp" style="--i:2"><g class="fs"><circle class="orbit" r="46"/><g class="spin"><circle cx="46" cy="0" r="6"/><circle cx="-23" cy="39.8" r="6"/><circle cx="-23" cy="-39.8" r="6"/></g></g></g>
        <g class="sp" style="--i:3"><g class="fs"><circle class="orbit" r="46"/><g class="spin"><circle cx="46" cy="0" r="6"/><circle cx="-23" cy="39.8" r="6"/><circle cx="-23" cy="-39.8" r="6"/></g></g></g>
      </g>
      <g class="lay off" id="lab1">
        <line x1="462" y1="268" x2="478" y2="268" stroke="var(--severe)" stroke-width="1.2"/>
        <text class="lbl" x="484" y="266" fill="var(--severe)">rodillos de rotación</text>
        <text class="lbl" x="484" y="282" fill="var(--severe)">horizontal</text>
      </g>
      <g class="lay off" id="lab2">
        <line x1="392" y1="284" x2="410" y2="296" stroke="var(--severe)" stroke-width="1.2"/>
        <text class="lbl" x="414" y="304" fill="var(--severe)">rotación inclinada</text>
        <text class="lbl" x="414" y="320" fill="var(--severe)">hacia la vertical</text>
      </g>
      <g class="lay off" id="lab4">
        <path d="M318 224 L312 224 L312 354 L318 354" fill="none" stroke="var(--severe)" stroke-width="1.4"/>
        <text class="lbl" x="304" y="254" text-anchor="end" fill="var(--severe)">mesociclón</text>
        <text class="lbl" x="304" y="270" text-anchor="end" fill="var(--severe)">2–10 km</text>
      </g>
      <g class="lay off" id="senseG">
        <circle cx="646" cy="126" r="30" fill="none" stroke="var(--severe)" stroke-width="2" opacity=".5"/>
        <path d="M646 96 A30 30 0 1 1 617 134" fill="none" stroke="var(--severe)" stroke-width="3" stroke-linecap="round"/>
        <path d="M612 124 L616 136 L628 133" fill="none" stroke="var(--severe)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        <text class="big" x="646" y="178" text-anchor="middle" fill="var(--ink)">sentido horario</text>
        <text x="646" y="196" text-anchor="middle">caso ilustrado</text>
      </g>
"""

# CAPE contra cizalladura 0–1 km: Chile (HSLC) frente a las Grandes Llanuras; comparación esquemática.
_CAPE_BODY = """
     <text class="big" x="694" y="94" text-anchor="middle" fill="var(--cold)">comparación esquemática</text>
     <text x="694" y="110" text-anchor="middle" fill="var(--cold)">no es un límite de STP</text>
     <line x1="90" y1="400" x2="800" y2="400" stroke="var(--line)" stroke-width="1.8"/>
     <line x1="90" y1="400" x2="90" y2="62" stroke="var(--line)" stroke-width="1.8"/>
     <g stroke="var(--line)" stroke-width="1" opacity=".55">
       <line x1="323" y1="400" x2="323" y2="62"/><line x1="557" y1="400" x2="557" y2="62"/><line x1="790" y1="400" x2="790" y2="62"/>
       <line x1="90" y1="334" x2="800" y2="334"/><line x1="90" y1="268" x2="800" y2="268"/>
       <line x1="90" y1="202" x2="800" y2="202"/><line x1="90" y1="136" x2="800" y2="136"/>
     </g>
     <text x="90" y="420" text-anchor="middle">10</text><text x="323" y="420" text-anchor="middle">100</text>
     <text x="557" y="420" text-anchor="middle">1.000</text><text x="790" y="420" text-anchor="middle">10.000</text>
     <text class="big" x="445" y="444" text-anchor="middle" fill="var(--ink-2)">CAPE  (J/kg, escala logarítmica)</text>
     <text x="80" y="404" text-anchor="end">0</text><text x="80" y="338" text-anchor="end">5</text>
     <text x="80" y="272" text-anchor="end">10</text><text x="80" y="206" text-anchor="end">15</text>
     <text x="80" y="140" text-anchor="end">20</text><text x="80" y="74" text-anchor="end">25</text>
     <text class="big" x="30" y="240" text-anchor="middle" fill="var(--ink-2)" transform="rotate(-90 30 240)">cizalladura 0–1 km  (m/s)</text>
     <path d="M160 104 L253 214 L323 268 L435 324 L557 358 L668 376 L790 387" fill="none" stroke="var(--accent)" stroke-width="2.6" stroke-dasharray="7 5"/>
     <text class="big" x="300" y="180" fill="var(--accent)">VGP₀₋₁ = 0,1 m/s²</text>
     <text x="300" y="196" fill="var(--accent)">referencia del estudio citado</text>
     <ellipse cx="694" cy="205" rx="66" ry="42" fill="var(--cold)" opacity=".20"/>
     <circle cx="668" cy="215" r="7" fill="var(--cold)"/><circle cx="729" cy="189" r="7" fill="var(--cold)"/>
     <text class="big" x="694" y="272" text-anchor="middle" fill="var(--cold)">Grandes Llanuras</text>
     <text x="694" y="288" text-anchor="middle" fill="var(--cold)">EE.UU. · supercélula clásica</text>
     <ellipse cx="492" cy="200" rx="56" ry="48" fill="var(--severe)" opacity=".18"/>
     <circle cx="464" cy="228" r="7.5" fill="var(--severe)"/><circle cx="520" cy="176" r="7.5" fill="var(--severe)"/>
     <text class="big" x="440" y="130" text-anchor="middle" fill="var(--ink)">Chile · 30–31 mayo 2019</text>
     <text x="440" y="146" text-anchor="middle" fill="var(--ink)">régimen HSLC</text>
     <line x1="452" y1="152" x2="470" y2="216" stroke="var(--severe)" stroke-width="1.2"/>
     <circle cx="201" cy="294" r="7" fill="var(--muted)"/>
     <text class="big" x="196" y="324" text-anchor="middle" fill="var(--muted)">Biobío · fines de mayo</text>
     <text x="196" y="340" text-anchor="middle" fill="var(--muted)">CAPE medio: 15–45 J/kg</text>
"""

STAGES = (
    (
        "1 · El cambio del viento con la altura genera rotación horizontal",
        "La cizalladura, llamada también cizalle, es el cambio de la velocidad o la dirección del viento con la altura. En el ejemplo del esquema, el viento aumenta su velocidad hacia arriba. Este cambio está asociado a una rotación del aire alrededor de un eje horizontal, paralelo al suelo.",
    ),
    (
        "2 · La corriente ascendente inclina la rotación",
        "La corriente ascendente es el aire que sube dentro de la tormenta. Al atravesar una capa con rotación horizontal, puede inclinar parte de esa rotación hacia la vertical. La helicidad relativa a la tormenta (SRH) ayuda a describir la relación entre la rotación del aire y el flujo que entra en la tormenta.",
    ),
    (
        "3 · El estiramiento puede intensificar la rotación",
        "Cuando el aire converge y asciende, la región en rotación puede estrecharse y estirarse. Este proceso puede aumentar su velocidad de giro. El esquema resume uno de los mecanismos que intervienen en la formación del mesociclón.",
    ),
    (
        "4 · La rotación se organiza en un mesociclón",
        "En esta etapa del esquema, la rotación se organiza dentro de la tormenta en una región de unos 2 a 10 km de diámetro. Si el mesociclón persiste, la tormenta se denomina supercélula. El esquema termina aquí: la formación de un tornado requiere procesos adicionales cerca de la superficie.",
    ),
)


# Vista desde arriba: el mismo mecanismo en los dos hemisferios (Chile, left-mover, horario; Grandes Llanuras, right-mover, antihorario).
_RING = (
    '<circle r="44" fill="none" stroke="var(--severe)" stroke-width="2" opacity=".5"/>'
    '<path d="M0 -44 A44 44 0 1 1 -42.5 11.7" fill="none" stroke="var(--severe)" stroke-width="3.4" stroke-linecap="round"/>'
    '<path d="M-49.5 -2.3 L-43.9 14.5 L-27.5 10.3" fill="none" stroke="var(--severe)" stroke-width="3.4" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
)


def _arrow(x1: float, y1: float, x2: float, y2: float, color: str) -> str:
    """Flecha recta de ``(x1, y1)`` a ``(x2, y2)`` con punta abierta."""
    ang = math.atan2(y2 - y1, x2 - x1)
    wing = [
        f"{x2 - 11 * math.cos(ang + d):.1f} {y2 - 11 * math.sin(ang + d):.1f}" for d in (0.5, -0.5)
    ]
    return (
        f'<path d="M{x1} {y1} L{x2} {y2}" stroke="{color}" stroke-width="3.2" stroke-linecap="round"/>'
        f'<path d="M{wing[0]} L{x2} {y2} L{wing[1]}" fill="none" stroke="{color}" stroke-width="3.2" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )


_PLAN_BODY = f"""
     <text class="big" x="205" y="30" text-anchor="middle" fill="var(--ink)">Chile · hemisferio sur</text>
     <text x="205" y="48" text-anchor="middle">left-mover: gira en sentido horario</text>
     <g transform="translate(205 160)">{_RING}</g>
     {_arrow(256, 160, 350, 160, "var(--muted)")}
     <text x="303" y="182" text-anchor="middle">viento medio</text>
     {_arrow(250, 136, 330, 88, "var(--severe)")}
     <text class="lbl" x="336" y="86" fill="var(--severe)">se desvía a la izquierda</text>
     <text class="big" x="615" y="30" text-anchor="middle" fill="var(--ink)">Grandes Llanuras · hemisferio norte</text>
     <text x="615" y="48" text-anchor="middle">right-mover: gira en sentido antihorario</text>
     <g transform="translate(615 160) scale(-1 1)">{_RING}</g>
     {_arrow(666, 160, 760, 160, "var(--muted)")}
     <text x="713" y="148" text-anchor="middle">viento medio</text>
     {_arrow(660, 184, 740, 232, "var(--severe)")}
     <text class="lbl" x="700" y="258" text-anchor="middle" fill="var(--severe)">se desvía a la derecha</text>
     <text x="410" y="282" text-anchor="middle">Vista desde arriba (esquema): el norte queda hacia arriba y el viento medio sopla hacia el este.</text>
"""

# Escala 2D, 15 px por km: dentro de una celda de ERA5 (31 × 31 km) caben unos 240 píxeles de GOES (2 × 2 km)
# y un mesociclón (círculo de 2 a 10 km de diámetro).
_GRID = "".join(
    f'<line x1="{40 + 30 * k}" y1="30" x2="{40 + 30 * k}" y2="495"/>' for k in range(1, 15)
) + "".join(f'<line x1="40" y1="{30 + 30 * k}" x2="505" y2="{30 + 30 * k}"/>' for k in range(1, 15))
_SCALE_BODY = f"""
     <rect x="40" y="30" width="465" height="465" fill="var(--cold)" opacity=".14"/>
     <g stroke="var(--cold)" stroke-width="1" opacity=".35">{_GRID}</g>
     <rect x="40" y="30" width="465" height="465" fill="none" stroke="var(--cold)" stroke-width="2.5"/>
     <rect x="100" y="90" width="30" height="30" fill="var(--accent)" opacity=".75" stroke="var(--accent)" stroke-width="1.5"/>
     <circle cx="300" cy="300" r="75" fill="var(--severe)" opacity=".16" stroke="var(--severe)" stroke-width="2" stroke-dasharray="6 4"/>
     <circle cx="300" cy="300" r="15" fill="var(--severe)" opacity=".5" stroke="var(--severe)" stroke-width="2"/>
     <path d="M130 105 L548 105" stroke="var(--accent)" stroke-width="1.2"/>
     <text class="big" x="552" y="100" fill="var(--accent)">Un píxel de GOES</text>
     <text x="552" y="118" fill="var(--accent)">2 × 2 km</text>
     <path d="M375 300 L548 300" stroke="var(--severe)" stroke-width="1.2"/>
     <text class="big" x="552" y="296" fill="var(--severe)">Un mesociclón</text>
     <text x="552" y="314" fill="var(--severe)">2 a 10 km de diámetro</text>
     <path d="M505 460 L548 460" stroke="var(--cold)" stroke-width="1.2"/>
     <text class="big" x="552" y="456" fill="var(--cold)">Una celda de ERA5</text>
     <text x="552" y="474" fill="var(--cold)">31 × 31 km: un solo valor</text>
     <text x="272" y="520" text-anchor="middle">Dentro de la celda caben unos 240 píxeles de GOES.</text>
"""


def _svg(width: int, height: int, css: str, body: str, extra: str = "") -> str:
    """Envuelve ``body`` en un SVG autónomo con la paleta y los estilos de texto del visor.

    La paleta va como variables CSS del modo activo: una imagen no hereda las de la página.
    """
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" {extra}>'
        f"<style>svg{{{theme.definitions(theme.colors())}}} {_TEXT} {css}</style>{body}</svg>"
    )


def mesocyclone(stage: int) -> str:
    """SVG de la mesociclogénesis en la ``stage`` 1–4."""
    return _svg(760, 430, _CSS_MC, _MC_BODY, f'id="mcSvg" data-stage="{stage}"')


def cape_shear() -> str:
    """SVG de CAPE contra cizalladura 0–1 km."""
    return _svg(880, 470, "", _CAPE_BODY)


def plan_view() -> str:
    """SVG de la vista desde arriba: el sentido de giro y la rama de movimiento en cada hemisferio."""
    return _svg(820, 300, "", _PLAN_BODY)


def scale() -> str:
    """SVG de la escala, en dos dimensiones: una celda de ERA5, un píxel de GOES y un mesociclón."""
    return _svg(780, 530, "", _SCALE_BODY)
