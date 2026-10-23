# Foundation: development and production networks

Run from this directory in PowerShell. This shared root manages only
`google_compute_network.vpc` and `google_compute_subnetwork.subnet`. The Google
provider explicitly selects `var.project_id`. No bucket, IAM, API activation,
firewall, NAT, router or cluster is managed here. Existing default networks stay
outside this state.

| Setting | DEV | PROD |
| --- | --- | --- |
| Variables | `dev.tfvars` | `prd.tfvars` |
| Project | `masterpoulet-dev` | `masterpoulet-prod` |
| Subnet region | `europe-west1` | `europe-west3` |
| `network_name` | `masterpoulet-dev-vpc` | `masterpoulet-prod-vpc` |
| `subnet_name` | `masterpoulet-dev-vpc-subnet` | `masterpoulet-prod-vpc-subnet` |
| `subnet_cidr` | `10.0.1.0/24` | `10.0.2.0/24` |
| Backend config | `backends/dev.hcl` | `backends/prd.hcl` |
| State bucket | `masterpoulet_bucket` | `masterpoulet_prod_bucket` |
| State prefix | `foundation/dev` | `foundation/prd` |
| Workspace | `default` | `default` |

Both existing buckets were verified in their respective projects on 2026-10-23:
`europe-west1`, versioning enabled, uniform access and public access prevention.
Bucket location is independent of subnet region. Before these checks, PROD's
bucket was empty; DEV state existed at `foundation/dev/default.tfstate`.
The existing `subnet_name` variable sets the subnet name explicitly.
Private Google Access is enabled; it does not provide Cloud NAT.

## Checks and environment selection

Authenticate with Google Application Default Credentials (ADC), without secrets
in Git. The tfvars files are public configuration. Keep `.terraform.lock.hcl`
tracked; `.terraform/`, states and `*.tfplan` files are ignored. Saved plans may
contain sensitive data and must remain local.

Always pair a backend with its matching tfvars. Stop after a failed command.
`-reconfigure` selects a backend without migrating state. Use the `default`
workspace; do not migrate, import, force-unlock or disable locking to bypass an
error. The active gcloud project does not select Terraform's project.

```powershell
terraform fmt -recursive
terraform fmt -check -recursive
if ($LASTEXITCODE -ne 0) { throw 'Formatting failed.' }

# DEV: expected to leave the existing network unchanged.
terraform init -reconfigure -backend-config="backends/dev.hcl" -input=false
if ($LASTEXITCODE -ne 0) { throw 'DEV init failed.' }
$foundationWorkspace = terraform workspace show
if ($LASTEXITCODE -ne 0 -or $foundationWorkspace -ne 'default') { throw 'Use the default workspace.' }
terraform validate
if ($LASTEXITCODE -ne 0) { throw 'Validation failed.' }
terraform plan -var-file="dev.tfvars" -input=false -lock-timeout=60s
if ($LASTEXITCODE -ne 0) { throw 'DEV plan failed.' }

# PROD: review exactly two creations, zero changes and zero deletions.
terraform init -reconfigure -backend-config="backends/prd.hcl" -input=false
if ($LASTEXITCODE -ne 0) { throw 'PROD init failed.' }
$foundationWorkspace = terraform workspace show
if ($LASTEXITCODE -ne 0 -or $foundationWorkspace -ne 'default') { throw 'Use the default workspace.' }
terraform validate
if ($LASTEXITCODE -ne 0) { throw 'Validation failed.' }
terraform plan -var-file="prd.tfvars" -input=false -lock-timeout=60s -out="prd.tfplan"
if ($LASTEXITCODE -ne 0) { throw 'PROD plan failed.' }
terraform show prd.tfplan
```

Before planning PROD, confirm the intended VPC/subnet have not been created by
someone else. The GCP `default` network already exists and must not appear in the
plan. Stop on an inaccessible bucket, unexpected state, duplicate target
resources, replacement or deletion. Resolve ownership first.

After personally reviewing the saved PROD plan, apply manually:

```powershell
terraform apply prd.tfplan
```

Reconfigure with `backends/dev.hcl` before the next DEV plan using `dev.tfvars`.
To compare the config with live GCP without
touching Terraform, run `python3 scripts/check.py` (read-only, JSON output; see
`scripts/README.md`). It replaces the former `check.ps1`.

## Verified results: 2026-10-23

Formatting and validation passed. DEV plan returned no changes (exit 0), and
DEV state generation and MD5 were identical before and after. PROD plan returned
2 additions, 0 changes, 0 deletions (detailed exit 2), exclusively the VPC and
subnet in the table. Its saved plan is local `prd.tfplan`, ignored by Git.
The local backend is now configured for PROD, workspace `default`.
No apply, destroy, import or state migration was performed.

Follow `CONTRIBUTOR.md` for branch/review conventions. Share the same backend and
workspace within each environment. GCS locking serializes operations; coordinate
with teammates and never let two states manage one resource. Dated updates in
`AUDIT.md` supersede historical bootstrap findings.
