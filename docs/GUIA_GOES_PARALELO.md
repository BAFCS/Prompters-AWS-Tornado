# Guía: descargar GOES en paralelo con el método exprés (bucket propio)

Esta guía permite a **otra persona del equipo**, en **su propia cuenta de AWS y su propio bucket**,
descargar las imágenes GOES recortadas a Chile **en paralelo** mientras otro corre ERA5, usando el
mismo método rápido (flota de EC2 con *sharding*) y **exactamente los mismos días** que la ingesta
de ERA5, para que ambos conjuntos sean compatibles día a día.

> **Reparto de trabajo del equipo.** Mientras una persona corre ERA5 (`era5_store/`) en el bucket
> principal, tú corres GOES (`goes_store/`) en **tu** bucket. Al final se juntan por fecha: cada día
> de evento tendrá ERA5 + GOES. No necesitas permiso de escritura en el bucket de nadie más.

Todo el código vive en el repositorio, rama **`intentos-nico`**:
<https://github.com/BAFCS/Prompters-AWS-Tornado/tree/intentos-nico>

- Scripts de ingesta: `scripts/ingest/`
- Lista de días a bajar: `scripts/ingest/dias_bloque.json`
- Infra de la flota: `infra/terraform-test/` (`worker_fleet.tf`, `worker_user_data.sh.tftpl`)

---

## 1. Qué vas a obtener

- **Fuente:** GOES-East (`s3://noaa-goes16` hasta 2025-04-04, `s3://noaa-goes19` desde entonces),
  producto `ABI-L2-CMIPF` (variable `CMI`). Es un bucket público en **us-east-1**.
- **Recorte:** Chile, región `south-central-austral` (lat −30 a −56, lon −76 a −66). El recorte se
  hace por **rango de bytes** (no se baja el globo entero), así que es exprés y en la **misma región**
  (sin cruce inter-región).
- **Bandas recomendadas para mesociclones:** `C13` (IR ventana, topes nubosos), `C08 C09 C10`
  (vapor de agua alto/medio/bajo), `C14 C15` (split-window). Puedes elegir cuáles.
- **Salida:** en TU bucket, `goes_store/<AAAA-MM-DD>/goes_YYYYMMDD_CNN.nc`, un archivo por banda y día.
- **Días:** los mismos **111 días-bloque** que ERA5 — bloques de 4 días (2 previos + día del evento +
  1 posterior) alrededor de cada uno de los 31 tornados catalogados entre 2020 y 2025. La lista está
  en `scripts/ingest/dias_bloque.json`.

---

## 2. Requisitos previos (una sola vez)

1. **Cuenta AWS propia** con permiso de crear EC2 en **us-east-1** (sin GPU, instancias < 6xlarge,
   p. ej. `c7i.2xlarge` = 8 vCPU).
2. **Un bucket S3 tuyo** en us-east-1 para dejar los datos, por ejemplo `mi-equipo-goes-chile`.
   ```bash
   aws s3 mb s3://mi-equipo-goes-chile --region us-east-1
   ```
3. **El repositorio clonado**, rama `intentos-nico`:
   ```bash
   git clone -b intentos-nico https://github.com/BAFCS/Prompters-AWS-Tornado.git
   cd Prompters-AWS-Tornado/redhorse
   ```
4. **Credenciales AWS** configuradas (`aws configure` o variables de entorno) con acceso a tu cuenta.

---

## 3. Opción A — rápida: una sola EC2 (sin Terraform)

Sirve para 111 días con holgura. Una `c7i.2xlarge` con 8 procesos en paralelo baja los 111 días ×
bandas en bastante menos de una hora (el cuello es la red, no la CPU).

### 3.1 Lanza una EC2 `c7i.2xlarge` (Amazon Linux 2023) en us-east-1
Con un rol de instancia que permita **escribir en tu bucket** (`s3:PutObject`, `s3:ListBucket` sobre
`arn:aws:s3:::mi-equipo-goes-chile*`) y, para entrar sin SSH, el managed policy
`AmazonSSMManagedInstanceCore`.

### 3.2 Dentro de la EC2 (por Session Manager), prepara el entorno
```bash
sudo dnf install -y python3.11 python3.11-pip git unzip
# AWS CLI v2 oficial (el del sistema puede venir roto)
cd /tmp && curl -sS https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o a.zip
unzip -q a.zip && sudo ./aws/install --update
# Código
sudo git clone -b intentos-nico https://github.com/BAFCS/Prompters-AWS-Tornado.git /opt/repo
cd /opt/repo/redhorse
python3.11 -m venv /opt/venv
/opt/venv/bin/pip install -U pip
/opt/venv/bin/pip install xarray zarr s3fs netCDF4 h5py h5netcdf numpy pandas boto3
```

