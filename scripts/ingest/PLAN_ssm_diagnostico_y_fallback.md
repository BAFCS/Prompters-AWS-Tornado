# Plan de diagnóstico SSM y fallback por user-data

Problema: la EC2 de laboratorio `i-0b0a5a414841ae928` (Amazon Linux 2023, us-east-1) **no aparece
como managed instance en SSM** pese a tener el rol `AmazonSSMManagedInstanceCore`, IP pública,
salida a internet y status checks OK. Es la segunda instancia seguida con el mismo síntoma, lo que
apunta a una causa **sistémica** (user-data, AMI, VPC/DNS, hora) y no a un fallo puntual del host.

Este documento es **solo diagnóstico y plan**: no ejecuta nada en AWS. Todas las verificaciones son
llamadas AWS CLI de **solo lectura**. El fallback propuesto evita SSM por completo: la instancia
corre el experimento sola al arrancar (user-data) y sube los resultados a S3.

Contexto fijo: cuenta `822870558093`, rol `WSParticipantRole`, **solo `us-east-1`** (us-west-2
denegado), sin GPU, sin instancias ≥ 6xlarge. Bucket destino
`mesocyclonic-test-data-20261015013924290100000003`.

---

## 1. Causas típicas de que el agente SSM de AL2023 no registre

Ordenadas de más a menos probable para este síntoma (status checks OK + IP pública + salida libre,
y **repetido en dos instancias**):

1. **El agente SSM no arranca o se cae al arrancar.**
   - En AL2023 el paquete es `amazon-ssm-agent` y el servicio corre bajo systemd como
     `amazon-ssm-agent.service` (NO `snap` como en Ubuntu). En algunas AMIs mínimas o personalizadas
     el agente no viene instalado o viene deshabilitado.
   - Si el user-data falla temprano o reemplaza/para el servicio, el agente nunca registra.
   - Señal esperada en consola: ausencia de líneas `amazon-ssm-agent`, o errores
     `failed to start message bus`, `error occurred attempting to registeration` (sic), o un
     `Permission denied` sobre `/var/lib/amazon/ssm`.

2. **User-data todavía corriendo y bloqueando (o fallando sin terminar).**
   - `cloud-init` ejecuta el user-data en el primer arranque. Si el script hace un `yum/dnf update`
     grande, instala muchas dependencias Python, o se cuelga en una descarga, el arranque "funcional"
     puede tardar y, si el script mata/espera recursos, el agente puede no haber reportado todavía.
   - Un user-data que **falla** deja la instancia "running" con status checks OK pero sin completar
     la configuración. Dos instancias con el mismo user-data defectuoso = mismo síntoma repetido.
     **Esta es la hipótesis más consistente con "dos seguidas".**
   - Señal en consola: `cloud-init` sin la línea final `Cloud-init ... finished`, o un traceback.

3. **Falta de conectividad a los endpoints de SSM.**
   - El agente necesita HTTPS (443) a **tres** servicios: `ssm.us-east-1.amazonaws.com`,
     `ssmmessages.us-east-1.amazonaws.com` y `ec2messages.us-east-1.amazonaws.com`.
   - "Salida libre" por SG/IGW no basta si: el **DNS de la VPC** no resuelve esos nombres, hay un
     **VPC endpoint (interface) mal configurado** que secuestra el tráfico, o el **NACL** bloquea el
     efímero de retorno. Con IP pública + IGW + salida 0.0.0.0/0 esto es menos probable, pero el
     endpoint `ssmmessages` (canal de sesión) suele ser el que falla aislado.

4. **Hora del sistema desincronizada.**
   - SigV4 rechaza peticiones con *skew* > ~5 min (`RequestTimeTooSkewed` / `InvalidSignatureException`).
     Si el reloj de la instancia está corrido (chrony no arrancó, o la AMI trae hora mala), el
     registro SSM falla con errores de firma aunque haya red perfecta.
   - Señal en consola: errores de `chronyd`, o del agente mencionando `skew` / `signature`.

