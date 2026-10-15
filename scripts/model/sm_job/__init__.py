"""Paquete del trabajo de SageMaker: punto de entrada del entrenamiento y servicio de inferencia.

Se llama ``sm_job`` y no ``sagemaker`` a propósito: cuando ``scripts/model`` está en ``sys.path``
(al correr un script de esa carpeta, en las pruebas y como ``source_dir`` del contenedor), un
paquete local llamado ``sagemaker`` taparía al SDK real de SageMaker en los ``import``.
"""
