# Infraestructura de SageMaker y Bedrock en ml_region (us-west-2). No crea trabajos, modelos ni
# endpoints: eso lo hace el SDK desde scripts/model/launch_sagemaker.py. Aquí solo quedan el bucket
# de artefactos del modelo y el rol de ejecución con permisos mínimos. training.tf no se toca.

# Identidad y partición en ml_region, para acotar los ARN del rol a esta cuenta y región.
data "aws_caller_identity" "ml" {
  provider = aws.ml
}

data "aws_partition" "ml" {
  provider = aws.ml
}

locals {
  # ARN de los modelos de embeddings de Bedrock que el rol puede invocar. Titan siempre; Cohere
  # Embed v4 solo si enable_cohere. Los foundation-model no llevan cuenta en el ARN.
  bedrock_titan_arn  = "arn:${data.aws_partition.ml.partition}:bedrock:${var.ml_region}::foundation-model/amazon.titan-embed-image-v1"
  bedrock_cohere_arn = "arn:${data.aws_partition.ml.partition}:bedrock:${var.ml_region}::foundation-model/cohere.embed-v4:0"
  bedrock_model_arns = var.enable_cohere ? [local.bedrock_titan_arn, local.bedrock_cohere_arn] : [local.bedrock_titan_arn]
}

# --- Bucket de artefactos del modelo (us-west-2) --------------------------------------------
# Tablas, folds, resultados, modelos e inferencias bajo el prefijo model/. Privado y cifrado.
resource "aws_s3_bucket" "ml" {
  provider      = aws.ml
  bucket_prefix = "${var.project_name}-${var.environment}-ml-"
  force_destroy = true # permite borrar el bucket con objetos al hacer destroy
}

resource "aws_s3_bucket_public_access_block" "ml" {
  provider                = aws.ml
  bucket                  = aws_s3_bucket.ml.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ml" {
  provider = aws.ml
  bucket   = aws_s3_bucket.ml.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Solo TLS sobre el bucket ML.
resource "aws_s3_bucket_policy" "ml_tls_only" {
  provider = aws.ml
  bucket   = aws_s3_bucket.ml.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.ml.arn,
          "${aws_s3_bucket.ml.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      },
    ]
  })
}

# --- Rol de ejecución de SageMaker ----------------------------------------------------------
data "aws_iam_policy_document" "sagemaker_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sagemaker_exec" {
  provider           = aws.ml
  name_prefix        = "${var.project_name}-${var.environment}-sm-"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume.json
}

# Política inline con permisos mínimos. Sin acciones "*", sin iam:*, sin s3:DeleteBucket ni
# s3:PutBucketPolicy. La única declaración con Resource "*" es cloudwatch:PutMetricData, acotada
# por condición al espacio de nombres /aws/sagemaker/* (AWS no admite otro recurso para esa acción).
data "aws_iam_policy_document" "sagemaker_exec" {
  # Lectura y escritura de los artefactos del modelo (prefijo model/).
  statement {
    sid     = "MlBucketObjects"
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = [
      "${aws_s3_bucket.ml.arn}/model/*",
    ]
  }

  statement {
    sid       = "MlBucketList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.ml.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["model/*"]
    }
  }

  # Lectura del Catálogo en el bucket de datos (prefijo data/).
  statement {
    sid     = "DataCatalogObjects"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data.arn}/data/*",
    ]
  }

  statement {
    sid       = "DataCatalogList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["data/*"]
    }
  }

  # Lectura y listado de los buckets públicos de ERA5 y GOES.
  statement {
    sid     = "PublicDataRead"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:${data.aws_partition.ml.partition}:s3:::nsf-ncar-era5",
      "arn:${data.aws_partition.ml.partition}:s3:::nsf-ncar-era5/*",
      "arn:${data.aws_partition.ml.partition}:s3:::noaa-goes16",
      "arn:${data.aws_partition.ml.partition}:s3:::noaa-goes16/*",
      "arn:${data.aws_partition.ml.partition}:s3:::noaa-goes19",
      "arn:${data.aws_partition.ml.partition}:s3:::noaa-goes19/*",
    ]
  }

  # Bedrock: InvokeModel acotado a los ARN de Titan y, opcionalmente, Cohere Embed v4.
  statement {
    sid       = "BedrockInvoke"
    actions   = ["bedrock:InvokeModel"]
    resources = local.bedrock_model_arns
  }

  # CloudWatch Logs de los trabajos de SageMaker, acotado a /aws/sagemaker/*.
  statement {
    sid = "SageMakerLogs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = [
      "arn:${data.aws_partition.ml.partition}:logs:${var.ml_region}:${data.aws_caller_identity.ml.account_id}:log-group:/aws/sagemaker/*",
      "arn:${data.aws_partition.ml.partition}:logs:${var.ml_region}:${data.aws_caller_identity.ml.account_id}:log-group:/aws/sagemaker/*:log-stream:*",
    ]
  }

  # Única excepción de Resource "*" (Req. 9.2): PutMetricData no admite otro recurso.
  # Se acota con condición al espacio de nombres /aws/sagemaker/*.
  statement {
    sid       = "SageMakerMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringLike"
      variable = "cloudwatch:namespace"
      values   = ["/aws/sagemaker/*"]
    }
  }
}

resource "aws_iam_role_policy" "sagemaker_exec" {
  provider    = aws.ml
  name_prefix = "sm-exec-"
  role        = aws_iam_role.sagemaker_exec.id
  policy      = data.aws_iam_policy_document.sagemaker_exec.json
}
