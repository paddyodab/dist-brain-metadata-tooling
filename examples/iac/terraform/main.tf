# Storage for the widget service. In real Terraform, prefer a provider
# `default_tags` block so the required set is applied once — the gate should then
# read `terraform show -json` of a plan to see resolved tags. This static sample
# keeps tags on the resource for a dependency-free demonstration.

resource "aws_s3_bucket" "widgets" {
  # @intent durable object storage for widget uploads; versioned, private.
  bucket = "widget-service-widgets"

  tags = {
    Owner       = "platform-team"
    Environment = "prod"
    CostCenter  = "cc-1234"
    Service     = "widget"
  }
}

resource "aws_sqs_queue" "widget_jobs" {
  # @intent buffers widget-processing jobs between the API and workers.
  name = "widget-service-widget-jobs"

  tags = {
    Owner       = "platform-team"
    Environment = "prod"
    CostCenter  = "cc-1234"
    Service     = "widget"
  }
}
