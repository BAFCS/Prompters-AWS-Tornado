# Atajos del proyecto. Cada objetivo es un comando de AGENTS.md; `make` solo lista los objetivos.

TF := terraform -chdir=deploy

.PHONY: help check fix viewer data deploy ssh

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

check: ## lint, formato, tipos y pruebas (lo que pide la plantilla de PR)
	uv run ruff check scripts tests
	uv run ruff format --check scripts tests
	uv run pyright
	uv run python -m unittest discover -s tests -v

fix: ## corrige lo que ruff sabe corregir y formatea
	uv run ruff check --fix scripts tests
	uv run ruff format scripts tests

viewer: ## visor en local, recarga al guardar
	uv run streamlit run scripts/viewer/viewer.py --server.runOnSave true

data: data/tornados_chile.xlsx data/coast.zip data/goes ## catálogo, costa y GOES de figs_goes.py (salta lo que ya existe)

data/tornados_chile.xlsx:
	curl -fL --create-dirs -o $@ https://ndownloader.figshare.com/files/56272544

data/coast.zip:
	curl -fL --create-dirs -o $@ https://naciscdn.org/naturalearth/10m/physical/ne_10m_coastline.zip

data/goes:
	aws s3 cp --no-sign-request --recursive s3://noaa-goes16/ABI-L2-CMIPF/2019/150/21/ $@/ \
	  --exclude '*' --include '*M6C13*s201915021[345]*'

deploy: ## crea o actualiza la máquina en AWS, abierta solo a la IP actual
	$(TF) init -input=false
	$(TF) apply -var allowed_cidr=$$(curl -4 -s ifconfig.me)/32

ssh: ## sesión en la máquina por SSM (necesita el plugin Session Manager)
	aws ssm start-session --region us-west-2 --target $$($(TF) output -raw instance_id)
