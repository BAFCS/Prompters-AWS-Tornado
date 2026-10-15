"""Pruebas de contrato con Daniel (modelo) y Nico (Lago_Datos), sin red ni AWS (Req. 9.9-9.15).

El código de Daniel se lee como texto y se analiza con ``ast`` (``contracts.py``) para no importar
``xgboost`` ni ``sagemaker``. ``build_table.py --help`` se ejecuta en un subproceso con tiempo
límite. Si el código de Daniel aún no está en el árbol (antes de la primera Sincronización), las
pruebas fallan con un mensaje explícito: no se saltan.
"""

import ast
import os
import re
import socket
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "app"))

import contracts  # noqa: E402
import lake_layout  # noqa: E402
from app_synthetic import NetworkBlockedError, NoNetworkMixin  # noqa: E402

MODEL_DIR = ROOT / "scripts" / "model"
INFERENCE_PY = MODEL_DIR / "sm_job" / "inference.py"
TABLE_PY = MODEL_DIR / "table.py"
BUILD_TABLE_PY = MODEL_DIR / "build_table.py"

INFERENCE_SYMBOLS = ("model_fn", "predict_fn", "output_fn", "OUTPUT_COLUMNS", "MissingColumnsError")
EXPECTED_OUTPUT_COLUMNS = ("probability", "date", "hour_utc", "latitude", "longitude", "config")
REQUIRED_ERA5_FEATURES = ("cape", "shear_06")
STAGE_INFER_MISSING = "la opción --stage infer no está disponible"
HELP_TIMEOUT_S = 60

# Transcripción de docs/DATOS_AWS.md (rama intentos-nico). Cuando el valor no sale del documento
# se indica el script de scripts/ingest/ o del pipeline de Daniel del que proviene.
EXPECTED_LAYOUT: dict[str, object] = {
    # §2: prefijos y patrones de nombre en el bucket.
    "ERA5_STORE_PREFIX": "era5_store",
    "ERA5_CDS_PREFIX": "era5_cds_year",
    "GOES_STORE_PREFIX": "goes_store",
    "ERA5_STORE_PATTERN": "era5_store/era5_{ymd}.zarr",
    "ERA5_CDS_PATTERN": "era5_cds_year/{yyyy}/{mm}/era5_{kind}_{ymd}.nc",
    "CDS_KINDS": ("pl", "sfc"),
    "GOES_STORE_PATTERN": "goes_store/{iso}/goes_{ymd}.nc",
    # Fuente: ingest_goes.dest_path (commit ec238df), un archivo por banda y día. Aún no figura en
    # DATOS_AWS.md; actualizar esta línea cuando Nico lo documente.
    "GOES_BAND_STORE_PATTERN": "goes_store/{iso}/goes_{ymd}_{band}.nc",
    # §3: variables y niveles de ERA5.
    "LEVELS": (1000, 925, 850, 700, 500, 300),
    "PL_VARS": ("u", "v", "t", "z"),
    "SFC_VARS": ("10u", "10v", "2t", "2d", "sp", "cape"),
    # §4: coords time/level del Zarr ncar (más latitude/longitude de la grilla).
    "DIMS": ("time", "level", "latitude", "longitude"),
    # §5: renombres CDS → ncar.
    "CDS_RENAME": {
        "valid_time": "time",
        "pressure_level": "level",
        "u10": "10u",
        "v10": "10v",
        "t2m": "2t",
        "d2m": "2d",
    },
    # §6 (expver de ERA5T) e ingest_cds: coordenadas auxiliares del NetCDF de CDS.
    "CDS_DROP": ("number", "expver"),
    # §3-§4: GOES, variable C13, dims time/y/x y grilla 882 × 466 (y, x).
    "GOES_VAR": "C13",
    "GOES_DIMS": ("time", "y", "x"),
    "GOES_SHAPE": (466, 882),
    # Fuente: ingest_goes.encoding (_FillValue del int16 crudo).
    "GOES_FILL": -1,
    # Fuente: build_table.py y process_goes.py de Daniel (rutas bajo data/crops/<región>/).
    "ERA5_IDX_PATTERN": "era5_indices/era5_idx_{ymd}.nc",
    "GOES_LATLON_PATTERN": "goes_latlon/{ymd}/goes_{ymd}{hh}.nc",
    "GOES_RES": 0.02,
}


def _read_daniel(path: Path) -> str:
    """Texto de un archivo de Daniel o AssertionError explícito si aún no está en el árbol."""
    if not path.is_file():
        raise AssertionError(
            f"falta {path.relative_to(ROOT)}: el código de Daniel aún no está en el árbol; "
            "corre la Sincronización (make sync) antes de las pruebas de contrato"
        )
    return path.read_text("utf-8")


def _help_stages(help_text: str) -> tuple[str, ...] | None:
    """Valores de ``--stage {a,b,c}`` en la salida de ``--help``, o None si no aparece."""
    match = re.search(r"--stage\s+\{([^}]*)\}", help_text)
    if match is None:
        return None
    return tuple(s.strip() for s in match.group(1).split(","))


