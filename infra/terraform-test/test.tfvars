# Configuración del CLON DE PRUEBAS (environment=test), aislado del dev vivo.
# Se usa con:  terraform apply -var-file=test.tfvars
#
# Objetivo: levantar una copia de la arquitectura para experimentar optimizaciones del
# flujo de datos ERA5 sin tocar el entorno dev. Si el clon resulta mejor, el equipo migra.

# --- Aislamiento: todo se nombra mesocyclonic-test-* en vez de -dev-* ---
environment  = "test"
project_name = "mesocyclonic"

# --- Permisos de la cuenta de hackathon (rol WSParticipantRole) ---
# La cuenta DENIEGA crear recursos fuera de us-east-1 (verificado en la política IAM
# ws-default-policy, sentencia DenyAllOutsideAllowedRegions). ERA5 vive en us-west-2, pero
# NO podemos poner cómputo ahí: la EC2 de entrenamiento va en us-east-1 y lee ERA5 entre
# regiones (nsf-ncar-era5 es un bucket público de acceso anónimo).
region          = "us-east-1"
training_region = "us-east-1"

# --- Repositorio que clonan las EC2 para construir el visor y entrenar ---
repo_url    = "https://github.com/BAFCS/Prompters-AWS-Tornado.git"
repo_branch = "main"

# --- Tamaños de instancia (dentro de lo permitido: la política deniega >=6xlarge y GPU) ---
# El visor cabe en t3.large; para el clon de pruebas basta t3.medium y ahorra ~la mitad.
instance_type   = "t3.medium"
root_volume_gib = 30

# --- Entrenamiento: lo dejamos APAGADO en el primer apply del clon ---
# Primero validamos que el clon (visor + S3 + CloudFront) levanta bien y aislado.
# El experimento de optimización (Batch/Step Functions) se monta aparte, no con esta EC2.
enable_training = false

# Si en algún momento se quiere la EC2 de entrenamiento clásica en el clon:
#   enable_training        = true
#   training_instance_type = "c7i.2xlarge"   # 8 vCPU, dentro del límite (<6xlarge)
#   max_event_days         = 6               # prueba rápida
#   unlabeled_days         = 4
#   stop_after_training    = true            # se apaga sola al terminar
