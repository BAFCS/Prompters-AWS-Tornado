# Guía de datos en AWS (para agentes y personas)

Dónde viven los datos del data lake de prueba, cómo acceder y cómo tratarlos. Esta guía es para que
cualquier agente/persona sepa **dónde mirar** y **cómo leer** sin re-descargar nada.

> ⚠️ Esta es una **tanda de PRUEBA**. Ver `docs/ARQUITECTURA_CLON.md` §4-§6 para alcance, reservas
> (ERA5T, variables reducidas) y el plan de la tanda completa.

## 1. Cuenta y acceso

- **Cuenta AWS**: `822870558093` (hackathon), rol `WSParticipantRole`. Solo **us-east-1**.
- Credenciales **temporales** (caducan): perfil `default` en `~/.aws/credentials`. Si una llamada
  da `ExpiredTokenException`, renovar las credenciales del portal de acceso y reescribir el archivo.
- Restricciones de la cuenta: sin GPU, sin instancias `>=6xlarge`, no se pueden subir cuotas, solo
  us-east-1 (verificado en la política IAM `ws-default-policy`).

## 2. Bucket y layout del data lake

Bucket: **`s3://mesocyclonic-test-data-20261015013924290100000003/`**

| Prefijo | Fuente | Formato | Contenido |
|---|---|---|---|
| `era5_store/era5_YYYYMMDD.zarr/` | ERA5 vía NSF NCAR | **Zarr** (1 por día) | variables, recorte Chile |
| `era5_cds_year/<AAAA>/<MM>/era5_pl_YYYYMMDD.nc` | ERA5 vía Copernicus CDS | **NetCDF** (niveles presión) | `u,v,t,z` |
| `era5_cds_year/<AAAA>/<MM>/era5_sfc_YYYYMMDD.nc` | ERA5 vía CDS | **NetCDF** (superficie) | `u10,v10,t2m,d2m,sp,cape` |
| `goes_store/<AAAA-MM-DD>/goes_YYYYMMDD.nc` | GOES-16/19 | **NetCDF** | banda C13 (imagen) |
| `experimentos/progreso*.json` | — | JSON | progreso de ingestas |
| `code/ingest/*.py` | — | Python | scripts de ingesta (copia) |

Región de todos los datos: **Chile** (lat −56..−30, lon −76..−66).

## 3. Qué contiene cada fuente (verificado leyendo archivos reales)

| Fuente | Tipo | Pasos/día | Variables | Niveles | Grilla |
|---|---|---|---|---|---|
| ERA5 ncar | numérico | 24 (horario) | `u,v,t,z` + `10u,10v,2t,2d,sp,cape` | 1000,925,850,700,500,300 hPa | 105×41 |
| ERA5 CDS | numérico | 24 (horario) | `u,v,t,z` + `u10,v10,t2m,d2m,sp,cape` | iguales | 105×41 |
| GOES | imagen | 144 (~10 min) | `C13` (IR ~10.3 µm) | — | 882×466 |

**Cobertura temporal** (al cierre de la tanda de prueba):
- ERA5 ncar: 2025-10-15 → 2026-07-31 (límite del bucket público) + día suelto 2019-05-30.
- ERA5 CDS: parcial 2025-10 → 2026-01 + relleno ago-sep 2026 (en curso) + día 2019.
- GOES: 2025-10-15 → 2026-09-30 (año casi completo).

## 4. Cómo LEER los datos (directo desde S3, sin descargar)

**Importante**: usar Python **3.12** (el repo declara `requires-python>=3.12`; `common.py` usa
sintaxis de genéricos 3.12). ERA5 ncar es Zarr; CDS y GOES son NetCDF.

```python
import xarray as xr, s3fs
B = "mesocyclonic-test-data-20261015013924290100000003"
fs = s3fs.S3FileSystem()  # credenciales del rol/entorno; región us-east-1

# ERA5 ncar (Zarr, nombres cortos, coords time/level)
era5 = xr.open_zarr(s3fs.S3Map(f"s3://{B}/era5_store/era5_20260520.zarr", s3=fs))

# ERA5 CDS (NetCDF; OJO coords valid_time/pressure_level y nombres largos u10/t2m)
cds_pl  = xr.open_dataset(fs.open(f"s3://{B}/era5_cds_year/2026/01/era5_pl_20260130.nc"))
cds_sfc = xr.open_dataset(fs.open(f"s3://{B}/era5_cds_year/2026/01/era5_sfc_20260130.nc"))

# GOES (NetCDF; dims time/y/x, variable C13)
goes = xr.open_dataset(fs.open(f"s3://{B}/goes_store/2026-05-20/goes_20260520.nc"))
```

## 5. Diferencias de esquema a ARMONIZAR antes de mezclar fuentes

(Ver detalle en `docs/ARQUITECTURA_CLON.md` §6.2. Es trabajo pendiente, bloqueante para la curación.)

| | ncar | CDS |
|---|---|---|
| coord tiempo | `time` | `valid_time` |
| coord nivel | `level` | `pressure_level` |
| viento 10m | `10u`,`10v` | `u10`,`v10` |
| temp 2m / rocío | `2t`,`2d` | `t2m`,`d2m` |
| pl + sfc | fusionados en 1 Zarr | 2 NetCDF separados |

Para consumir ncar+CDS como una serie única hay que renombrar coords/variables, mergear pl+sfc de
CDS, y (recomendado) convertir todo a un **Zarr único concatenado en `time`**. GOES necesita regrid
a la grilla ERA5 (reutilizar `scripts/pipeline/process_goes.py`).

## 6. Procedencia y advertencias

- Días de **2019** (caso de estudio brote de tornados) están mezclados con la ventana reciente.
- El tramo **ago-sep 2026** proviene de **CDS/ERA5T preliminar** (`expver=5`), no de la ERA5 final.
  Debe re-descargarse cuando ECMWF consolide (~2-3 meses). Etiquetar procedencia por día.
- La verificación CDS≡ncar se hizo con 1 variable/1 nivel/1 día (dif 0.000 K): indicativa, no
  exhaustiva. Ampliar antes de usar como base científica.

## 7. Cómo operar la infra (Terraform)

Carpeta `infra/terraform-test/` (clon aislado, no toca `dev`). Binario portable o `terraform`:

```bash
cd infra/terraform-test
terraform apply -var-file=test.tfvars -var="enable_cdslab=true"                      # EC2 lab CDS
terraform apply -var-file=test.tfvars -var="enable_cdslab=true" -var="ncar_fleet_size=6"  # flota ncar
terraform apply -var-file=test.tfvars -var="enable_cdslab=true" -var="goes_fleet_size=6"  # flota GOES
terraform apply -var-file=test.tfvars ... -var="ncar_fleet_size=0" -var="goes_fleet_size=0"  # apagar flotas
```

Para ejecutar en una EC2 sin SSH: AWS Systems Manager (`aws ssm send-command`). La AMI del proyecto
NO trae el agente SSM: el user-data lo instala (`dnf install -y amazon-ssm-agent`).

Nota de entorno en las EC2: usar el AWS CLI v2 oficial (`/usr/local/bin/aws`) y un venv Python 3.12
(`/opt/lab/venv312`), NO el Python del sistema (3.9) ni pip global (rompe el AWS CLI).
