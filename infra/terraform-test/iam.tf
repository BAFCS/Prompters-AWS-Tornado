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

# Session Manager: consola en la instancia sin abrir SSH.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2" {
  name_prefix = "${var.project_name}-${var.environment}-ec2-"
  role        = aws_iam_role.ec2.name
}
