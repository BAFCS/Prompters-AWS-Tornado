#!/bin/bash
# Primer arranque de la máquina: Docker, el repo, los datos que se bajan a mano y el visor.
# Si algo falla, el registro está en /var/log/cloud-init-output.log.
set -euxo pipefail
dnf install -y docker git
systemctl enable --now docker

git clone --branch ${branch} ${repo_url} /opt/mesocyclonic
mkdir -p /opt/mesocyclonic/data && cd /opt/mesocyclonic/data
curl -fL --retry 5 -o tornados_chile.xlsx https://ndownloader.figshare.com/files/56272544
curl -fL --retry 5 -o coast.zip https://naciscdn.org/naturalearth/10m/physical/ne_10m_coastline.zip

/opt/mesocyclonic/deploy/up.sh
