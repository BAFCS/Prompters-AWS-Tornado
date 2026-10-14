"""Pila de AWS del visor: S3 con los datos, Streamlit en ECS Fargate y CloudFront con HTTPS.

Flujo: ``cdk deploy`` sube ``data/`` al bucket, construye la imagen con el ``Dockerfile`` del
repositorio y la ejecuta en Fargate. Al arrancar, el contenedor copia ``data/`` desde S3 a
``/app/data`` y abre Streamlit. CloudFront es la única entrada pública: el balanceador solo
acepta tráfico desde CloudFront.
"""

from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Size,
    Stack,
)
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import custom_resources as cr
from constructs import Construct

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# Solo lo que lee el visor; descargas crudas u otros archivos de data/ no se suben.
DATA_EXCLUDE = ["*", "!crops", "!crops/**", "!tornados_chile.xlsx", "!coast.zip"]

# Tamaño de la tarea Fargate: 1 vCPU y 2 GB alcanzan para un par de días de datos.
CPU = 1024
MEMORY_MIB = 2048

# Código que corre en el contenedor antes de Streamlit: copia data/ desde S3 a /app/data.
SYNC_CODE = """
import os, pathlib, botocore.session
s3 = botocore.session.get_session().create_client("s3")
bucket = os.environ["DATA_BUCKET"]
count = 0
for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="data/"):
    for obj in page.get("Contents", []):
        dest = pathlib.Path("/app", obj["Key"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read())
        count += 1
print(f"Datos copiados desde S3: {count} archivos", flush=True)
"""


class ViewerStack(Stack):
    """Recursos del visor público: bucket de datos, servicio Fargate, balanceador y CloudFront."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        """Define todos los recursos de la pila."""
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]

        # --- Datos en S3 (privado, cifrado, solo TLS) ---------------------------------------
        bucket = s3.Bucket(
            self,
            "DataBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        data_version = "sin-datos"
        upload: s3deploy.BucketDeployment | None = None
        if DATA.is_dir():
            asset = s3_assets.Asset(self, "DataAsset", path=str(DATA), exclude=DATA_EXCLUDE)
            data_version = asset.asset_hash
            upload = s3deploy.BucketDeployment(
                self,
                "DataUpload",
                sources=[s3deploy.Source.bucket(asset.bucket, asset.s3_object_key)],
                destination_bucket=bucket,
                destination_key_prefix="data/",
                prune=False,
                memory_limit=1024,
                ephemeral_storage_size=Size.gibibytes(4),
            )

        # --- Red mínima: subredes públicas, sin NAT (ahorra ~32 USD/mes) ----------------------
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC)
            ],
        )
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)

        # --- Visor Streamlit en Fargate detrás de un balanceador -----------------------------
        image = ecs.ContainerImage.from_asset(str(ROOT), platform=ecr_assets.Platform.LINUX_AMD64)
        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "Viewer",
            cluster=cluster,
            cpu=CPU,
            memory_limit_mib=MEMORY_MIB,
            desired_count=1,
            min_healthy_percent=100,  # mantiene el visor arriba durante los despliegues
            public_load_balancer=True,
            open_listener=False,  # el acceso se abre solo a CloudFront, más abajo
            assign_public_ip=True,
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            health_check_grace_period=Duration.minutes(5),
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.X86_64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=image,
                container_port=8501,
                command=[
                    "sh",
                    "-c",
                    'python -c "$SYNC_CODE" && exec streamlit run scripts/viewer/viewer.py'
                    " --server.address=0.0.0.0 --server.port=8501",
                ],
                environment={
                    "DATA_BUCKET": bucket.bucket_name,
                    "AWS_DEFAULT_REGION": self.region,
                    "SYNC_CODE": SYNC_CODE,
                    # Cambia cuando cambian los datos: fuerza a ECS a reiniciar con lo nuevo.
                    "DATA_VERSION": data_version,
                },
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="viewer", log_retention=logs.RetentionDays.TWO_WEEKS
                ),
            ),
        )
        bucket.grant_read(service.task_definition.task_role)
        if upload is not None:
            service.service.node.add_dependency(upload)

        service.target_group.configure_health_check(
            path="/_stcore/health", healthy_http_codes="200", interval=Duration.seconds(30)
        )
        # Streamlit mantiene la sesión en un WebSocket: misma tarea para cada visitante.
        service.target_group.enable_cookie_stickiness(Duration.hours(1))
        service.load_balancer.set_attribute("idle_timeout.timeout_seconds", "900")

        # El balanceador solo acepta tráfico desde CloudFront (lista de prefijos administrada).
        prefix_list = cr.AwsCustomResource(
            self,
            "CloudFrontPrefixList",
            on_update=cr.AwsSdkCall(
                service="EC2",
                action="describeManagedPrefixLists",
                parameters={
                    "Filters": [
                        {
                            "Name": "prefix-list-name",
                            "Values": ["com.amazonaws.global.cloudfront.origin-facing"],
                        }
                    ]
                },
                physical_resource_id=cr.PhysicalResourceId.of("cloudfront-origin-facing"),
                output_paths=["PrefixLists.0.PrefixListId"],
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
            ),
            install_latest_aws_sdk=False,
        )
        service.load_balancer.connections.allow_from(
            ec2.Peer.prefix_list(prefix_list.get_response_field("PrefixLists.0.PrefixListId")),
            ec2.Port.tcp(80),
            "Solo CloudFront",
        )

        # --- CloudFront: URL pública con HTTPS, sin caché (Streamlit es dinámico) ------------
        distribution = cloudfront.Distribution(
            self,
            "Cdn",
            comment="Visor aws-mesocyclonic",
            price_class=cloudfront.PriceClass.PRICE_CLASS_ALL,  # incluye Sudamérica
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.LoadBalancerV2Origin(
                    service.load_balancer,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    read_timeout=Duration.seconds(60),
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
            ),
        )

        CfnOutput(self, "ViewerUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "DataBucketName", value=bucket.bucket_name)
        CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        CfnOutput(self, "ServiceName", value=service.service.service_name)
