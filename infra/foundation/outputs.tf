output "network_id" {
  description = "Fully qualified VPC ID."
  value       = google_compute_network.vpc.id
}

output "subnet_id" {
  description = "Fully qualified subnet ID."
  value       = google_compute_subnetwork.subnet.id
}

output "subnet_cidr" {
  description = "Primary subnet IPv4 range."
  value       = google_compute_subnetwork.subnet.ip_cidr_range
}