### 3.3 Lanza la descarga apuntando a TU bucket y a los días-bloque
```bash
export DEST_BUCKET=mi-equipo-goes-chile          # <-- TU bucket
export PYTHONPATH=/opt/repo/redhorse/scripts:/opt/repo/redhorse/scripts/ingest
cd /opt/repo/redhorse
nohup /opt/venv/bin/python scripts/ingest/ingest_goes_multiband.py \
    --days-file scripts/ingest/dias_bloque.json \
    --bands 13 8 9 10 14 15 \
    --workers 8 \
    > /var/log/goes.log 2>&1 &
```
`DEST_BUCKET` redirige **toda** la escritura a tu bucket (lo leen tanto `ingest_goes_multiband.py`
como `ingest_goes.py`). `--days-file` usa exactamente los mismos 111 días que ERA5.

### 3.4 Sigue el avance
```bash
# por log
tail -f /var/log/goes.log
# o contando archivos reales en tu bucket (medida de verdad)
aws s3 ls s3://mi-equipo-goes-chile/goes_store/ --recursive --region us-east-1 | wc -l
```

---

## 4. Opción B — a escala: flota con Terraform (varias EC2)

Si quieres más bandas o más velocidad, usa la flota con *sharding* igual que la de ERA5. La infra
está en `infra/terraform-test/`.

1. Copia la lista de días y los scripts a **tu** bucket, bajo el prefijo `code/` (así los workers los
   descargan al arrancar):
   ```bash
   export DEST_BUCKET=mi-equipo-goes-chile
   aws s3 cp scripts/common.py        s3://$DEST_BUCKET/code/common.py        --region us-east-1
   aws s3 cp scripts/ingest/          s3://$DEST_BUCKET/code/ingest/          --recursive --region us-east-1
   aws s3 cp scripts/pipeline/        s3://$DEST_BUCKET/code/pipeline/        --recursive --region us-east-1
   ```
2. En `infra/terraform-test/worker_user_data.sh.tftpl`, la rama GOES ya corre
   `ingest_goes_multiband.py` con *sharding*. Asegúrate de:
   - Exportar `DEST_BUCKET` a tu bucket dentro del user-data (añade `export DEST_BUCKET="${bucket}"`
     antes de lanzar el script, y pon tu bucket en el `templatefile(...)`).
   - Pasar `--days-file /opt/lab/scripts/ingest/dias_bloque.json` en la invocación GOES (igual que ya
     hace la rama ncar), en vez de `--start/--end`.
   - Usar `python3.11` (la AMI nueva ya no trae 3.12; `common.py` es compatible con 3.9+).
3. Lanza, por ejemplo, 4 workers GOES:
   ```bash
   cd infra/terraform-test
   terraform apply -var-file=test.tfvars \
     -var="goes_fleet_size=4" -var="ncar_fleet_size=0" -var="enable_cdslab=true"
   ```
   Cada worker toma `(día, banda) % shard_total == shard_index`, sin solaparse. Al terminar,
   **destrúyelos** para no gastar:
   ```bash
   terraform apply -var-file=test.tfvars -var="goes_fleet_size=0"
   ```

> **Nota sobre el `.tfvars` y el bucket.** El `test.tfvars` del repo apunta al bucket del proyecto
> principal. Para tu cuenta, crea tu propio `terraform.tfvars` con `environment` y nombres distintos,
> o adapta `s3.tf` para usar tu bucket. Lo más simple es la **Opción A** (una EC2) si solo necesitas
> estos 111 días.

---

## 5. Compatibilidad con ERA5 (importante)

Para que GOES y ERA5 "casen" día a día:

- **Mismos días:** usa `scripts/ingest/dias_bloque.json` en ambas ingestas (ya lo hace esta guía).
- **Misma región de recorte:** `south-central-austral` (lat −30..−56, lon −76..−66). Es la que usan
  los dos scripts por defecto; no la cambies.
- **Mismo esquema de rutas:** GOES queda en `goes_store/<fecha>/goes_YYYYMMDD_CNN.nc`; ERA5 en
  `era5_store/era5_YYYYMMDD.zarr`. Un consumidor cruza por la fecha del nombre.

> La **armonización fina** (reproyectar GOES a la grilla lat/lon de ERA5 y alinear el eje temporal)
> es un paso posterior de curación, no de la descarga. Esta guía deja ambas fuentes recortadas a la
> misma región y los mismos días, que es la base para esa armonización.

---

## 6. Resumen de parámetros

| Parámetro | Valor para esta tanda |
|---|---|
| Días | `--days-file scripts/ingest/dias_bloque.json` (111 días, bloques de 4d, 2020–2025) |
| Bandas | `--bands 13 8 9 10 14 15` (ajústalas si quieres menos) |
| Región | `south-central-austral` (por defecto, no cambiar) |
| Bucket destino | `export DEST_BUCKET=<tu-bucket>` |
| Instancia | `c7i.2xlarge` (8 vCPU), us-east-1, sin GPU |
| Paralelismo | `--workers 8` por EC2; varias EC2 con `--shard-index/--shard-total` |
| Idempotencia | reejecuta sin miedo: salta lo que ya está (`--skip-existing` interno) |

Cualquier duda, el código y los comentarios están en `scripts/ingest/ingest_goes_multiband.py` y
`scripts/ingest/ingest_goes.py`.