5. **La VPC no tiene resolución DNS (enableDnsSupport / enableDnsHostnames).**
   - Si `enableDnsSupport=false`, la instancia no resuelve `ssm.us-east-1.amazonaws.com` y el agente
     no puede conectar aunque haya ruta a internet. Es una causa sistémica que afectaría a **todas**
     las instancias de esa VPC → consistente con "dos seguidas".

6. **Rol/credenciales no efectivos.**
   - El rol `AmazonSSMManagedInstanceCore` está adjunto, pero: el **instance profile** puede no estar
     asociado (adjuntar la *policy* a un rol no basta: la instancia necesita el *instance profile*),
     o IMDS está deshabilitado/con hop-limit 1 impidiendo que el agente obtenga credenciales, o una
     SCP/boundary niega `ssm:UpdateInstanceInformation`.
   - Señal en consola/metadata: el agente registra `NoCredentialProviders` o `AccessDenied` al llamar
     `UpdateInstanceInformation`.

---

## 2. Cómo verificar cada causa — SOLO lectura, AWS CLI

Todas en `--region us-east-1`. Reemplazar `i-0b0a5a414841ae928` si se prueba otra instancia.

### 2.0 Estado base de la instancia

```bash
aws ec2 describe-instances --region us-east-1 \
  --instance-ids i-0b0a5a414841ae928 \
  --query 'Reservations[].Instances[].{State:State.Name,AZ:Placement.AvailabilityZone,\
PublicIp:PublicIpAddress,SubnetId:SubnetId,VpcId:VpcId,Profile:IamInstanceProfile.Arn,\
ImageId:ImageId,Imds:MetadataOptions}' --output json

aws ec2 describe-instance-status --region us-east-1 \
  --instance-ids i-0b0a5a414841ae928 \
  --query 'InstanceStatuses[].{Inst:InstanceStatus.Status,Sys:SystemStatus.Status}' --output json
```

- **Causa 6 (instance profile / IMDS)**: `Profile` debe traer un ARN de *instance-profile*. Si es
  `null`, el rol no está realmente efectivo. `Imds.HttpTokens`=`required` con `HttpPutResponseHopLimit`=`1`
  es normal para el agente local; `HttpEndpoint`=`disabled` **rompe** el acceso a credenciales.

### 2.1 Leer la consola serial (clave para causas 1, 2, 4)

```bash
# Salida de consola más reciente (incluye cloud-init y arranque de servicios).
aws ec2 get-console-output --region us-east-1 \
  --instance-id i-0b0a5a414841ae928 --latest \
  --output text > console_$(date +%s).txt
```

Buscar en el texto resultante:

- **Causa 2 (user-data)**: `Cloud-init v. ... finished at ...` al final = user-data terminó.
  Su ausencia, o un `Traceback`, `command not found`, `No space left on device`, o
  `cloud-init ... failed` = el user-data no completó → síntoma explicado.
- **Causa 1 (agente)**: líneas `Started amazon-ssm-agent` / `amazon-ssm-agent.service`. Si no
  aparecen, o aparece `Unit amazon-ssm-agent.service not found`, el agente no está o no arrancó.
- **Causa 4 (hora)**: `chronyd` arrancando con error, o `System clock wrong` → skew.

> La consola serial es la única ventana sin shell: por eso es el centro del diagnóstico cuando SSM
> no está disponible. `--latest` da el buffer más reciente; sin `--latest` da el histórico.

### 2.2 Conectividad a endpoints (causa 3) — inspección de red, no de la instancia

No se puede `curl` desde la instancia sin shell, así que se verifica la **configuración** que
habilita la conectividad:

