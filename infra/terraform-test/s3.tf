# Bucket privado con los datos del visor (crops, catálogo y costa). La EC2 los descarga a
# /app/data al arrancar. Sin acceso público: solo la instancia lo lee, por su rol de IAM.

resource "aws_s3_bucket" "data" {
  bucket_prefix = "${var.project_name}-${var.environment}-data-"
  force_destroy = true # permite borrar el bucket con objetos al hacer destroy
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Política del bucket: solo TLS, y lectura de resultados/ por CloudFront vía OAC.
resource "aws_s3_bucket_policy" "data_tls_only" {
  bucket = aws_s3_bucket.data.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
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
    ]
  })
}
