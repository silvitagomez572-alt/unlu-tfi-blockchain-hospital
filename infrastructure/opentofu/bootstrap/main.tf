# PREPARED ONLY: apply requires an explicit monetary authorization.
terraform {
  required_version = ">= 1.6.0, < 2.0.0"
  required_providers {
    google = { source = "hashicorp/google", version = "5.45.2" }
  }
}
provider "google" { project = var.project_id }
variable "project_id" {
  type = string
  validation {
    condition     = var.project_id == "unlu-tfi-hisjb-20261104"
    error_message = "Only the proposed independent TFI project is allowed."
  }
}
variable "billing_account" {
  type = string
  validation {
    condition     = var.billing_account == "01091D-82ABD9-7BDBC4"
    error_message = "Unexpected billing account."
  }
}
variable "github_repository_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "Verified immutable GitHub repository ID required."
  }
}
resource "google_project" "tfi" {
  project_id          = var.project_id
  name                = "UNLu HISJB Evidence Chain TFI"
  billing_account     = var.billing_account
  auto_create_network = false
  labels              = { project = "hisjb-tfi", managed_by = "opentofu" }
  lifecycle { prevent_destroy = true }
}
resource "google_project_service" "apis" {
  for_each = toset(["compute.googleapis.com", "container.googleapis.com", "artifactregistry.googleapis.com",
    "iam.googleapis.com", "iamcredentials.googleapis.com", "sts.googleapis.com",
  "cloudresourcemanager.googleapis.com", "serviceusage.googleapis.com"])
  project            = google_project.tfi.project_id
  service            = each.value
  disable_on_destroy = false
}
resource "google_artifact_registry_repository" "images" {
  project       = google_project.tfi.project_id
  location      = "us-central1"
  repository_id = "hisjb-tfi"
  format        = "DOCKER"
  description   = "One synthetic academic HISJB image; temporary TFI"
  depends_on    = [google_project_service.apis]
}
resource "google_service_account" "publisher" {
  project      = google_project.tfi.project_id
  account_id   = "hisjb-image-writer"
  display_name = "HISJB OIDC image publication only"
  depends_on   = [google_project_service.apis]
}
resource "google_artifact_registry_repository_iam_member" "writer" {
  project    = google_project.tfi.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.publisher.email}"
}
resource "google_iam_workload_identity_pool" "github" {
  project                   = google_project.tfi.project_id
  workload_identity_pool_id = "hisjb-github"
  depends_on                = [google_project_service.apis]
}
resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = google_project.tfi.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "hisjb-provider"
  attribute_mapping = {
    "google.subject"          = "assertion.sub"
    "attribute.repository"    = "assertion.repository"
    "attribute.repository_id" = "assertion.repository_id"
    "attribute.ref"           = "assertion.ref"
  }
  attribute_condition = "assertion.repository == 'silvitagomez572-alt/unlu-tfi-blockchain-hospital' && assertion.repository_id == '${var.github_repository_id}' && assertion.ref == 'refs/heads/tfi/despliegue-temporal' && assertion.event_name == 'workflow_dispatch'"
  oidc { issuer_uri = "https://token.actions.githubusercontent.com" }
}
resource "google_service_account_iam_member" "federation" {
  service_account_id = google_service_account.publisher.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}
output "project_id" { value = google_project.tfi.project_id }
output "publisher" { value = google_service_account.publisher.email }
output "provider" { value = google_iam_workload_identity_pool_provider.github.name }
output "image_repository" { value = "us-central1-docker.pkg.dev/${var.project_id}/hisjb-tfi/hisjb" }
