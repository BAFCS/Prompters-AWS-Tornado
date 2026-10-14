"""Punto de entrada de la App CDK: publica el visor Streamlit en AWS.

Uso (desde infra/): ``npx aws-cdk@2.1145.0 deploy``. La cuenta y la región salen de las
credenciales exportadas en la terminal (``AWS_DEFAULT_REGION``, por defecto us-east-1).
"""

import os

import aws_cdk as cdk
from stack import ViewerStack

app = cdk.App()
ViewerStack(
    app,
    "MesocyclonicViewer",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
    description="Visor de tornados y tormentas mesociclónicas de Chile (aws-mesocyclonic)",
)
cdk.Tags.of(app).add("project", "aws-mesocyclonic")
app.synth()
