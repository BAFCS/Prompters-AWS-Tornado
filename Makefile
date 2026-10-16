# Atajos del proyecto. Cada objetivo es un comando de AGENTS.md; `make` solo lista los objetivos.

# Una descarga cortada no debe quedar como hecha.
.DELETE_ON_ERROR:

.PHONY: help check fix viewer data data/goes

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
	aws s3 sync --no-sign-request s3://noaa-goes16/ABI-L2-CMIPF/2019/150/21/ $@/ \
	  --exclude '*' --include '*M6C13*s201915021[345]*'

.PHONY: sync
sync: ## fusiona origin/main y las ramas de origen en merge/datos-modelo (sin push)
	uv run python scripts/app/sync_branches.py

.PHONY: publish
SITE_BUCKET ?= mesocyclonic-dev-data-20261015215812490800000001
SITE_DIST ?= E1QZXODGHESLF4
SITE_PROFILE ?= gpu
SITE_DIR ?= demo_site
SITE_PREFIX ?= resultados/sitio
publish: ## sube el sitio a S3 (SITE_PREFIX, por defecto resultados/sitio/) e invalida CloudFront
	aws s3 cp $(SITE_DIR)/index.html s3://$(SITE_BUCKET)/$(SITE_PREFIX)/index.html --profile $(SITE_PROFILE) --content-type "text/html; charset=utf-8" --cache-control no-cache
	aws s3 cp $(SITE_DIR)/metricas.json s3://$(SITE_BUCKET)/$(SITE_PREFIX)/metricas.json --profile $(SITE_PROFILE) --content-type "application/json; charset=utf-8" --cache-control no-cache
	aws s3 sync $(SITE_DIR)/days s3://$(SITE_BUCKET)/$(SITE_PREFIX)/days --profile $(SITE_PROFILE) --content-type application/json --cache-control max-age=300 --delete
	aws cloudfront create-invalidation --distribution-id $(SITE_DIST) --paths "/$(SITE_PREFIX)/*" --profile $(SITE_PROFILE)

.PHONY: publish-goes
publish-goes: ## sube el sitio «solo GOES» (ERA5 típico) a resultados/sitio_goes/
	$(MAKE) publish SITE_DIR=demo_site_goes SITE_PREFIX=resultados/sitio_goes
