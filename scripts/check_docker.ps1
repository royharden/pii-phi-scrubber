param(
    [string]$Python = 'python',
    [Parameter(Mandatory)][string]$PortsScript,
    [string]$ContainerName = 'm7-r03-rv2-e2e',
    [string]$ImageTag = 'm7-r03-rv2-eval:local'
)
$ErrorActionPreference = 'Stop'
if ($ContainerName -notmatch '^m7-r03-rv2-[a-z0-9-]+$' -or $ImageTag -notmatch '^m7-r03-rv2-') {
    throw 'Only assigned m7-r03-rv2 resources are allowed'
}
$root = Split-Path -Parent $PSScriptRoot
& $Python $PortsScript check 'M7/r03-rv2'
if ($LASTEXITCODE -ne 0) { throw 'Port/resource preflight failed or unknown' }
docker build --label agentports.project=m7 --label agentports.instance=r03-rv2 --label agentports.owner=0017 -t $ImageTag $root
if ($LASTEXITCODE -ne 0) { throw 'Docker build failed' }
$imageId = docker image inspect --format '{{.Id}}' $ImageTag
if ($LASTEXITCODE -ne 0) { throw 'Image identity unavailable' }
Write-Output "Image: $imageId"
docker run --name $ContainerName --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges --label agentports.project=m7 --label agentports.instance=r03-rv2 --label agentports.owner=0017 $imageId
if ($LASTEXITCODE -ne 0) { throw 'Docker public eval failed; container retained for investigation' }
& $Python $PortsScript observe 'M7/r03-rv2'
if ($LASTEXITCODE -ne 0) { throw 'Docker passed but resource observation failed' }