def _ast_stages(source: str) -> tuple[object, ...] | None:
    """Valores de ``--stage`` según el código: ``choices`` literal o la constante ``STAGES``."""
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "add_argument" or not any(
            isinstance(a, ast.Constant) and a.value == "--stage" for a in node.args
        ):
            continue
        for kw in node.keywords:
            if kw.arg != "choices":
                continue
            if isinstance(kw.value, ast.Name):
                return contracts.tuple_constant(source, kw.value.id)
            try:
                value = ast.literal_eval(kw.value)
            except ValueError:
                return None
            return tuple(value) if isinstance(value, tuple | list) else None
    return None


class DanielContractTest(NoNetworkMixin):
    """Interfaz de ``scripts/model`` que consumen el Adaptador y el Ejecutor_Inferencia."""

    def test_inference_symbols(self) -> None:
        """``inference.py`` define los cinco nombres que usamos (Req. 9.11)."""
        source = _read_daniel(INFERENCE_PY)
        missing = contracts.missing_symbols(source, INFERENCE_SYMBOLS)
        self.assertEqual(missing, [], f"{INFERENCE_PY.name} no define: {', '.join(missing)}")

    def test_output_columns_exact(self) -> None:
        """``OUTPUT_COLUMNS`` coincide en contenido y orden (Req. 9.12)."""
        source = _read_daniel(INFERENCE_PY)
        found = contracts.tuple_constant(source, "OUTPUT_COLUMNS")
        drifts = contracts.sequence_drift("OUTPUT_COLUMNS", EXPECTED_OUTPUT_COLUMNS, found)
        self.assertEqual(drifts, [], contracts.format_drift(drifts))

    def test_era5_features_include_cape_and_shear06(self) -> None:
        """``table.ERA5_FEATURES`` contiene ``cape`` y ``shear_06`` (Req. 9.13)."""
        source = _read_daniel(TABLE_PY)
        found = contracts.tuple_constant(source, "ERA5_FEATURES")
        self.assertIsNotNone(found, "table.py no define ERA5_FEATURES como tupla literal")
        missing = contracts.missing_members(REQUIRED_ERA5_FEATURES, [str(f) for f in found or ()])
        self.assertEqual(missing, [], f"table.ERA5_FEATURES no contiene: {', '.join(missing)}")

    def test_build_table_accepts_stage_infer(self) -> None:
        """``build_table.py --help`` lista ``infer`` en ``--stage``; si no corre, se mira el código
        con ``ast`` (Req. 9.14)."""
        source = _read_daniel(BUILD_TABLE_PY)
        try:
            proc = subprocess.run(
                [sys.executable, str(BUILD_TABLE_PY), "--help"],
                capture_output=True,
                text=True,
                timeout=HELP_TIMEOUT_S,
                cwd=ROOT,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            reason = f"--help no terminó: {exc}"
            stages = None
        else:
            reason = f"--help terminó con código {proc.returncode}"
            stages = _help_stages(proc.stdout) if proc.returncode == 0 else None
        if stages is None:
            # Caída a ast: el subproceso falló o la salida no muestra las opciones de --stage.
            stages = _ast_stages(source)
            reason += "; análisis con ast"
        self.assertIsNotNone(stages, f"{STAGE_INFER_MISSING} ({reason}: sin --stage)")
        self.assertIn("infer", stages or (), f"{STAGE_INFER_MISSING} ({reason}: {stages})")


class NicoContractTest(NoNetworkMixin):
    """``lake_layout.py`` coincide con lo documentado en ``docs/DATOS_AWS.md`` (Req. 9.15)."""

    def test_lake_layout_matches_datos_aws(self) -> None:
        """Cada constante transcrita existe en ``lake_layout`` con el mismo valor."""
        drifts = contracts.layout_drift(EXPECTED_LAYOUT, lake_layout)
        self.assertEqual(drifts, [], "\n" + contracts.format_drift(drifts))


class HelpersTest(NoNetworkMixin):
    """Los ayudantes de esta prueba y el bloqueo de red se comportan como se espera."""

    def test_stage_parsers(self) -> None:
        """``--stage`` se lee de la salida de ``--help`` y del código, con y sin ``infer``."""
        self.assertEqual(
            _help_stages("  --stage {select,build,infer}\n"), ("select", "build", "infer")
        )
        self.assertIsNone(_help_stages("usage: x [-h]"))
        with_const = "S = ('a', 'infer')\np.add_argument('--stage', choices=S)\n"
        self.assertEqual(_ast_stages(with_const), ("a", "infer"))
        literal = "p.add_argument('--stage', choices=['build'])\n"
        self.assertEqual(_ast_stages(literal), ("build",))
        self.assertIsNone(_ast_stages("p.add_argument('--start')\n"))

    def test_daniel_file_missing_fails_explicitly(self) -> None:
        """Un archivo ausente produce AssertionError con la ruta, no un salto."""
        with self.assertRaisesRegex(AssertionError, "aún no está en el árbol"):
            _read_daniel(MODEL_DIR / "no_existe.py")

    def test_network_blocked_and_no_credentials(self) -> None:
        """Una conexión TCP falla y las credenciales AWS están vacías."""
        with (
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
            self.assertRaises(NetworkBlockedError),
        ):
            sock.connect(("127.0.0.1", 9))
        self.assertEqual(os.environ["AWS_ACCESS_KEY_ID"], "")
        self.assertEqual(os.environ["AWS_PROFILE"], "")


if __name__ == "__main__":
    unittest.main()
