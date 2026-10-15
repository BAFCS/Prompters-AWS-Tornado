# Versiones de Terraform y del proveedor de AWS. us-east-1 es obligatorio porque CloudFront y
# (si se activa) WAF viven en esa región.
terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project     = "aws-mesocyclonic"
      environment = var.environment
      managed_by  = "terraform"
    }
  }
}

# Proveedor para la EC2 de entrenamiento, en la región donde vive ERA5 (us-west-2): así la
# transferencia de los ~12 GB/día de ERA5 es dentro de la región, rápida y sin costo de salida.
provider "aws" {
  alias  = "training"
  region = var.training_region

  default_tags {
    tags = {
      project     = "aws-mesocyclonic"
      environment = var.environment
      managed_by  = "terraform"
    }
  }
}