```bash
# Subred: ¿asigna IP pública? ¿qué route table?
aws ec2 describe-subnets --region us-east-1 \
  --subnet-ids <SubnetId> \
  --query 'Subnets[].{MapPublicIp:MapPublicIpOnLaunch,Az:AvailabilityZone,Cidr:CidrBlock}'

# Route table de la subred: ¿hay 0.0.0.0/0 -> igw-...?
aws ec2 describe-route-tables --region us-east-1 \
  --filters Name=association.subnet-id,Values=<SubnetId> \
  --query 'RouteTables[].Routes[]'

# Security group de salida: ¿443 permitido a 0.0.0.0/0?
aws ec2 describe-security-groups --region us-east-1 \
  --group-ids <SgId> --query 'SecurityGroups[].IpPermissionsEgress'

# NACL de la subred: ¿bloquea efímeros de retorno (1024-65535)?
aws ec2 describe-network-acls --region us-east-1 \
  --filters Name=association.subnet-id,Values=<SubnetId> \
  --query 'NetworkAcls[].Entries'

# ¿Hay VPC endpoints de SSM que podrían secuestrar/mal-enrutar el tráfico?
aws ec2 describe-vpc-endpoints --region us-east-1 \
  --filters Name=vpc-id,Values=<VpcId> \
  --query 'VpcEndpoints[].{Svc:ServiceName,Type:VpcEndpointType,State:State,\
PrivateDns:PrivateDnsEnabled,Subnets:SubnetIds}'
```

- Falta de `0.0.0.0/0 -> igw` o de 443 egress → causa 3 confirmada por configuración.
- Un interface endpoint de `ssm`/`ssmmessages`/`ec2messages` con `PrivateDnsEnabled=true` pero en
  otra AZ/subred sin ruta → secuestra el DNS y rompe el canal: causa 3 variante endpoint.

### 2.3 DNS de la VPC (causa 5)

```bash
aws ec2 describe-vpc-attribute --region us-east-1 \
  --vpc-id <VpcId> --attribute enableDnsSupport \
  --query 'EnableDnsSupport.Value'

aws ec2 describe-vpc-attribute --region us-east-1 \
  --vpc-id <VpcId> --attribute enableDnsHostnames \
  --query 'EnableDnsHostnames.Value'
```

- `enableDnsSupport=false` → la instancia no resuelve los endpoints SSM: causa 5 confirmada, y
  explica el síntoma repetido en todas las instancias de la VPC.

### 2.4 ¿Figura o no en SSM? (confirmación del síntoma)

```bash
aws ssm describe-instance-information --region us-east-1 \
  --filters Key=InstanceIds,Values=i-0b0a5a414841ae928 \
  --query 'InstanceInformationList[].{Ping:PingStatus,Agent:AgentVersion,Platform:PlatformName}'
```

- Lista vacía = nunca registró (consistente con el reporte). Si apareciera con
  `PingStatus=ConnectionLost`, el agente registró y luego perdió el canal (apunta a causa 3/4).

### 2.5 Resumen de verificación

| Causa | Comando de lectura | Señal que la confirma |
|---|---|---|
| 1 Agente no arranca | `get-console-output --latest` | sin `Started amazon-ssm-agent`, o unit not found |
| 2 User-data colgado/fallido | `get-console-output --latest` | sin `Cloud-init ... finished`, o `Traceback` |
| 3 Endpoints inalcanzables | `describe-route-tables`/`-security-groups`/`-network-acls`/`-vpc-endpoints` | falta ruta/igw/443, o endpoint mal enrutado |
| 4 Hora desincronizada | `get-console-output --latest` | errores `chronyd` / `skew` / `signature` |
| 5 VPC sin DNS | `describe-vpc-attribute` | `enableDnsSupport=false` |
| 6 Rol/IMDS/profile | `describe-instances` (Profile, MetadataOptions) | `Profile=null` o `HttpEndpoint=disabled` |

---

## 3. Enfoque alternativo a SSM: ejecución autónoma por user-data

Idea: **no necesitamos shell interactivo**. Lanzamos una instancia nueva cuyo **user-data** instala
dependencias, ejecuta `ingest_ncar_zarr.py` para uno o varios días, escribe un informe de tiempos a
S3 y, opcionalmente, apaga la instancia. El resultado se lee desde S3 con `aws s3 cp`, sin SSM, sin
SSH, sin consola interactiva.

