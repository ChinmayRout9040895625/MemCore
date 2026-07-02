# SessionStart hook: inject git snapshot + PROJECT_STATE.md staleness check.
# Must never block a session: swallow all errors, always exit 0.
$ErrorActionPreference = 'SilentlyContinue'

Write-Output '=== MemCore session snapshot ==='
git log --oneline -3
$dirty = (git status --porcelain | Measure-Object -Line).Lines
Write-Output "dirty files: $dirty"

$state = Get-Item 'PROJECT_STATE.md'
$lastCommitIso = git log -1 --format=%cI
if ($state -and $lastCommitIso) {
    $lastCommit = [datetime]::Parse($lastCommitIso)
    if ($state.LastWriteTime -lt $lastCommit) {
        Write-Output 'WARNING: PROJECT_STATE.md is STALE (older than last commit). Update it before new work.'
    } else {
        Write-Output 'PROJECT_STATE.md: fresh'
    }
}
exit 0
