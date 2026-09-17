# Modal infrastructure for the MAX-vs-SGLang benchmark.
#
# NOTE on providers: there is no official Modal Terraform provider, and the
# community `deevus/modal` provider is uninstallable (its release artifacts
# 404 on GitHub — verified 2026-09-17). So Modal resources are managed here
# via `terraform_data` + the modal CLI — volumes, secrets, and `modal deploy`.
# This keeps `terraform apply/destroy` as the single infra entrypoint.

terraform {
  required_version = ">= 1.7"
}

locals {
  repo_root = abspath("${path.module}/../..")
  modal_bin = "${local.repo_root}/.venv/bin/modal"

  # Any src/ change re-triggers both deploys.
  src_hash = sha256(join("", [
    for f in fileset("${local.repo_root}/src", "**") :
    filesha256("${local.repo_root}/src/${f}")
  ]))
}

# ---------------------------------------------------------------------------
# Volumes — names must match `volumes:` in src/config.yaml (apps also
# auto-create them via create_if_missing; declaring here keeps infra explicit).
# ---------------------------------------------------------------------------
resource "terraform_data" "volumes" {
  for_each = toset(["bench-hf-cache", "bench-max-cache", "bench-results"])

  provisioner "local-exec" {
    command = "${local.modal_bin} volume create ${each.value} || true"
  }
  # Intentionally no destroy provisioner: volumes hold weight caches and
  # benchmark results — delete manually (`modal volume rm <name>`) if wanted.
}

# ---------------------------------------------------------------------------
# HF token secret — only for gated models (e.g. Llama). Skipped when empty.
# ---------------------------------------------------------------------------
resource "terraform_data" "hf_secret" {
  count = var.hf_token == "" ? 0 : 1

  triggers_replace = { token_sha = sha256(var.hf_token) }

  provisioner "local-exec" {
    command     = "${local.modal_bin} secret create hf-token HF_TOKEN=$HF_TOKEN --force"
    environment = { HF_TOKEN = var.hf_token } # env var keeps the token off argv
  }
}

# ---------------------------------------------------------------------------
# App deploys — Modal apps are SDK-defined; deploy via the CLI.
# ---------------------------------------------------------------------------
resource "terraform_data" "deploy_sglang" {
  count      = var.deploy_sglang ? 1 : 0
  depends_on = [terraform_data.volumes, terraform_data.hf_secret]

  triggers_replace = {
    code      = local.src_hash
    repo_root = local.repo_root
  }

  provisioner "local-exec" {
    working_dir = self.triggers_replace.repo_root
    command     = ".venv/bin/modal deploy src/apps/sglang_server.py"
    environment = { PYTHONPATH = "src" }
  }

  provisioner "local-exec" {
    when        = destroy
    working_dir = self.triggers_replace.repo_root
    command     = ".venv/bin/modal app stop bench-sglang || true"
  }
}

resource "terraform_data" "deploy_max" {
  count      = var.deploy_max ? 1 : 0
  depends_on = [terraform_data.volumes, terraform_data.hf_secret]

  triggers_replace = {
    code      = local.src_hash
    repo_root = local.repo_root
  }

  provisioner "local-exec" {
    working_dir = self.triggers_replace.repo_root
    command     = ".venv/bin/modal deploy src/apps/max_server.py"
    environment = { PYTHONPATH = "src" }
  }

  provisioner "local-exec" {
    when        = destroy
    working_dir = self.triggers_replace.repo_root
    command     = ".venv/bin/modal app stop bench-max || true"
  }
}
