# Adapted from the teaching GKE/network modules; exclusive new TFI state.
terraform {
  required_version = ">= 1.6.0, < 2.0.0"
  required_providers {
    google = { source = "hashicorp/google", version = "5.45.2" }
  }
}
variable "project_id" {
  type = string
  validation {
    condition     = var.project_id == "unlu-tfi-hisjb-20261104"
    error_message = "Only the independent TFI project is allowed."
  }
}
variable "operator_ipv4_cidr" {
  type = string
  validation {
    condition     = can(cidrhost(var.operator_ipv4_cidr, 0)) && endswith(var.operator_ipv4_cidr, "/32")
    error_message = "One verified operator IPv4 /32 is required; never 0.0.0.0/0."
  }
}
provider "google" {
  project = var.project_id
  region  = "us-central1"
  zone    = "us-central1-a"
}
resource "google_compute_network" "tfi" {
  name                    = "hisjb-tfi-vpc"
  auto_create_subnetworks = false
}
resource "google_compute_subnetwork" "tfi" {
  name          = "hisjb-tfi-subnet"
  network       = google_compute_network.tfi.id
  ip_cidr_range = "10.72.0.0/24"
  region        = "us-central1"
  secondary_ip_range {
    range_name    = "hisjb-pods"
    ip_cidr_range = "10.73.0.0/20"
  }
  secondary_ip_range {
    range_name    = "hisjb-services"
    ip_cidr_range = "10.74.0.0/24"
  }
}
resource "google_service_account" "nodes" {
  account_id   = "hisjb-gke-node"
  display_name = "HISJB GKE node; no application cloud credentials"
}
resource "google_project_iam_member" "node_system" {
  project = var.project_id
  role    = "roles/container.defaultNodeServiceAccount"
  member  = "serviceAccount:${google_service_account.nodes.email}"
}
resource "google_artifact_registry_repository_iam_member" "node_reader" {
  project    = var.project_id
  location   = "us-central1"
  repository = "hisjb-tfi"
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.nodes.email}"
}
resource "google_container_cluster" "tfi" {
  name                = "hisjb-tfi-temp"
  location            = "us-central1-a"
  network             = google_compute_network.tfi.id
  subnetwork          = google_compute_subnetwork.tfi.id
  initial_node_count  = 1
  deletion_protection = false
  resource_labels     = { project = "hisjb-tfi", ephemeral = "true" }
  release_channel { channel = "REGULAR" }
  ip_allocation_policy {
    cluster_secondary_range_name  = "hisjb-pods"
    services_secondary_range_name = "hisjb-services"
  }
  master_authorized_networks_config {
    cidr_blocks {
      cidr_block   = var.operator_ipv4_cidr
      display_name = "current-authorized-operator"
    }
  }
  workload_identity_config { workload_pool = "${var.project_id}.svc.id.goog" }
  network_policy {
    enabled  = true
    provider = "CALICO"
  }
  addons_config {
    http_load_balancing { disabled = true }
    network_policy_config { disabled = false }
    gce_persistent_disk_csi_driver_config { enabled = true }
  }
  logging_service    = "none"
  monitoring_service = "none"
  monitoring_config {
    enable_components = []
    managed_prometheus { enabled = false }
  }
  node_config {
    machine_type    = "e2-standard-4"
    disk_type       = "pd-standard"
    disk_size_gb    = 30
    image_type      = "COS_CONTAINERD"
    service_account = google_service_account.nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    metadata        = { disable-legacy-endpoints = "true" }
    workload_metadata_config { mode = "GKE_METADATA" }
    shielded_instance_config { enable_secure_boot = true }
    labels = { project = "hisjb-tfi" }
  }
  depends_on = [google_project_iam_member.node_system, google_artifact_registry_repository_iam_member.node_reader]
}
output "cluster_name" { value = google_container_cluster.tfi.name }
output "project_id" { value = var.project_id }
output "zone" { value = "us-central1-a" }
