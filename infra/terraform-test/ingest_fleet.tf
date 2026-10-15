# EC2 de ingesta aisladas para que cada fuente avance por su lado sin competir recursos ni
# romper lo que ya corre en la cdslab (CDS). Reutilizan el rol IAM, el instance profile y el
# security group del cdslab (mismo acceso: lectura/escritura al bucket, salida a internet, SSM).
# Se crean solo si enable_ingest_fleet = true.
#
#   terraform apply -var-file=test.tfvars -var="enable_cdslab=true" -var="enable_ingest_fleet=true"
#
# La AMI y el user-data (que instala el agente SSM + python) se comparten con cdslab.

variable "enable_ingest_fleet" {
  description = "Si es true, crea 2 EC2 extra de ingesta (ncar y goes), aisladas de la cdslab."
  type        = bool
  default     = false
}

# EC2 dedicada a la ingesta ERA5 por bucket directo (nsf-ncar-era5 -> Zarr).
resource "aws_instance" "ingest_ncar" {
  count                  = var.enable_ingest_fleet ? 1 : 0
  ami                    = data.aws_ami.al2023.id
  instance_type          = "r7i.2xlarge" # 8 vCPU / 64 GB RAM: la memoria es el límite al paralelizar días ERA5 (c/día carga bloques globales)
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.cdslab[0].id]
  iam_instance_profile   = aws_iam_instance_profile.cdslab[0].name

  associate_public_ip_address = true
  user_data                   = local.cdslab_user_data
  user_data_replace_on_change = true

  root_block_device {
    volume_size = 50
    volume_type = "gp3"
    encrypted   = true
  }
  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }
  tags = { Name = "${var.project_name}-${var.environment}-ingest-ncar" }
  depends_on = [aws_s3_bucket.data]
}

# EC2 dedicada a la ingesta GOES (noaa-goes16/19, us-east-1, intra-región).
resource "aws_instance" "ingest_goes" {
  count                  = var.enable_ingest_fleet ? 1 : 0
  ami                    = data.aws_ami.al2023.id
  instance_type          = "t3.large"
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.cdslab[0].id]
  iam_instance_profile   = aws_iam_instance_profile.cdslab[0].name

  associate_public_ip_address = true
  user_data                   = local.cdslab_user_data
  user_data_replace_on_change = true

  root_block_device {
    volume_size = 60 # GOES pesa más (imágenes)
    volume_type = "gp3"
    encrypted   = true
  }
  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }
  tags = { Name = "${var.project_name}-${var.environment}-ingest-goes" }
  depends_on = [aws_s3_bucket.data]
}

output "ingest_ncar_instance_id" {
  value = var.enable_ingest_fleet ? aws_instance.ingest_ncar[0].id : "flota deshabilitada"
}

output "ingest_goes_instance_id" {
  value = var.enable_ingest_fleet ? aws_instance.ingest_goes[0].id : "flota deshabilitada"
}