Ventajas:

- Evita por completo el canal SSM problemático.
- Es idempotente y auditable: todo el trabajo queda escrito en S3 (`ingest/run-<id>/`), incluido el
  log completo de cloud-init y el informe de tiempos.
- Si el user-data era la causa 2, este diseño mueve el log a S3 **y** a la consola serial, así que el
  propio fallback sirve de diagnóstico.

Requisitos sobre el rol de instancia (verificar, no asumir): `s3:PutObject` sobre
`mesocyclonic-test-data-20261015013924290100000003/ingest/*` y `era5_store/*`, y lectura anónima de
`s3://nsf-ncar-era5/` (que es pública, no necesita permisos). Lanzar con un *instance profile* real,
no solo la policy en un rol.

### 3.1 Patrón de robustez del user-data

- `set -euxo pipefail` y **redirigir todo a un log** que se sube a S3 pase lo que pase (trap EXIT).
- Subir el log **al final siempre** (éxito o fallo) para no quedarnos ciegos como ahora.
- **Usar `uv`, no `pip`.** El proyecto exige `requires-python >= 3.12`, pero AL2023 solo trae
  Python 3.9/3.11 por `dnf`: `uv` descarga el Python 3.13 correcto e instala las deps **exactas**
  desde `uv.lock` con `uv sync`, evitando adivinar versiones (p. ej. `zarr`, que el script usa vía
  `to_zarr` pero no aparece pineado en `pyproject.toml`, lo resuelve el lockfile). Es además la
  convención del repo (AGENTS.md: nunca `pip`).
- Clonar el repo completo (trae `pyproject.toml`, `uv.lock`, `common.py`,
  `pipeline/download_era5.py` e `ingest/ingest_ncar_zarr.py`), o copiarlo desde un bucket propio.
- Fijar `AWS_DEFAULT_REGION=us-east-1`.
- Opcional: `shutdown -h now` al final para no gastar la instancia (dejar comentado mientras se
  depura, para poder leer la consola).

### 3.2 Snippet de user-data autosuficiente

> Pensado para Amazon Linux 2023. Sustituir `<REPO_GIT_URL>` por la URL del repositorio (o reemplazar
> el bloque de `git clone` por una copia desde un bucket propio con `aws s3 cp --recursive`). Lanzar,
> por ejemplo, con `--instance-type m7i.xlarge` (sin GPU, < 6xlarge) y un *instance profile* con los
> permisos de la sección 3. **No ejecutar como parte de esta tarea**; es el artefacto a usar cuando
> se decida lanzar.

