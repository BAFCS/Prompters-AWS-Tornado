# Visor exploratorio ERA5 + GOES — diseño

Fecha: 2026-10-02. Estado: implementado (el usuario pidió implementar tras aprobar la arquitectura;
esta especificación queda como registro de lo acordado).

## Propósito y audiencia

- **Participantes de la hackathon**: entender el caso y el problema en pocos minutos.
- **Investigadores**: explorar índices, sondeos y la evolución en satélite alrededor de cada evento.
- Solo días ya descargados en `data/recortes/`. Caso por defecto: 30-may-2019.

## Decisiones

| Tema | Decisión |
|---|---|
| Vistas | Índices del entorno, sondeo + hodógrafo, animación y firmas GOES, series en el evento |
| Explicación | Portada del caso, ayuda en contexto, recorrido guiado |
| Tema | Claro "Cuaderno de campo": paleta y tipografías de `web/index.html` |
| Estructura | Páginas de Streamlit (`st.navigation`) con estado compartido en la barra lateral |
| Índices | Script `procesa_era5.py` que escribe `era5_indices/`; el visor solo lee |

## Arquitectura

```
scripts/procesa_era5.py      era5_pl + era5_sfc → era5_indices/era5_idx_AAAAMMDD.nc
scripts/visor.py             entrada: tema, barra lateral común, navegación, recorrido
scripts/visor_app/
  datos.py                   recortes, catálogo, costa, series GOES (con caché)
  estado.py                  contexto, hora, punto, recorrido; persistencia de widgets
  textos.py                  ayuda por variable, contexto por caso, pasos del recorrido
  tema.py                    paleta, plantilla plotly, CSS fino
  componentes.py             ficha de umbrales y regla de tiempo (HTML)
  graficos.py                mapa, Skew-T, hodógrafo, series
  p_caso.py p_mapas.py p_sondeo.py p_series.py
.streamlit/config.toml       tema base de Streamlit
```

## Índices (`procesa_era5.py`)

Perfil por columna: superficie a 10 m + niveles por encima del terreno (la altura del terreno sale
de interpolar el geopotencial a la presión de superficie), interpolado cada 100 m hasta 6 km.
Cizalle 0–1/0–3/0–6 km; Bunkers (viento medio 0–6 km ± 7,5 m/s); SRH 0–1/0–3 km respecto de la
*left-mover*, con signo físico (negativa en casos tornádicos); LCL de Espy; gradientes 0–3 km y
700–500 hPa; VGP₀₋₁; STP rama *left-mover* sin CIN con el CAPE de ERA5; SHERBS3. Cada variable lleva
`umbral_chile` y `umbral_sentido` cuando el documento da un umbral. Validado contra MetPy en columnas
de muestra.

## Páginas

- **El caso**: título y contexto del día, GOES C13 de la zona con eventos, bitácora seleccionable,
  ficha "entorno contra umbral chileno" (punto elegido y extremo de la zona).
- **Mapas**: ERA5 (índices, superficie o presión con nivel) junto a GOES (16 bandas, ΔC13 en 10 min,
  C08 − C13), línea roja de umbral, viento 850 hPa, clic para elegir punto, animación ±1 h.
- **Sondeo**: Skew-T con parcela de superficie y LCL (MetPy), hodógrafo por capas con Bunkers.
- **Series**: VGP, SRH y cizalle (punto y ventana), Tb mínima y área < −50 °C de GOES, eventos
  marcados, CSV descargable.

## Límites conocidos

ERA5 no resuelve el mesociclón; GOES sin paralaje; STP sin CIN y SHERBS3 en lugar de SHERBE; el
catálogo solo trae positivos.
