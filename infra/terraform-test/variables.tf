# Variables del despliegue. Los valores por defecto bastan para la cuenta de la hackathon;
# cada uno se puede sobreescribir con -var o un archivo terraform.tfvars.

variable "region" {
  description = "Región de AWS. us-east-1 por CloudFront (y WAF si se activa)."
  type        = string
  default     = "us-east-1"
}

variable "training_region" {
  description = "Región de la EC2 de entrenamiento. us-east-1: la cuenta de hackathon deniega crear recursos en us-west-2. (ERA5 vive en us-west-2, así que la lectura es entre regiones.)"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Nombre del entorno; etiqueta los recursos y el prefijo de nombres."
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Prefijo para nombrar los recursos."
  type        = string
  default     = "mesocyclonic"
}

variable "repo_url" {
  description = "Repositorio Git que las EC2 clonan (visor y entrenamiento)."
  type        = string
  default     = "https://github.com/BAFCS/Prompters-AWS-Tornado.git"
}

variable "repo_branch" {
  description = "Rama del repositorio a clonar."
  type        = string
  default     = "main"
}

variable "instance_type" {
  description = "Tipo de instancia EC2. t3.large (2 vCPU, 8 GB) construye la imagen y corre el visor con holgura."
  type        = string
  default     = "t3.large"
}

variable "root_volume_gib" {
  description = "Tamaño del disco raíz en GiB. La imagen Docker con todas las librerías ocupa varios GB."
  type        = number
  default     = 30
}

# --- Entrenamiento (EC2 aparte) ---------------------------------------------------------------

variable "enable_training" {
  description = "Si es true, crea la EC2 de entrenamiento y la corre. Ponla en false para apagarla."
  type        = bool
  default     = true
}

variable "training_instance_type" {
  description = "Tipo de la EC2 de entrenamiento. c7i.2xlarge (8 vCPU) acelera el cálculo de índices."
  type        = string
  default     = "c7i.2xlarge"
}

variable "training_volume_gib" {
  description = "Disco de la EC2 de entrenamiento: ERA5 descarga mucho temporalmente."
  type        = number
  default     = 60
}

variable "max_event_days" {
  description = "Límite de días con evento a procesar (0 = todos los ~38). Bájalo para una prueba rápida."
  type        = number
  default     = 0
}

variable "unlabeled_days" {
  description = "Días extra SIN evento añadidos como no etiquetados del PU learning."
  type        = number
  default     = 10
}

variable "stop_after_training" {
  description = "Si es true, la EC2 de entrenamiento se apaga sola al terminar el job (ahorra costo)."
  type        = bool
  default     = true
}
