# FLOTA DE WORKERS DE INGESTA con sharding, para el "mejor método": escalar horizontal.
# Cada worker es una EC2 idéntica que al arrancar: instala el entorno, baja los scripts del S3 y
# ejecuta SU shard del rango de días (--shard-index = su índice, --shard-total = tamaño de la flota).
# Así N workers procesan el rango en 1/N del tiempo, sin saturar una sola máquina (lección de los
# 24 workers) y sin solaparse (cada día lo toma un solo shard). Resiliente: si uno falla, el resto
# sigue. Todo versionado y destruible con terraform destroy.
#
#   terraform apply ... -var="ncar_fleet_size=6"   # 6 workers para ncar
#   terraform apply ... -var="goes_fleet_size=4"   # 4 workers para GOES
#
# Respeta permisos: c7i.2xlarge = 8 vCPU (< 6xlarge, sin GPU), us-east-1.

variable "ncar_fleet_size" {
  description = "Número de EC2 worker para ingesta ncar (sharding). 0 = ninguna."
  type        = number
  default     = 0
}

# AMI fija para la flota: evita que data.aws_ami.al2023 (most_recent) fuerce recrear workers vivos
# cuando AWS publica una AMI nueva. Vacío = usa la dinámica. Se fija al ID actual al escalar.
variable "worker_ami" {
  description = "AMI fija para los workers de flota (vacío = usa la AMI dinámica al2023)."
  type        = string
  default     = ""
}

locals {
  worker_ami = var.worker_ami != "" ? var.worker_ami : data.aws_ami.al2023.id
}

variable "goes_fleet_size" {
  description = "Número de EC2 worker para ingesta GOES (sharding). 0 = ninguna."
  type        = number
  default     = 0
}

variable "fleet_start" {
  description = "Primer día del rango de ingesta de la flota (AAAA-MM-DD)."
  type        = string
  default     = "2025-10-15"
}

variable "fleet_end" {
  description = "Último día del rango de ingesta de la flota (AAAA-MM-DD)."
  type        = string
  default     = "2026-09-30"
}

# user-data del worker: ver worker_user_data.sh.tftpl (templatefile robusto, sin escapes frágiles).

resource "aws_instance" "ncar_worker" {
  count                       = var.ncar_fleet_size
  ami                         = local.worker_ami
  instance_type               = "c7i.2xlarge" # 8 vCPU / 16 GB (<6xlarge, sin GPU)
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.cdslab[0].id]
  iam_instance_profile        = aws_iam_instance_profile.cdslab[0].name
  associate_public_ip_address = true
  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/worker_user_data.sh.tftpl", {
    bucket      = aws_s3_bucket.data.bucket
    region      = var.region
    source      = "ncar"
    idx         = count.index
    total       = var.ncar_fleet_size
    fleet_start = var.fleet_start
    fleet_end   = var.fleet_end
  })

  root_block_device {
    volume_size = 40
    volume_type = "gp3"
    encrypted   = true
  }
  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }
  tags = { Name = "${var.project_name}-${var.environment}-ncar-worker-${count.index}" }
  depends_on = [aws_s3_bucket.data, aws_iam_instance_profile.cdslab]
}

output "ncar_fleet_ids" {
  value = aws_instance.ncar_worker[*].id
}

resource "aws_instance" "goes_worker" {
  count                       = var.goes_fleet_size
  ami                         = local.worker_ami
  instance_type               = "c7i.2xlarge" # 8 vCPU / 16 GB (<6xlarge, sin GPU)
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.cdslab[0].id]
  iam_instance_profile        = aws_iam_instance_profile.cdslab[0].name
  associate_public_ip_address = true
  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/worker_user_data.sh.tftpl", {
    bucket      = aws_s3_bucket.data.bucket
    region      = var.region
    source      = "goes"
    idx         = count.index
    total       = var.goes_fleet_size
    fleet_start = var.fleet_start
    fleet_end   = var.fleet_end
  })

  root_block_device {
    volume_size = 60 # GOES pesa más (imágenes)
    volume_type = "gp3"
    encrypted   = true
  }
  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }
  tags       = { Name = "${var.project_name}-${var.environment}-goes-worker-${count.index}" }
  depends_on = [aws_s3_bucket.data, aws_iam_instance_profile.cdslab]
}

output "goes_fleet_ids" {
  value = aws_instance.goes_worker[*].id
}