```bash
#!/bin/bash
# user-data: ingesta ERA5 NSF NCAR -> Zarr autónoma, sin SSM ni SSH. Sube log e informe a S3.
set -euxo pipefail

# --- Parámetros del experimento ---------------------------------------------
BUCKET="mesocyclonic-test-data-20261015013924290100000003"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
S3_RUN="s3://${BUCKET}/ingest/run-${RUN_ID}"
DATES=("2019-05-30")               # añadir más días si se quiere comparar varios
REGION="us-east-1"
export AWS_DEFAULT_REGION="${REGION}"
LOG="/var/log/ingest-userdata.log"

# --- Log a archivo + consola serial, y subida garantizada al salir ----------
exec > >(tee -a "${LOG}") 2>&1
upload_log() { aws s3 cp "${LOG}" "${S3_RUN}/cloud-init.log" || true; }
trap upload_log EXIT

echo "== run ${RUN_ID} =="; date -u; echo "destino ${S3_RUN}"

# --- Hora correcta (defensa contra causa 4: skew de SigV4) y utilidades base -
dnf install -y chrony git tar gzip || true
systemctl enable --now chronyd || true
chronyc makestep || true

# --- Dependencias con uv (resuelve Python 3.13 + deps exactas de uv.lock) -----
# uv instala el Python correcto; AL2023 por dnf solo da 3.9/3.11 y el repo pide >=3.12.
export HOME=/root
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="/root/.local/bin:${PATH}"
uv --version

# --- Código del proyecto -----------------------------------------------------
cd /opt
git clone --depth 1 <REPO_GIT_URL> redhorse
cd redhorse
uv sync                                   # entorno reproducible desde uv.lock

# --- Ejecutar la ingesta por cada día y capturar el informe ------------------
REPORT="/tmp/informe_tiempos_${RUN_ID}.txt"
{
  echo "Informe de ingesta NSF NCAR -> Zarr"
  echo "run: ${RUN_ID}"
  echo "tipo: $(curl -s http://169.254.169.254/latest/meta-data/instance-type || echo n/a)"
  echo "region lectura fuente: us-west-2 (nsf-ncar-era5), escritura: ${REGION}"
  echo "-----------------------------------------------------------"
} > "${REPORT}"

for D in "${DATES[@]}"; do
  echo ">> ingestando ${D}"
  START=$(date -u +%s)
  # El script imprime tiempo total, MB y MB/s por stdout; lo volcamos al informe.
  if uv run python scripts/ingest/ingest_ncar_zarr.py --date "${D}" >> "${REPORT}" 2>&1; then
    STATUS="OK"
  else
    STATUS="FALLO"
  fi
  END=$(date -u +%s)
  echo "   ${D}: ${STATUS} en $((END-START)) s (medido por user-data)" >> "${REPORT}"
done

echo "-----------------------------------------------------------" >> "${REPORT}"
echo "fin: $(date -u)" >> "${REPORT}"

# --- Subir el informe (el log se sube solo en el trap EXIT) ------------------
aws s3 cp "${REPORT}" "${S3_RUN}/informe_tiempos.txt"

echo "== listo; informe en ${S3_RUN}/informe_tiempos.txt =="
# Para ahorrar costo una vez validado, descomentar:
# shutdown -h now
```

### 3.3 Cómo leer el resultado (solo lectura, sin shell en la instancia)

```bash
# Listar lo que dejó la corrida:
aws s3 ls --region us-east-1 \
  s3://mesocyclonic-test-data-20261015013924290100000003/ingest/ --recursive

# Traer el informe de tiempos y el log de cloud-init:
aws s3 cp --region us-east-1 \
  s3://mesocyclonic-test-data-20261015013924290100000003/ingest/run-<RUN_ID>/informe_tiempos.txt .
aws s3 cp --region us-east-1 \
  s3://mesocyclonic-test-data-20261015013924290100000003/ingest/run-<RUN_ID>/cloud-init.log .
```

Si el informe no aparece pero el `cloud-init.log` sí, el log dirá exactamente dónde falló (deps,
clone, permisos S3) — justo el diagnóstico que hoy nos falta por no tener shell.

---

## 4. Orden de ataque recomendado

1. **Leer la consola serial** (`get-console-output --latest`): confirma o descarta causas 1, 2 y 4
   de inmediato y es lo más barato. Dado "dos instancias seguidas", esperar encontrar aquí un
   user-data fallido (causa 2) o el agente ausente (causa 1).
2. **`describe-instances` + `describe-vpc-attribute`**: descartar causa 5 (DNS de VPC) y 6
   (instance profile/IMDS), ambas sistémicas y coherentes con el síntoma repetido.
3. **Inspección de red** (rutas/SG/NACL/endpoints): descartar causa 3.
4. **En paralelo**, sin esperar a resolver SSM: lanzar la instancia con el **user-data de la sección
   3.2** para obtener ya los tiempos de ingesta NSF NCAR → Zarr y, de paso, un log en S3 que sirve de
   diagnóstico. Este frente desbloquea el experimento aunque SSM siga caído.

GOES-16/19 están en `us-east-1` (misma región del laboratorio): es la "fruta madura" para un
segundo user-data análogo si se quiere avanzar la ingesta satelital en paralelo, sin el cruce de
regiones que penaliza a ERA5.
