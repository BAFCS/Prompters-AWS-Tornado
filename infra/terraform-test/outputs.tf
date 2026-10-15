# Salidas útiles tras el despliegue.

output "viewer_url" {
  description = "URL pública del visor (HTTPS) para compartir."
  value       = "https://${aws_cloudfront_distribution.viewer.domain_name}"
}

output "results_url" {
  description = "URL del reporte de resultados del entrenamiento (disponible tras correr el job)."
  value       = "https://${aws_cloudfront_distribution.viewer.domain_name}/resultados/reporte.html"
}

output "training_instance_id" {
  description = "ID de la EC2 de entrenamiento (us-west-2), si está habilitada."
  value       = var.enable_training ? aws_instance.training[0].id : "entrenamiento deshabilitado"
}

output "data_bucket" {
  description = "Nombre del bucket S3 con los datos del visor."
  value       = aws_s3_bucket.data.bucket
}

output "instance_id" {
  description = "ID de la instancia EC2 (para Session Manager y logs)."
  value       = aws_instance.viewer.id
}

output "instance_public_dns" {
  description = "DNS público de la EC2 que usa CloudFront como origen."
  value       = aws_instance.viewer.public_dns
}

output "cloudfront_distribution_id" {
  description = "ID de la distribución de CloudFront (para invalidaciones)."
  value       = aws_cloudfront_distribution.viewer.id
}
