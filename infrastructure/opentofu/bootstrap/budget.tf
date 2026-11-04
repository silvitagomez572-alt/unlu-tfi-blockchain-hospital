provider "google" {
  alias                 = "budget"
  project               = var.project_id
  billing_project       = var.project_id
  user_project_override = true
}
variable "approved_budget_usd" {
  type = number
  validation {
    condition     = var.approved_budget_usd > 0 && var.approved_budget_usd <= 3
    error_message = "Explicit authorization required, total ceiling USD 3 as of 2026-11-04."
  }
}
resource "google_project_service" "budget_api" {
  project            = google_project.tfi.project_id
  service            = "billingbudgets.googleapis.com"
  disable_on_destroy = false
}
resource "google_billing_budget" "tfi" {
  provider        = google.budget
  billing_account = var.billing_account
  display_name    = "HISJB temporary TFI - alert only, NOT a spending cap"
  budget_filter {
    projects               = ["projects/${google_project.tfi.number}"]
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }
  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(floor(var.approved_budget_usd))
      nanos         = floor((var.approved_budget_usd - floor(var.approved_budget_usd)) * 1000000000)
    }
  }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.9 }
  threshold_rules { threshold_percent = 1.0 }
  depends_on = [google_project_service.budget_api]
}
