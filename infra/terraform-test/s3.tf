# Bucket privado con los datos del visor (crops, catálogo y costa). La EC2 los descarga a
# /app/data al arrancar. Sin acceso público: solo la instancia lo lee, por su rol de IAM.

resource "aws_s3_bucket" "data" {
  bucket_prefix = "${var.project_name}-${var.environment}-data-"
  force_destroy = true # permite borrar el bucket con objetos al hacer destroy
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket = aws_s3_bucket.data.id
  # Cuando data_bucket_public=true, se afloja el bloqueo para permitir la política pública.
  # En dev (default false) el bucket queda totalmente privado.
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = var.data_bucket_public ? false : true
  restrict_public_buckets = var.data_bucket_public ? false : true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Política del bucket: solo TLS, lectura de resultados/ por CloudFront vía OAC, y
# -si data_bucket_public=true- lectura anónima de todo el data lake para el equipo.
resource "aws_s3_bucket_policy" "data_tls_only" {
  bucket = aws_s3_bucket.data.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.data.arn,
          "${aws_s3_bucket.data.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      },
      {
        Sid       = "AllowCloudFrontReadResults"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.data.arn}/resultados/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.viewer.arn
          }
        }
      },
      ], var.data_bucket_public ? [
      {
        Sid       = "PublicReadData"
        Effect    = "Allow"
        Principal = "*"
        Action    = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.data.arn,
          "${aws_s3_bucket.data.arn}/*",
        ]
      },
    ] : [])
  })

  # La política pública requiere que el public_access_block ya la permita.
  depends_on = [aws_s3_bucket_public_access_block.data]
}
