# CloudFront: única entrada pública, con HTTPS y el certificado *.cloudfront.net. El origen es el
# DNS público de la EC2 por HTTP en el 8501. No cachea nada (Streamlit es dinámico y usa WebSocket)
# y reenvía todas las cabeceras, cookies y parámetros al origen.

# Política de caché: desactivada (todo dinámico).
data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

# Política de petición al origen: reenvía todo lo del visitante.
data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}

# Política de caché optimizada para los resultados estáticos en S3.
data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

# Control de acceso de origen (OAC): deja que CloudFront lea el bucket S3 privado (resultados/).
resource "aws_cloudfront_origin_access_control" "results" {
  name                              = "${var.project_name}-${var.environment}-results-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "viewer" {
  enabled         = true
  comment         = "Visor aws-mesocyclonic (${var.environment})"
  price_class     = "PriceClass_All" # incluye nodos de borde en Sudamérica
  http_version    = "http2and3"
  is_ipv6_enabled = true

  origin {
    origin_id   = "viewer-ec2"
    domain_name = aws_instance.viewer.public_dns

    custom_origin_config {
      http_port                = 8501
      https_port               = 443
      origin_protocol_policy   = "http-only" # el SG solo deja entrar a CloudFront
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }
  }

  # Segundo origen: el bucket S3 con los resultados del entrenamiento (model.json, reporte.html...).
  origin {
    origin_id                = "results-s3"
    domain_name              = aws_s3_bucket.data.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.results.id
    origin_path              = "/resultados"
  }

  default_cache_behavior {
    target_origin_id         = "viewer-ec2"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
  }

  # /resultados/* -> reporte y modelo del entrenamiento, servidos desde S3.
  ordered_cache_behavior {
    path_pattern           = "/resultados/*"
    target_origin_id       = "results-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }
}
