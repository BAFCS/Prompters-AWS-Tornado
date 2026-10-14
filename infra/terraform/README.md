# Despliegue del visor en AWS con Terraform (EC2 + CloudFront)

Esta carpeta despliega el visor Streamlit en AWS usando **Terraform**, con una instancia **EC2**
que corre el contenedor Docker del visor y **CloudFront** por delante para dar una URL pública con
HTTPS que puedes compartir.

```
Equipo (navegador) ─HTTPS─► CloudFront ─HTTP:8501─► EC2 (Docker: visor Streamlit)
                                                        │ al arrancar baja data/ desde S3
                                                        ▼
                                              S3 (bucket privado con data/)
```

- Un bucket **S3 privado** guarda los datos (`data/crops/`, `tornados_chile.xlsx`, `coast.zip`).
- Una **EC2** (Amazon Linux 2023) clona el repositorio, baja los datos desde S3, **construye la
  imagen con el `Dockerfile` del repositorio** y deja el visor corriendo en el puerto 8501. Todo el
  trabajo ocurre en la nube: no se construye ni se prueba nada en tu equipo.
- **CloudFront** es la única entrada pública. Entrega HTTPS con el certificado `*.cloudfront.net` y
  reenvía todo al visor. El *security group* de la EC2 solo acepta tráfico desde CloudFront (lista
  de prefijos administrada `com.amazonaws.global.cloudfront.origin-facing`), así nadie puede
  saltarse el HTTPS llegando directo a la instancia.

> Esta es una alternativa a la carpeta `infra/` (CDK con ECS Fargate). Aquí se usa EC2 + Terraform
> por pedido explícito: más barato y más simple para una demo.

## Requisitos

- **Terraform** 1.5 o superior (`terraform version`).
- Credenciales de AWS exportadas en la terminal (las del portal de acceso de AWS):

  ```bash
  export AWS_DEFAULT_REGION="us-east-1"
  export AWS_ACCESS_KEY_ID="..."
  export AWS_SECRET_ACCESS_KEY="..."
  export AWS_SESSION_TOKEN="..."
  ```

  No las guardes en archivos del repositorio ni las pegues en chats.

- El AWS CLI, solo para subir los datos a S3 (`aws --version`).

No hace falta Docker en tu equipo: la imagen se construye en la EC2.

## Pasos

Todo desde esta carpeta (`infra/terraform/`).

### 1. Inicializa Terraform

```bash
terraform init
```

### 2. Crea primero el bucket de datos

El visor necesita los datos en S3 cuando arranca, así que el bucket se crea antes de subir nada:

```bash
terraform apply \
  -target=aws_s3_bucket.data \
  -target=aws_s3_bucket_public_access_block.data \
  -target=aws_s3_bucket_server_side_encryption_configuration.data \
  -target=aws_s3_bucket_policy.data_tls_only
```

Responde `yes`. Al terminar imprime `data_bucket = "mesocyclonic-dev-data-xxxxx"`.

### 3. Sube los datos a S3

Desde la raíz del repositorio, con el nombre de bucket del paso anterior:

```bash
BUCKET="$(terraform -chdir=infra/terraform output -raw data_bucket)"
aws s3 sync data/crops/            "s3://$BUCKET/data/crops/"
aws s3 cp   data/tornados_chile.xlsx "s3://$BUCKET/data/tornados_chile.xlsx"
aws s3 cp   data/coast.zip           "s3://$BUCKET/data/coast.zip"
```

Solo se sube lo que el visor lee. Descargas crudas u otros archivos de `data/` no hacen falta.

### 4. Despliega el resto (EC2 + CloudFront)

```bash
terraform apply
```

Responde `yes`. La EC2 se crea en menos de un minuto y CloudFront tarda unos 3 minutos. Al final
imprime:

```
viewer_url = "https://xxxxxxxx.cloudfront.net"
```

Esa es **la URL que compartes**. La EC2 todavía construye la imagen por dentro durante uno o dos
minutos; en cuanto termina, la URL responde con el visor.

### 5. Comprueba que responde

