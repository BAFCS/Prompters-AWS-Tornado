# Laboratorio de experimentación de INGESTA DE DATOS (Desafío 1), aislado en el clon test.
# Una EC2 efímera en us-east-1 que prueba traer ERA5 recortado a Chile desde dos orígenes:
#   - Copernicus CDS (recorte en servidor con area:, pide solo MB)
#   - nsf-ncar-era5 (bloques globales por byte-range, lo que hace el pipeline actual)
# y escribe los resultados a nuestro bucket S3 (mesocyclonic-test-data-*). Se crea solo si
# enable_cdslab = true, para no dejarla encendida. Se activa con:
#   terraform apply -var-file=test.tfvars -var="enable_cdslab=true"
# y se apaga/borra con:
#   terraform apply -var-file=test.tfvars        (enable_cdslab vuelve a su default false)

variable "enable_cdslab" {
  description = "Si es true, crea la EC2 de experimentación de ingesta (CDS vs nsf-ncar-era5)."
  type        = bool
  default     = false
}

variable "cdslab_instance_type" {
  description = "Tipo de la EC2 del laboratorio. t3.medium basta y respeta el límite de la cuenta (<6xlarge, sin GPU)."
  type        = string
  default     = "t3.medium"
}

# --- Rol de IAM: lectura y ESCRITURA del bucket de datos (deja los datos ingeridos) ---
resource "aws_iam_role" "cdslab" {
  count              = var.enable_cdslab ? 1 : 0
  name_prefix        = "${var.project_name}-${var.environment}-cdslab-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "cdslab_s3" {
  statement {
    sid       = "ReadWriteDataBucketObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    sid       = "ListDataBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
}

resource "aws_iam_role_policy" "cdslab_s3" {
  count       = var.enable_cdslab ? 1 : 0
  name_prefix = "cdslab-s3-"
  role        = aws_iam_role.cdslab[0].id
  policy      = data.aws_iam_policy_document.cdslab_s3.json
}

resource "aws_iam_role_policy_attachment" "cdslab_ssm" {
  count      = var.enable_cdslab ? 1 : 0
  role       = aws_iam_role.cdslab[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "cdslab" {
  count       = var.enable_cdslab ? 1 : 0
  name_prefix = "${var.project_name}-${var.environment}-cdslab-"
  role        = aws_iam_role.cdslab[0].name
}

# --- Red: SG solo de SALIDA (habla con CDS en Europa y con S3; nadie entra salvo SSM) ---
resource "aws_security_group" "cdslab" {
  count       = var.enable_cdslab ? 1 : 0
  name_prefix = "${var.project_name}-${var.environment}-cdslab-"
  description = "Lab de ingesta: solo salida (CDS + S3). Entrada por Session Manager, sin SSH."
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "Salida a internet (CDS, S3, pip, apt)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

# --- Instancia: Amazon Linux 2023, prepara Python + cdsapi + herramientas de datos ---
# El user-data NO contiene la API key de CDS (no se versiona). El ~/.cdsapirc se inyecta
# después por Session Manager/SSM, para no dejar el secreto en el código ni en el user-data.
locals {
  cdslab_user_data = <<-EOF
    #!/bin/bash
    # Prioridad 1: dejar el agente SSM operativo cuanto antes (así podemos entrar aunque el
    # resto tarde). NO se hace 'dnf update -y' completo porque puede actualizar el propio
    # agente SSM y dejarlo reiniciándose, bloqueando el registro de la instancia.
    set -ux
    exec > >(tee /var/log/cdslab-setup.log) 2>&1
    echo "=== cdslab setup $(date -u) ==="

    # La AMI del proyecto (ami-0c1a9930d2846de36) NO trae el agente SSM preinstalado
    # (verificado en la consola serial: "Unit amazon-ssm-agent.service not found"). Lo
    # instalamos explícitamente desde los repos de AL2023 y lo habilitamos, para recuperar
    # el acceso por Session Manager.
    dnf install -y amazon-ssm-agent || dnf install -y https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/linux_amd64/amazon-ssm-agent.rpm || true
    systemctl enable --now amazon-ssm-agent || true
    systemctl restart amazon-ssm-agent || true

    # Dependencias mínimas, sin actualizar todo el sistema.
    dnf install -y python3 python3-pip git || true

    # Librerías de ingesta y comparación. Si algo falla, el agente SSM ya está arriba y podemos
    # terminar la instalación a mano.
    pip3 install --upgrade pip || true
    pip3 install "cdsapi>=0.7.7" "xarray" "zarr" "s3fs" "netCDF4" "h5py" "numpy" "pandas" || true

    echo "=== cdslab listo $(date -u) ==="
  EOF
}

resource "aws_instance" "cdslab" {
  count                  = var.enable_cdslab ? 1 : 0
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.cdslab_instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.cdslab[0].id]
  iam_instance_profile   = aws_iam_instance_profile.cdslab[0].name

  associate_public_ip_address = true
  user_data                   = local.cdslab_user_data
  user_data_replace_on_change = true

  root_block_device {
    volume_size = 40 # ERA5 descarga temporalmente; 40 GB da holgura
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens   = "required" # IMDSv2 obligatorio
    http_endpoint = "enabled"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-cdslab"
  }

  depends_on = [aws_s3_bucket.data]
}

output "cdslab_instance_id" {
  description = "ID de la EC2 del laboratorio de ingesta (para Session Manager)."
  value       = var.enable_cdslab ? aws_instance.cdslab[0].id : "cdslab deshabilitado"
}
