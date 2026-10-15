# Setup report (mtp-remaining)

## git status (branch main, up to date with origin/main)
Modified (unstaged, keep):
- infra/terraform/variables.tf (+/-21): ml_region, enable_cohere, training_region description (task 12.1, done)
- pyproject.toml (+3): boto3>=1.43.75, sagemaker>=3.21.0, dev hypothesis>=6.169.4 (task 1.1 partial)
- uv.lock (~2816 lines changed, regenerated)

Untracked: .kiro/specs/multimodal-tornado-predictor/

Diff stat: 3 files changed, 2797 insertions(+), 43 deletions(-)

## Partial changes from 1.1
Only dependency changes. No scripts/model/sagemaker/ package exists yet.

## Toolchain
- uv: not on PATH as `uv`; available via `python -m uv` (uv 0.13.1). Use `python -m uv ...`.
- terraform: ABSENT (not on PATH). Terraform changes cannot be validated locally.
