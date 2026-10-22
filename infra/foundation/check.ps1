param([switch]$LocalOnly)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & terraform fmt -check -recursive
    if ($LASTEXITCODE -ne 0) { throw 'Terraform formatting failed.' }

    if ($LocalOnly) {
        & terraform init -backend=false -input=false
        if ($LASTEXITCODE -ne 0) { throw 'Provider initialization failed.' }
    } else {
        # List only dev buckets before allowing access to the proposed backend.
        $devBuckets = & gcloud storage buckets list --project=masterpoulet-dev --format='value(name)' --quiet
        if ($LASTEXITCODE -ne 0) { throw 'Cannot audit development buckets.' }
        $backendText = Get-Content 'backends/dev.hcl' -Raw
        if ($backendText -notmatch '(?m)^bucket\s*=\s*"([^"]+)"') { throw 'Missing backend bucket.' }
        $stateBucket = $Matches[1]
        $bucketNames = @($devBuckets | ForEach-Object { $_ -replace '^gs://', '' -replace '/$', '' })
        if ($stateBucket -notin $bucketNames) { throw 'Backend bucket not found in masterpoulet-dev. Approval and bootstrap are required.' }

        & terraform init '-backend-config=backends/dev.hcl' -input=false
        if ($LASTEXITCODE -ne 0) { throw 'Remote backend initialization failed.' }
        $workspace = & terraform workspace show
        if ($LASTEXITCODE -ne 0 -or $workspace -ne 'default') { throw 'Use the default workspace for the foundation/dev prefix.' }
    }

    & terraform validate
    if ($LASTEXITCODE -ne 0) { throw 'Terraform validation failed.' }

    if (-not $LocalOnly) {
        & terraform plan '-var-file=dev.tfvars' -input=false -lock-timeout=60s '-out=dev.tfplan'
        if ($LASTEXITCODE -ne 0) { throw 'Terraform plan failed.' }
    }
} finally {
    Pop-Location
}
