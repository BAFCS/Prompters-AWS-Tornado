# Variables del despliegue. Los valores por defecto bastan para la cuenta de la hackathon;
# cada uno se puede sobreescribir con -var o un archivo terraform.tfvars.

variable "region" {
  description = "Región de AWS. us-east-1 por CloudFront (y WAF si se activa)."
  type        = string
  default     = "us-east-1"
}

variable "training_region" {
  description = "Región de la EC2 de entrenamiento existente. Sigue en us-east-1 por la restricción histórica de la cuenta de hackathon (ERA5 vive en us-west-2, así que esa lectura es entre regiones). No afecta a SageMaker ni a Bedrock: ese flujo usa ml_region, independiente de esta variable."
  type        = string
  default     = "us-east-1"
}

# --- SageMaker y Bedrock ----------------------------------------------------------------------

variable "ml_region" {
  description = "Región de SageMaker (entrenamiento, modelos, Batch Transform, endpoints) y de las llamadas a Bedrock. Debe ser us-west-2, la región de nsf-ncar-era5. Independiente de training_region y de region."
  type        = string
  default     = "us-west-2"

  validation {
    condition     = var.ml_region == "us-west-2"
    error_message = "SageMaker y Bedrock deben ir en us-west-2 (región de nsf-ncar-era5)."
  }
}

variable "enable_cohere" {
  description = "Si es true, el rol de SageMaker también puede invocar Cohere Embed v4 (cohere.embed-v4:0) en Bedrock. Titan Multimodal Embeddings G1 siempre queda habilitado."
  type        = bool
  default     = false
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
  default     = "adapter-bucket"
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
