#!/bin/bash
# Trae el código de la rama clonada, reconstruye la imagen y reinicia el visor. Lo llama user_data en
# el primer arranque; para actualizar: sudo /opt/mesocyclonic/deploy/up.sh
set -euxo pipefail
cd /opt/mesocyclonic
git pull --ff-only
docker build -t mesocyclonic-viewer .
docker rm -f viewer || true
docker run -d --name viewer --restart unless-stopped -p 8501:8501 \
  -v /opt/mesocyclonic/data:/app/data mesocyclonic-viewer
