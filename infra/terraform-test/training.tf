# EC2 de ENTRENAMIENTO, aparte del visor y en us-west-2 (donde vive ERA5). Genera los índices,
# entrena XGBoost y sube los resultados al prefijo "resultados/" del bucket de datos (us-east-1).
# Es efímera: con stop_after_training = true se apaga sola al terminar.

# --- AMI de Amazon Linux 2023 en us-west-2 --------------------------------------------------
data "aws_ami" "al2023_training" {
  provider    = aws.training
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

# --- Rol de IAM de la EC2 de entrenamiento --------------------------------------------------
resource "aws_iam_role" "training" {
  count              = var.enable_training ? 1 : 0
  name_prefix        = "${var.project_name}-${var.environment}-train-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# Lectura y escritura del bucket de datos (lee el catálogo, escribe resultados/).
data "aws_iam_policy_document" "training_s3" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
  # Permite que la instancia se apague a sí misma al terminar el job.
  statement {
    actions   = ["ec2:StopInstances"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "training_s3" {
  count       = var.enable_training ? 1 : 0
  name_prefix = "train-s3-"
  role        = aws_iam_role.training[0].id
  policy      = data.aws_iam_policy_document.training_s3.json
}

resource "aws_iam_role_policy_attachment" "training_ssm" {
  count      = var.enable_training ? 1 : 0
  role       = aws_iam_role.training[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "training" {
  count       = var.enable_training ? 1 : 0
  name_prefix = "${var.project_name}-${var.environment}-train-"
  role        = aws_iam_role.training[0].name
}

# --- Red en us-west-2: VPC por defecto, SG solo de salida -----------------------------------
data "aws_vpc" "training_default" {
  provider = aws.training
  default  = true
}

data "aws_subnets" "training_default" {
  provider = aws.training
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.training_default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

resource "aws_security_group" "training" {
  count       = var.enable_training ? 1 : 0
  provider    = aws.training
  name_prefix = "${var.project_name}-${var.environment}-train-"
  description = "EC2 de entrenamiento: solo salida (baja ERA5 y sube a S3). Sin entrada."
  vpc_id      = data.aws_vpc.training_default.id

  egress {
    description = "Salida a internet"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

# --- Instancia de entrenamiento -------------------------------------------------------------
locals {
  training_user_data = templatefile("${path.module}/training_user_data.sh.tftpl", {
    data_bucket     = aws_s3_bucket.data.bucket
    bucket_region   = var.region
    training_region = var.training_region
    repo_url        = var.repo_url
    repo_branch     = var.repo_branch
    region_name     = "south-central-austral"
    max_event_days  = var.max_event_days
    unlabeled_days  = var.unlabeled_days
    stop_after      = var.stop_after_training ? "true" : "false"
  })
}

resource "aws_instance" "training" {
  count                  = var.enable_training ? 1 : 0
  provider               = aws.training
  ami                    = data.aws_ami.al2023_training.id
  instance_type          = var.training_instance_type
  subnet_id              = data.aws_subnets.training_default.ids[0]
  vpc_security_group_ids = [aws_security_group.training[0].id]
  iam_instance_profile   = aws_iam_instance_profile.training[0].name

  associate_public_ip_address = true
  user_data_replace_on_change = true
  user_data                   = local.training_user_data

  root_block_device {
    volume_size = var.training_volume_gib
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-training"
  }

  depends_on = [aws_s3_bucket.data]
}
