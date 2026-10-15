# Instancia EC2 que corre el visor. Usa la última AMI de Amazon Linux 2023 (x86_64), un disco
# raíz amplio para la imagen Docker y el user-data que construye y arranca el visor.

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  # El hash del user-data fuerza a recrear la instancia cuando cambia el aprovisionamiento.
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    data_bucket = aws_s3_bucket.data.bucket
    region      = var.region
    repo_url    = var.repo_url
    repo_branch = var.repo_branch
  })
}

resource "aws_instance" "viewer" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.viewer.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  # IP pública para que CloudFront llegue a la instancia por su DNS público.
  associate_public_ip_address = true

  user_data_replace_on_change = true
  user_data                   = local.user_data

  root_block_device {
    volume_size = var.root_volume_gib
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens   = "required" # IMDSv2 obligatorio
    http_endpoint = "enabled"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-viewer"
  }

  # El bucket tiene que existir antes de que la instancia sincronice los datos.
  depends_on = [
    aws_s3_bucket.data,
  ]
}
