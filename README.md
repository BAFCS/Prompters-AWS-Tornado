# Predicción de tormentas mesociclónicas en Chile

Proyecto abierto para el **AWS Hackathon**: estimar qué tormentas del centro-sur de Chile
desarrollan **rotación organizada de mesoescala** (un mesociclón), potencialmente tornádica,
a partir del reanálisis **ERA5** y las imágenes multiespectrales del satélite **GOES**.

> Chile tiene alrededor de **100 tornados registrados desde 2015**, ninguna red de radar
> meteorológico operacional, y la certeza fundada de que **la mayoría de los eventos nunca
> fue vista por nadie**. Este proyecto busca tanto anticipar las tormentas que vienen como
> **encontrar en el archivo histórico las que faltan**.

## Contenido

| Ruta | Qué es |
|---|---|
| `docs/mesociclones_chile.md` | **El documento principal.** Contexto completo: el problema, la física, el caso chileno, los datos de entrada, las variables a calcular, cómo plantear el modelo, arquitectura en AWS y tareas abiertas. |
| `web/index.html` | Sitio web autocontenido en español (abrir directamente en el navegador). Incluye 8 diagramas SVG y una animación de cuatro pasos de la mesociclogénesis. |
| `web/artifact.html` | El mismo contenido sin el esqueleto `<html>/<head>`, para publicar como artifact. Derivado de `index.html`. |

No hay dependencias: el sitio es un único archivo HTML con SVG y CSS en línea.

## Los tres hallazgos que definen el proyecto

**1 · Los índices norteamericanos no funcionan aquí.**
Los tornados chilenos ocurren en un régimen **HSLC** (*High Shear, Low CAPE*). El brote del
30–31 de mayo de 2019 tuvo apenas **200–1.000 J/kg** de CAPE — la media climatológica de
fines de mayo en el Biobío es de **15–45 J/kg** — con cizalle 0–1 km de **12–20 m/s**.
Vicencio et al. (2021) señalan explícitamente que **el STP clásico no habría dado la alarma**.
Los umbrales calibrados para Chile son otros:

- `VGP₀₋₁ = √CAPE × cizalle₀₋₁ > 0,1 m/s²`
- `SHERBE ≥ 1`
- `STP` (rama *left-mover*) **≤ −0,3**, no `+1`

**2 · Estamos en el hemisferio sur.** La SRH de los casos tornádicos es **negativa** y las
supercélulas favorecidas son las ***left-movers***. Usar MetPy o SHARPpy tal cual produce
índices con el signo cambiado; es el error silencioso más costoso de este proyecto.

**3 · Los eventos faltantes ya están señalados en la literatura.**
Caballero-Morán & Rondanelli (2025, *GRL*) encontraron, con ERA5 1959–2021, amplias zonas
del sur austral con VGP, cizalle y helicidad suficientes y **ningún registro documentado**,
atribuible a subregistro por baja densidad poblacional.

## Datos

```bash
# ERA5 — NSF NCAR, us-west-2  ✅ el bucket a usar
aws s3 ls --no-sign-request s3://nsf-ncar-era5/

# ERA5 — DEPRECADO: solo 18 variables de superficie, sin niveles de presión ni CAPE
aws s3 ls --no-sign-request s3://era5-pds/

# GOES-East, us-east-1 — el satélite que mira a Chile (75,2°W)
aws s3 ls --no-sign-request s3://noaa-goes19/   # abr 2025 – presente
aws s3 ls --no-sign-request s3://noaa-goes16/   # dic 2017 – abr 2025
```

Dos trampas documentadas en `docs/`: los archivos de nivel de presión de ERA5 pesan **≈1,36 GB
cada uno** (una variable, un día, el globo entero) y no admiten recorte del lado del servidor;
y el **paralaje** de GOES desplaza los topes nubosos unos **20 km a 53°S**, varias celdas de grilla.

## Por dónde empezar

La sección 8 del documento lista diez tareas ordenadas por dificultad. Las de mayor impacto
por unidad de esfuerzo son curar el catálogo de eventos y construir *loops* GOES de los casos
conocidos; la de mayor potencial es **detectar la rotación del yunque por flujo óptico**, un
detector de mesociclones que no depende del catálogo de tornados.

## Referencias principales

- Vicencio, J. *et al.* (2021). *The Chilean Tornado Outbreak of May 2019.* **BAMS** 102(3), E611–E634. [doi](https://doi.org/10.1175/BAMS-D-19-0218.1) · [PDF](https://dgf.uchile.cl/rene/PUBS/Tornado_chile_2019.pdf)
- Marín, J. C. *et al.* (2024). *Climatological Aspects of Notable Tornado Events in Chile.* **MWR** 152(8), 1803–1819. [doi](https://doi.org/10.1175/MWR-D-23-0249.1)
- Barrett, B. S. *et al.* (2020). *A multiscale analysis of the tornadoes of 30–31 May 2019.* **Atmos. Res.** 236, 104811. [doi](https://doi.org/10.1016/j.atmosres.2019.104811)
- Caballero-Morán, V. & Rondanelli, R. (2025). *Tornado Seasonality in Central-Southern Chile.* **GRL** 52. [doi](https://doi.org/10.1029/2024GL110900)

La lista completa está en `docs/mesociclones_chile.md`.

---

*Las figuras del sitio son diagramas esquemáticos dibujados a mano en SVG, no imágenes de
satélite ni gráficos generados a partir de los datos. Generar las visualizaciones reales es
una de las tareas abiertas.*
