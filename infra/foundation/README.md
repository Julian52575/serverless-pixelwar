# C02 Hands-on 1: development network

Run from this directory in PowerShell. This root manages only a custom VPC and
one subnet in `masterpoulet-dev`. No VM, firewall rule, NAT, project, IAM binding,
API activation or state bucket is managed by this root. Production is rejected
by variable validation; do not add production credentials or backend settings.

`dev.tfvars` is public configuration, not a secret. Google Application Default
Credentials (ADC) authenticate Terraform; never put a service account key in Git.
The provider version constraint and committed `.terraform.lock.hcl` make provider
selection reproducible. The subnet uses Private Google Access for future VMs
without public IPs; this does not provide general Internet access or Cloud NAT.

## Team workflow

Use a feature branch from current `origin/main`, then a reviewed PR following
`CONTRIBUTOR.md`. All three developers must use the same bucket, `foundation/dev`
prefix and `default` workspace. GCS locking serializes state operations; discuss
changes before applying because locking does not reconcile competing branches.
Never use `-lock=false`, force-unlock, import or state migration without review.
Keep the bucket separate from the network lifecycle so destroying the lab does
not delete its state history. Coordinate ownership before adopting existing
resources: a second state must never manage the same VPC/subnet.

## Bootstrap: approval required, commands NOT run automatically

Latest backend check (2026-10-22): the user authorized creation of the state
bucket after an empty dev bucket inventory. Creation was attempted and rejected
with HTTP 403: the project has no linked billing account (`billingEnabled:
false`). No bucket was created. Linking a billing account and enabling Compute
Engine API require separate authorization; neither action has been performed.
Remote init reproduces the missing-bucket 404, format and validation pass, and
plan remains blocked by backend initialization. See `AUDIT.md` for this check.

The audit on 2026-10-22 found no bucket in dev, and Compute Engine API disabled.
The bucket name in `backends/dev.hcl` is proposed, not proven globally available.
If unavailable, choose another globally unique name and update the backend file.

After explicit approval, an authorized operator can run:

```powershell
gcloud services enable compute.googleapis.com --project=masterpoulet-dev --quiet
gcloud storage buckets create gs://masterpoulet-dev-tfstate-539044310096 --project=masterpoulet-dev --location=europe-west1 --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://masterpoulet-dev-tfstate-539044310096 --project=masterpoulet-dev --versioning
```

Verify the bucket belongs to dev, versioning is enabled and public access is
prevented. Check effective bucket permissions for every team member: Terraform
needs object get/list/create/delete (including lock objects), typically
`roles/storage.objectAdmin` scoped to this bucket. Bucket creation alone does not
prove these permissions. Updating versioning needs `storage.buckets.update`.
Use a separate reviewed IAM change if permissions are missing; no grant is
automated here. Compute operations also require get/create/delete/use rights for
networks/subnets. The initial audit tested only a subset of these permissions.

After API activation, repeat the inventory before planning:

```powershell
gcloud compute networks list --project=masterpoulet-dev --quiet
gcloud compute networks subnets list --project=masterpoulet-dev --quiet
gcloud storage buckets describe gs://masterpoulet-dev-tfstate-539044310096 --project=masterpoulet-dev
```

Check existing names, primary/secondary ranges and any planned peering/VPN ranges
against `10.0.1.0/24`. Stop if resources already exist; agree on their owner and
review a possible import instead of creating duplicates. Do not modify the
default network. If ADC is missing, run `gcloud auth application-default login`
yourself; interactive authentication is not automated.

## Checks and plan

```powershell
terraform fmt -recursive
./check.ps1 -LocalOnly
# Once bootstrap, permissions and the network inventory have been verified:
./check.ps1
```

The script stops on native command failures. LocalOnly installs providers and
validates configuration without initializing GCS or planning cloud changes.
The complete path performs:

```powershell
terraform fmt -check -recursive
terraform init '-backend-config=backends/dev.hcl' -input=false
terraform validate
terraform plan '-var-file=dev.tfvars' -input=false -lock-timeout=60s '-out=dev.tfplan'
terraform show dev.tfplan
```

Review the real plan before approval. Expected for an empty state and absent
resources: **2 additions, 0 changes, 0 deletions**, VPC `masterpoulet-dev-vpc` and
subnet `masterpoulet-dev-vpc-subnet`, `europe-west1`, `10.0.1.0/24`. This expectation
is not an executed plan. Google may create system routes as part of VPC creation;
no separate Terraform route or firewall resources are declared.

## Apply, verification and recreation: explicit approval required

Only after approval of a fresh plan, run `terraform apply dev.tfplan`.
Then verify:

```powershell
terraform output
terraform state list
gcloud compute networks describe masterpoulet-dev-vpc --project=masterpoulet-dev
gcloud compute networks subnets describe masterpoulet-dev-vpc-subnet --region=europe-west1 --project=masterpoulet-dev
terraform plan '-var-file=dev.tfvars' -input=false -lock-timeout=60s
```

For teardown, first review a destruction plan and obtain explicit approval:

```powershell
terraform plan -destroy '-var-file=dev.tfvars' -input=false -lock-timeout=60s '-out=dev-destroy.tfplan'
# Only after approval of that destruction plan:
terraform apply dev-destroy.tfplan
# To recreate, prepare a fresh plan and obtain approval again:
./check.ps1
# Only after approval:
terraform apply dev.tfplan
```

Do not delete the state bucket during the lab teardown. New dependencies added
by teammates can block deletion and require coordination, not forced deletion.

References: [GCS backend and locking](https://developer.hashicorp.com/terraform/language/backend/gcs),
[Google Terraform security practices](https://docs.cloud.google.com/docs/terraform/best-practices/security).
