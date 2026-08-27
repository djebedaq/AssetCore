param(
    [string]$Python = "backend/.venv/Scripts/python.exe",
    [string]$Pnpm = "pnpm"
)

$ErrorActionPreference = "Stop"
$script:Failures = 0

function Invoke-Check([string]$Name, [scriptblock]$Action) {
    Write-Host "`n== $Name =="
    try {
        & $Action
        if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
        Write-Host "PASS: $Name" -ForegroundColor Green
    } catch {
        $script:Failures += 1
        Write-Host "FAIL: $Name - $($_.Exception.Message)" -ForegroundColor Red
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment not found: $Python"
}

$qaDir = Join-Path $PWD ".tmp/release-qa"
New-Item -ItemType Directory -Force -Path $qaDir | Out-Null

Invoke-Check "Backend runtime and CI dependency install" { & $Python -m pip install -r backend/requirements.txt -r backend/requirements-ci.txt }
Invoke-Check "Python dependency compatibility" { & $Python -m pip check }
Invoke-Check "Python dependency audit" { & $Python scripts/audit_dependencies.py python --output "$qaDir/python-audit.json" }

Invoke-Check "No tracked databases, backups, secrets or private keys" {
    $unsafe = git ls-files | Select-String -Pattern '(?i)(\.db$|\.sqlite3?$|\.dump$|\.backup$|(^|/)(\.env|private_keys)(/|$)|\.(pem|key|p12|pfx)$)'
    if ($unsafe) { $unsafe | ForEach-Object { Write-Host $_ }; throw "unsafe tracked files" }
}
Invoke-Check "Verified HPWJ seed count" {
    & $Python -c "from pathlib import Path; import ast; m=ast.parse(Path('backend/app/seed.py').read_text(encoding='utf-8')); value=next(ast.literal_eval(n.value) for n in m.body if isinstance(n,ast.Assign) and any(getattr(t,'id',None)=='MACHINES' for t in n.targets)); assert len(value)==19; assert {x['inventory_number'] for x in value}=={'4','5','7','9','10','11','12','13','14','15','16','17','18','19','20','21','22','23','24'}"
}
Invoke-Check "Python compile" { & $Python -m compileall -q backend/app backend/alembic backend/scripts scripts tests }
Invoke-Check "Python lint" { & $Python -m ruff check backend/app backend/alembic backend/scripts scripts tests }
Invoke-Check "Alembic single head" { & $Python -m alembic -c backend/alembic.ini heads }
Invoke-Check "Historical migration integrity" { & $Python backend/scripts/validate_migration_history.py }
Invoke-Check "Authorization inventory" { & $Python backend/scripts/validate_authorization_inventory.py }
Invoke-Check "Catalog translations" {
    $qaPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = 'backend'
        & $Python backend/scripts/build_catalog_translations.py --check
    } finally {
        $env:PYTHONPATH = $qaPythonPath
    }
}
Invoke-Check "Backend tests" { & $Python -m pytest -q }
Invoke-Check "Document QA" { & $Python backend/scripts/document_qa.py $qaDir }
Invoke-Check "Isolated release invariants" { & $Python scripts/verify_release.py --output $qaDir }
Invoke-Check "Legal and SBOM files" {
    @('LICENSE_PROPRIETARY_BG.md','COPYRIGHT_NOTICE.txt','NOTICE.md','THIRD_PARTY_LICENSES.md','SOFTWARE_BOM.md','SECURITY.md','docs/LICENSE_ADMIN_BG.md','docs/USER_MANAGEMENT_BG.md','docs/SIGNATURE_WORKFLOW_BG.md','docs/DOCUMENT_WORKFLOW_BG.md') | ForEach-Object { if (-not (Test-Path -LiteralPath $_)) { throw "missing $_" } }
}

Push-Location frontend
try {
    Invoke-Check "Frontend dependency install" { $env:CI='true'; & $Pnpm install --frozen-lockfile }
    Invoke-Check "TypeScript" { & $Pnpm run typecheck }
    Invoke-Check "Frontend lint" { & $Pnpm run lint }
    Invoke-Check "Frontend tests" { & $Pnpm run test }
    Invoke-Check "Frontend production build" { & $Pnpm run build }
} finally {
    Pop-Location
}
Invoke-Check "Frontend dependency audit" { & $Python scripts/audit_dependencies.py frontend --output "$qaDir/frontend-audit.json" }

if (Get-Command docker -ErrorAction SilentlyContinue) {
    Invoke-Check "Docker Compose configuration" { docker compose config --quiet }
    Invoke-Check "Docker production image" { docker build -t assetcore:release-qa . }
} else {
    Write-Host "SKIP: Docker is not installed on this workstation." -ForegroundColor Yellow
}

if ($env:ASSETCORE_POSTGRES_SOURCE_URL -and $env:ASSETCORE_POSTGRES_RESTORE_URL) {
    Invoke-Check "PostgreSQL migrations and real backup/restore" { & $Python scripts/postgres_smoke_test.py }
} else {
    Write-Host "SKIP: Separate PostgreSQL QA database URLs are not configured." -ForegroundColor Yellow
}

if ($env:ASSETCORE_POSTGRES_CONCURRENCY_URL) {
    Invoke-Check "Real PostgreSQL concurrent transactions" { & $Python -m pytest -q tests/postgres --durations=10 }
} else {
    Write-Host "SKIP: Dedicated PostgreSQL concurrency database URL is not configured." -ForegroundColor Yellow
}

if ($script:Failures -gt 0) {
    Write-Host "`nRelease verification failed: $script:Failures check(s)." -ForegroundColor Red
    exit 1
}
Write-Host "`nRelease verification completed successfully." -ForegroundColor Green
