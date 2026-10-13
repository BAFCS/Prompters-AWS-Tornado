# Una máquina EC2 con el visor en Docker, en us-west-2: la región de ERA5 (nsf-ncar-era5), la fuente
# más pesada (cada hora de niveles de presión es un bloque global de ~50–65 MB). GOES queda en
# us-east-1, pero sus lecturas son recortes por bloques y pesan mucho menos.
# Sin puerto 22: se entra con `aws ssm start-session --target <instance_id>`.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

provider "aws" {
  region = "us-west-2"
}

variable "allowed_cidr" {
  description = "Red que puede abrir el visor (Streamlit no tiene autenticación), p. ej. 200.9.100.75/32"
  type        = string
}

variable "instance_type" {
  description = "t3.large (8 GB) alcanza para el visor y para procesar ERA5 día a día"
  type        = string
  default     = "t3.large"
}

variable "repo" {
  description = "Repositorio y rama que la máquina clona y construye"
  type        = object({ url = string, branch = string })
  default     = { url = "https://github.com/fforster/aws-mesocyclonic.git", branch = "main" }
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_security_group" "viewer" {
  name = "mesocyclonic-viewer"

  ingress {
    from_port   = 8501
    to_port     = 8501
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "viewer" {
  name = "mesocyclonic-viewer"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.viewer.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "viewer" {
  name = "mesocyclonic-viewer"
  role = aws_iam_role.viewer.name
}

resource "aws_instance" "viewer" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  iam_instance_profile   = aws_iam_instance_profile.viewer.name
  vpc_security_group_ids = [aws_security_group.viewer.id]
  user_data = templatefile("${path.module}/user_data.sh", {
    repo_url = var.repo.url, branch = var.repo.branch
  })

  # Los recortes viven en el disco raíz (/opt/mesocyclonic/data); crecer el volumen no rehace la máquina.
  root_block_device {
    volume_size = 60
    volume_type = "gp3"
  }

  metadata_options {
    http_tokens = "required"
  }

  tags = { Name = "mesocyclonic-viewer" }
}

resource "aws_eip" "viewer" {
  instance = aws_instance.viewer.id
}

output "url" {
  value = "http://${aws_eip.viewer.public_ip}:8501"
}

output "instance_id" {
  value = aws_instance.viewer.id
}
