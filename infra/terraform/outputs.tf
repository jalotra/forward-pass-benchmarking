output "volumes" {
  description = "Modal volumes managed by this config"
  value       = keys(terraform_data.volumes)
}

output "endpoint_hint" {
  description = "Endpoint URLs are issued by `modal deploy` — grab them with `make urls` or `modal app list`"
  value       = "make urls"
}
