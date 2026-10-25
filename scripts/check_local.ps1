param(
    [string]$Python = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'),
    [string]$EvidenceDirectory
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Create the project-local Python 3.12 environment with the documented bootstrap first.'
}
& $Python -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 2)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }

# Run all local synthetic tests; never invoke the locked evaluator/train CLI.
# No install, environment mutation, provider selection or Docker lifecycle here.
$pytestArgs = @('-m', 'pytest', '-c', (Join-Path $root 'pyproject.toml'), (Join-Path $root 'tests'), '-q')
if ($EvidenceDirectory) {
    $evidence = New-Item -ItemType Directory -Force -Path $EvidenceDirectory
    $report = Join-Path $evidence.FullName ('pytest-' + [guid]::NewGuid().ToString('N') + '.xml')
    $pytestArgs += "--junitxml=$report"
}
& $Python @pytestArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Owned reviewer scope only; root/source lint belongs to implementation owners.
$lintPaths = @('contracts', 'render', 'detectors', 'providers', 'training', 'data', 'host', 'e2e') |
    ForEach-Object { Join-Path $root "tests\$_" }
& $Python -m ruff check @lintPaths
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& git -C $root diff --check
exit $LASTEXITCODE