```bash
URL="$(terraform output -raw viewer_url)"
curl -s -o /dev/null -w "%{http_code}\n" "$URL/_stcore/health"   # debe dar 200
```

## Agregar días nuevos

Descarga y procesa el día en tu equipo (paso 5 del README principal), vuelve a sincronizar los
datos a S3 (paso 3) y reinicia el contenedor de la EC2 para que los lea. Lo más simple es forzar un
nuevo arranque recreando la instancia:

```bash
terraform apply -replace=aws_instance.viewer
```

(La IP de origen cambia, pero CloudFront usa el DNS público de la EC2, así que la URL pública no
cambia.)

## Entrenar el modelo XGBoost (EC2 aparte)

El entrenamiento corre en **otra EC2**, separada del visor, para no mezclar un servicio
*always-on* con cómputo pesado puntual. Esa instancia:

1. Clona el repositorio e instala las dependencias con `uv`.
2. Baja el catálogo desde S3 y, para los días con evento (y una muestra de días sin evento),
   **genera los índices ERA5** (`download_era5.py` + `process_era5.py`) leyendo el bucket público
   `nsf-ncar-era5`.
3. Arma la tabla *positive-unlabeled*, entrena **XGBoost** y evalúa con **POD/FAR/CSI** usando
   validación *dejar-un-evento-afuera* (sin fuga entre horas del mismo evento).
4. Sube `model.json`, `metrics.json`, `importance.json` y `reporte.html` al prefijo
   `resultados/` del bucket de datos.
5. Si `stop_after_training = true`, se **apaga sola** al terminar (no sigue cobrando).

```
EC2 entrenamiento ──baja──► ERA5 público (nsf-ncar-era5)
       │ genera índices, entrena XGBoost
       └──sube resultados──► S3  ──(/resultados/* vía CloudFront)──► reporte HTML público
```

El entrenamiento se activa por defecto (`enable_training = true`). Para una **primera corrida
rápida**, acota los días (descargar ERA5 es lento: ~0,3 GB/día entre regiones, más tiempo de
cálculo):

```bash
terraform apply -var="max_event_days=6" -var="unlabeled_days=4"
```

Para entrenar con **todos** los días con evento del catálogo (unos 38; tarda bastante más):

```bash
terraform apply -var="max_event_days=0"
```

> La cuenta de la hackathon **deniega crear recursos en us-west-2**, donde vive ERA5. Por eso la
> EC2 de entrenamiento va en `us-east-1` (variable `training_region`) y lee ERA5 entre regiones:
> funciona porque `nsf-ncar-era5` es un bucket público de acceso anónimo.

### El cuello de botella: descargar ERA5 (y cómo se optimiza)

Entrenar XGBoost toma **segundos**; lo lento es **bajar ERA5**. El bucket `nsf-ncar-era5` guarda
cada variable como un archivo que cubre el globo entero (una variable, un día, ~1,4 GB) y no admite
recorte en el servidor: hay que transferir el bloque global y recortarlo en memoria. Lo que se hace
para que no sea un muro:

1. **Bajar solo las variables que el modelo usa.** `process_era5` solo necesita `u, v, t, z` en
   niveles de presión (el default traía 8, con `w, q, r, vo` que no entran en ninguna feature) y
   `10u, 10v, 2t, 2d, sp, cape` en superficie. El orquestador ya pide solo esas: **~la mitad** del
   tráfico, sin cambiar ningún índice.
2. **Cachear los índices en S3 y reutilizarlos** (`--indices-s3 s3://bucket/era5_indices`). ERA5 →
   índice es determinista. Una vez calculado, cada día pesa ~2 MB en vez de ~11 GB. La primera
   corrida del equipo paga el costo una vez; las siguientes entrenan en segundos leyendo los
   índices. Volver a entrenar con otras features ya no vuelve a bajar ERA5.
3. **Timeout por día**: si un día se cuelga bajando (sockets entre regiones), se omite y el job
   sigue, en vez de bloquearse.

Mejoras mayores si tu cuenta lo permite:

