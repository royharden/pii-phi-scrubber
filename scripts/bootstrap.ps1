param([switch]$Check)
$ErrorActionPreference = 'Stop'
# Python 3.11+ is sufficient for this stdlib-only launcher; the product uses 3.12.13.
$bootstrapArgs = @((Join-Path $PSScriptRoot 'bootstrap.py'))
if ($Check) { $bootstrapArgs += '--check' }
& python @bootstrapArgs
exit $LASTEXITCODE
