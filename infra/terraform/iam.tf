# Rol de IAM de la EC2: le da permiso de solo lectura sobre el bucket de datos y acceso a
# Session Manager (para entrar sin SSH ni llaves). No se abre el puerto 22.

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name_prefix        = "${var.project_name}-${var.environment}-ec2-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# Solo lectura del bucket de datos.
data "aws_iam_policy_document" "s3_read" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
}

resource "aws_iam_role_policy" "s3_read" {
  name_prefix = "s3-read-"
  role        = aws_iam_role.ec2.id
  policy      = data.aws_iam_policy_document.s3_read.json
}

# Permiso para que la página «Predecir» del visor genere embeddings con Bedrock (Titan).
data "aws_iam_policy_document" "bedrock_invoke" {
  statement {
    actions   = ["bedrock:InvokeModel"]
    resources = ["arn:aws:bedrock:*::foundation-model/amazon.titan-embed-image-v1"]
  }
}

resource "aws_iam_role_policy" "bedrock_invoke" {
  name_prefix = "bedrock-invoke-"
  role        = aws_iam_role.ec2.id
  policy      = data.aws_iam_policy_document.bedrock_invoke.json
}

# Session Manager: consola en la instancia sin abrir SSH.
# Alertas por correo de la página «Predecir» (scripts/viewer/viewer_app/alerts.py): la EC2 del visor
# envía con SES solo desde el remitente configurado. Cada dirección es una identidad de SES; en modo
# sandbox AWS les manda un correo de verificación y solo reciben las que hagan clic en el enlace.
resource "aws_sesv2_email_identity" "alerts" {
  for_each       = toset(concat([var.alert_sender], var.alert_recipients))
  email_identity = each.value
}

data "aws_iam_policy_document" "ses_alerts" {
  statement {
    sid       = "EnviarAlertasDePredecir"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = [for k, v in aws_sesv2_email_identity.alerts : v.arn]
    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [var.alert_sender]
    }
  }
}

resource "aws_iam_role_policy" "ses_alerts" {
  name   = "ses-alertas-predecir"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.ses_alerts.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2" {
  name_prefix = "${var.project_name}-${var.environment}-ec2-"
  role        = aws_iam_role.ec2.name
}
