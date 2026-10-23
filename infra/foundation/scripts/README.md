# check.py: read-only infrastructure inspection

Compares the Terraform config with live GCP for each environment and prints one
JSON document:

| Source | Read from | Never |
| --- | --- | --- |
| Terraform config | `infra/foundation/*.tf` + `<stem>.tfvars` (built-in HCL subset parser) | runs `terraform` |
| Live GCP | read-only `gcloud ... describe/list --format=json` | create, update, enable, IAM |

Terraform state is not read: it lives in GCS and the script never fetches it, so
it cannot prove that Terraform owns a matching live resource (`terraform plan` in
CI does that). Deployment stays in `.github/workflows/terraform-ci.yml` (plan) and
`terraform-deploy.yml` (apply). This script never invokes them.

## Usage

Works from any directory; paths resolve relative to the script.

```bash
python3 infra/foundation/scripts/check.py                  # both envs (default)
python3 infra/foundation/scripts/check.py --env dev        # dev | prod | all
python3 infra/foundation/scripts/check.py --terraform-only # config only, no gcloud
python3 infra/foundation/scripts/check.py --cloud-only     # live listing, no comparison
python3 infra/foundation/scripts/check.py --verbose        # progress on stderr
python3 -m unittest discover -s infra/foundation/scripts   # tests, no credentials needed
```

| `--env` | tfvars stem | Project (from tfvars) |
| --- | --- | --- |
| `dev` | `dev` | `masterpoulet-dev` |
| `prod` | `prd` | `masterpoulet-prod` |

Requires Python ≥ 3.10 and, for live checks, `gcloud` authenticated as an account
with `compute.networks.list`, `compute.subnetworks.list`,
`resourcemanager.projects.get` and `serviceusage.services.list` (for example,
`roles/viewer`). Run `gcloud auth login` first.

## Inspected resources

Live types are chosen from the resource types declared in the config. Each
supported type has an entry in `TYPE_SPECS`:

| Type | Live command | Compared attributes |
| --- | --- | --- |
| `google_compute_network` | `compute networks list` | name, auto_create_subnetworks, routing_mode |
| `google_compute_subnetwork` | `compute networks subnets list` | name, region, ip_cidr_range, network (by name), private_ip_google_access |

The script also reads the project (`projects describe`) and the list of enabled
services. Every live resource of a declared type that does not match the config
is reported as `untracked`, unless it matches a rule in `ignore.json`. Declared
types with no spec are `unknown`.

### Ignore rules (`ignore.json`)

Undeclared live resources that are intentionally unmanaged are listed in
`ignore.json`, matched by exact `type` and `name`, and each rule carries a
`reason`. A matched resource is counted in `ignored` instead of producing an
`untracked` entry. Rules never apply to resources declared in the config, so a
missing or drifted resource can't be hidden. The current rules cover the GCP
`default` network and its auto-mode subnets, which are outside Terraform per
`../README.md`. If the file is malformed, nothing is ignored and the error
appears under source `ignore`.

Attributes that use expressions beyond literals, `var.*`, `"${var.*}"` or
`<type>.<name>.<attr>` references are listed in `unverified`, never guessed.

## Output schema (version 2)

Compact JSON with sorted keys and resources sorted by `(type, address, id)`.

```
{ "schema": 2, "exit_code": int, "environments": [Env] }
Env      = { environment, project_id: str|null,
             status: "complete"|"partial"|"failed",
             sources: { terraform_config, gcloud }
                      each "ok"|"error"|"skipped"|"discovery_only",
             project: {projectId, projectNumber, lifecycleState}|null,
             services: [str]|null,        // enabled APIs; null = not inspected
             resources: [Resource],
             ignored: [{ type, name, reason, count }],  // matched ignore.json rules, count > 0
             errors: [Error], warnings: [str] }
Resource = { address: str|null, type, id: "project/[region/]name"|null, status,
             in: { config, cloud }         // true/false, or null = not determined
             evidence: [{ field, sources: "config/cloud", config, cloud }],
             unverified: [str],            // declared fields not compared
             reason: str|null }
Error    = { source, code, message }
           code: missing_tool|timeout|permission_denied|api_disabled|auth_required|
                 not_found|command_failed|malformed_output|parse_failed|no_project|<exception>
```

| Status | Meaning |
| --- | --- |
| `in_sync` | Exists live and every compared attribute matches the config. Check `unverified` for fields that were not compared. |
| `missing_in_cloud` | The listing succeeded and contains no resource with this identity. |
| `untracked` | Exists live but is not declared in the config (and matches no ignore rule). |
| `drifted` | A live attribute differs from the config. |
| `unknown` | Insufficient evidence (listing failed, unsupported type, unresolvable name, or comparison skipped). |

A failed or denied listing always produces `unknown` with `in.cloud: null`,
never `missing_in_cloud`.

`status` is `partial` when a non-skipped source failed, when a
resource is `unknown` for a reason other than a skipped source, or when any
resource has `unverified` fields.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Every environment is `complete` and has no differences. |
| 1 | At least one confirmed difference (`missing_in_cloud`, `drifted`, `untracked`). This takes priority over 3. |
| 2 | Usage error (argparse). |
| 3 | Inspection incomplete: an environment is `partial` or `failed`. |

## Safety and side effects

- `terraform` is never executed. `gcloud` runs with an argument list (no shell),
  with prompts disabled and `CLOUDSDK_CORE_SHOULD_PROMPT_TO_ENABLE_API=false`, so a
  disabled API is reported and never enabled.
- Error messages are truncated and access tokens are redacted.
- gcloud may write its own logs and credential cache under `~/.config/gcloud`.
  Python may write `__pycache__/` (ignored by Git).
- Each run makes about 4 read-only API calls per environment. They appear in
  Cloud Audit Logs (Data Access, if enabled) and count toward API quotas, at no
  meaningful cost.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `missing_tool` | Install the Cloud SDK, or run with `nix shell nixpkgs#google-cloud-sdk -c python3 ...`. |
| `auth_required` | `gcloud auth login` (or `gcloud auth application-default login` for Terraform itself). |
| `permission_denied` | Grant read access (`roles/viewer`) on the project. |
| `api_disabled` | The API is off. Resources of that type cannot exist, but the script still reports `unknown`. |
| `parse_failed` on config | The config uses HCL beyond the supported subset. Extend `parse_hcl`/`evaluate`. |

## Migration from `check.ps1`

`check.ps1` ran `terraform fmt -check`, `init`, `validate` and a dev `plan`. Those
steps initialize backends and take state locks, so they are out of scope here.
They now run in CI: `ci.yml` (`fmt -check`, `validate` with `-backend=false`) and
`terraform-ci.yml` (`plan` per environment). The dev bucket guard from
`check.ps1` is replaced by the live inspection in this script.
