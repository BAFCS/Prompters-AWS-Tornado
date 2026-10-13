#!/bin/bash
# Primer arranque de la máquina: Docker, el repo, los datos que se bajan a mano y el visor.
set -euxo pipefail
dnf install -y docker git
systemctl enable --now docker

git clone --depth 1 --branch ${branch} ${repo_url} /opt/mesocyclonic
cd /opt/mesocyclonic
mkdir -p data
curl -fL -o data/tornados_chile.xlsx https://ndownloader.figshare.com/files/56272544
curl -fL -o data/coast.zip https://naciscdn.org/naturalearth/10m/physical/ne_10m_coastline.zip

docker build -t mesocyclonic-viewer .
docker run -d --name viewer --restart unless-stopped -p 8501:8501 \
  -v /opt/mesocyclonic/data:/app/data mesocyclonic-viewer