- **EC2 en us-west-2** (misma región que ERA5): transferencia intra-región, mucho más rápida y sin
  cuelgues. Hoy lo bloquea el *deny* de la cuenta de la hackathon.
- **Climate Data Store (CDS) de Copernicus**: permite pedir solo la región y niveles (`area:`),
  bajando kilobytes en vez de gigabytes. Requiere cuenta/API key y a veces hay cola.

### Ver los resultados del modelo

El reporte HTML con las métricas queda servido por CloudFront:

```bash
terraform output results_url
# https://<dominio>.cloudfront.net/resultados/reporte.html
```

Para seguir el avance **en vivo** mientras entrena (se refresca solo):

```
https://<dominio>.cloudfront.net/resultados/estado.html
```

También puedes descargar los archivos crudos desde S3:

```bash
BUCKET="$(terraform output -raw data_bucket)"
aws s3 ls "s3://$BUCKET/resultados/"
aws s3 cp "s3://$BUCKET/resultados/metrics.json" .
```

### Volver a entrenar

Fuerza un nuevo arranque de la EC2 de entrenamiento (vuelve a generar índices y modelo):

```bash
terraform apply -replace='aws_instance.training[0]' -var="max_event_days=6"
```

Para seguir el avance del job, mira su log por Session Manager:

```bash
aws ssm start-session --target "$(terraform output -raw training_instance_id)"
# dentro: tail -f /var/log/training.log
```

### Apagar el entrenamiento

Para no dejar la EC2 de entrenamiento encendida:

```bash
terraform apply -var="enable_training=false"
```

## Ver la URL de nuevo

```bash
terraform output viewer_url
```

## Entrar a la instancia (sin SSH)

La EC2 no abre el puerto 22. Para una consola usa Session Manager:

```bash
aws ssm start-session --target "$(terraform output -raw instance_id)"
```

El registro del aprovisionamiento está en `/var/log/viewer-setup.log` dentro de la instancia.

## Borrar todo

```bash
terraform destroy
```

Elimina la EC2, CloudFront, el bucket (con sus datos; `force_destroy = true`), el rol de IAM y el
*security group*. Tus archivos locales no se tocan.

## Variables

Se ajustan con `-var` o un archivo `terraform.tfvars`:

| Variable | Por defecto | Qué es |
|---|---|---|
| `region` | `us-east-1` | Región de AWS (CloudFront exige us-east-1 para el WAF). |
| `environment` | `dev` | Etiqueta y prefijo de nombres. |
| `project_name` | `mesocyclonic` | Prefijo de nombres. |
| `repo_url` | `https://github.com/idia-tt/aws-mesocyclonic.git` | Repo que clona la EC2 para construir la imagen. |
| `repo_branch` | `main` | Rama a clonar. |
| `instance_type` | `t3.large` | Tipo de EC2 (2 vCPU, 8 GB). |
| `root_volume_gib` | `30` | Disco raíz; la imagen Docker ocupa varios GB. |

## Costo aproximado (us-east-1, encendido 24/7)

| Recurso | USD/mes |
|---|---|
| EC2 `t3.large` | ~60 |
| Disco gp3 30 GB | ~2 |
| CloudFront, S3, tráfico (poco uso) | ~1–3 |
| **Total** | **~65** |

Es más barato aún con un tipo menor (`t3.medium`, ~30 USD/mes) si la construcción de la imagen no te
apura. Si no lo usan, `terraform destroy` deja el costo en cero.

## Seguridad

- El visor es **público y sin login**: cualquiera con la URL lo ve. Es intencional; los datos son
  abiertos (catálogo CC BY 4.0, ERA5 y GOES). Si hay que restringirlo, se agrega autenticación
  delante (por ejemplo CloudFront + Cognito).
- El bucket es privado, cifrado y solo acepta TLS; la EC2 lo lee con un rol de IAM de solo lectura.
- El *security group* solo acepta el puerto 8501 desde CloudFront: no se puede saltar el HTTPS.
- La EC2 usa IMDSv2 obligatorio y no abre SSH (se entra por Session Manager).
