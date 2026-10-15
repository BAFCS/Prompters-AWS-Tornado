# Despliegue del visor en AWS (CDK)

> [!NOTE]
> Para la **ingesta de datos optimizada** (data lake multi-fuente ERA5+GOES en S3, recortado a
> Chile, con flota de EC2 en paralelo ~25× más rápida que la descarga día a día), ver
> `docs/ARQUITECTURA_CLON.md`, `docs/DATOS_AWS.md`, `docs/ESTADO_ACTUAL.md` y `docs/PENDIENTES.md`.

Con un solo comando, `cdk deploy` crea en tu cuenta de AWS:

```
Equipo (navegador) ─HTTPS─► CloudFront ─► Balanceador (ALB) ─► Streamlit en ECS Fargate
                                                                     │ al arrancar copia data/
                                                                     ▼
                                                           S3 (bucket privado con data/)
```

- Sube `data/crops/`, `data/tornados_chile.xlsx` y `data/coast.zip` a un bucket S3 privado.
- Construye la imagen con el `Dockerfile` del repositorio y la corre en Fargate.
- Entrega una URL pública `https://xxxx.cloudfront.net` para compartir con el equipo.

## Requisitos

- Lo del README principal: `uv`, `uv sync` y al menos un día de datos en `data/` (pasos 1 a 5).
- Node.js 18 o superior (`node --version`). CDK se ejecuta con `npx`, no hace falta instalarlo.
- Docker en marcha (`docker info` no debe dar error). En Linux: `sudo systemctl start docker`.

## Pasos

Todos desde la carpeta `infra/`, en la **misma terminal** donde exportas las credenciales.

1. Exporta las credenciales de tu sesión de AWS (las copias del portal de acceso de AWS):

   ```bash
   export AWS_DEFAULT_REGION="us-east-1"
   export AWS_ACCESS_KEY_ID="..."
   export AWS_SECRET_ACCESS_KEY="..."
   export AWS_SESSION_TOKEN="..."
   ```

   No las guardes en archivos del repositorio ni las pegues en chats.

2. Prepara la cuenta para CDK (solo la primera vez por cuenta y región):

   ```bash
   cd infra
   npx -y aws-cdk@2.1145.0 bootstrap
   ```

3. Despliega:

   ```bash
   npx -y aws-cdk@2.1145.0 deploy
   ```

   Responde `y` cuando pregunte por los permisos. Tarda entre 10 y 20 minutos la primera vez.
   Al final imprime `MesocyclonicViewer.ViewerUrl = https://...`: esa es la URL del visor.
   El visor puede tardar 1 o 2 minutos más en responder mientras copia los datos.

## Agregar días nuevos

Descarga y procesa el día en tu computador (paso 5 del README principal) y vuelve a correr
`npx -y aws-cdk@2.1145.0 deploy`. CDK sube solo lo nuevo y reinicia el visor con los datos.

## Ver la URL de nuevo

```bash
aws cloudformation describe-stacks --stack-name MesocyclonicViewer \
  --query "Stacks[0].Outputs[?OutputKey=='ViewerUrl'].OutputValue" --output text
```

(o en la consola de AWS: CloudFormation → MesocyclonicViewer → Outputs).

## Borrar todo

```bash
npx -y aws-cdk@2.1145.0 destroy
```

Elimina todos los recursos, incluido el bucket con los datos (tus archivos locales no se tocan).

## Costo aproximado (us-east-1, encendido 24/7)

| Recurso | USD/mes |
|---|---|
| Fargate 1 vCPU, 2 GB | ~36 |
| Balanceador (ALB) | ~18 |
| IPs públicas (tarea + ALB) | ~11 |
| CloudFront, S3, logs (poco tráfico) | ~1 |
| **Total** | **~65** |

Si no lo usan, bórralo con `destroy` y vuelve a desplegarlo cuando haga falta.

## Seguridad

- El visor es público y sin login: cualquiera con la URL lo ve. Es intencional, los datos son
  abiertos (catálogo CC BY 4.0, ERA5 y GOES). Si necesitan restringirlo, hay que agregar
  autenticación (por ejemplo Cognito en el balanceador).
- El bucket es privado y cifrado; solo el visor lo puede leer.
- El balanceador solo acepta tráfico desde CloudFront, así que no se puede saltar el HTTPS.
