# Red: se usa la VPC por defecto de la cuenta y una de sus subredes públicas. El Security Group
# solo deja entrar el puerto 8501 (Streamlit) desde la lista de prefijos administrada de
# CloudFront, así nadie puede saltarse el HTTPS llegando directo a la instancia.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

# Lista de prefijos de las IP de los nodos de borde de CloudFront orientados al origen.
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "viewer" {
  name_prefix = "${var.project_name}-${var.environment}-viewer-"
  description = "Visor Streamlit: entrada solo desde CloudFront en el puerto 8501"
  vpc_id      = data.aws_vpc.default.id

  # Solo CloudFront puede llegar al puerto del visor.
  ingress {
    description     = "Streamlit desde CloudFront"
    from_port       = 8501
    to_port         = 8501
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }

  # Salida libre: la instancia clona el repo, baja paquetes y lee S3.
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
