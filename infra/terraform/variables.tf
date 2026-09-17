variable "hf_token" {
  description = "Hugging Face token — only needed for gated models (e.g. Llama)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "deploy_sglang" {
  description = "Deploy the SGLang baseline app on apply"
  type        = bool
  default     = true
}

variable "deploy_max" {
  description = "Deploy the OSS MAX app on apply"
  type        = bool
  default     = true
}
