variable "project_id" {
  description = "Target GCP project, selected by the environment tfvars file."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid GCP project ID."
  }
}

variable "region" {
  description = "GCP region for the subnet."
  type        = string
  default     = "europe-west1"
}

variable "network_name" {
  description = "Name of the custom-mode VPC."
  type        = string
}

variable "subnet_name" {
  description = "Name of the regional subnet."
  type        = string
}

variable "subnet_cidr" {
  description = "Canonical IPv4 CIDR, checked against existing networks before deployment."
  type        = string

  validation {
    condition     = can(cidrnetmask(var.subnet_cidr)) && try(cidrsubnet(var.subnet_cidr, 0, 0) == var.subnet_cidr, false)
    error_message = "Use a canonical IPv4 CIDR, for example 10.0.1.0/24."
  }
}
