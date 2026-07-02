# SessionStart hook: inject git snapshot + PROJECT_STATE.md staleness check.
# Must never block a session: swallow all errors, always exit 0.
$ErrorActionPreference = 'SilentlyContinue'

Write-Output '=== MemCore session snapshot ==='
git log --oneline -3
$dirty = (git status --porcelain | Measure-Object -Line).Lines
Write-Output "dirty files: $dirty"

# Staleness = commits since PROJECT_STATE.md was last touched (mtime is
# unreliable: commits don't bump it, clones reset it). A dirty state file
# counts as fresh (it is being updated right now).
$stateDirty = (git status --porcelain -- PROJECT_STATE.md | Measure-Object -Line).Lines
$lastTouch = git log -1 --format=%H -- PROJECT_STATE.md
if ($stateDirty -gt 0) {
    Write-Output 'PROJECT_STATE.md: fresh (uncommitted edits)'
} elseif ($lastTouch) {
    $behind = [int](git rev-list --count "$lastTouch..HEAD")
    if ($behind -gt 3) {
        Write-Output "WARNING: PROJECT_STATE.md is STALE ($behind commits since last update). Update it before new work."
    } elseif ($behind -gt 0) {
        Write-Output "PROJECT_STATE.md: $behind commit(s) behind HEAD (ok mid-phase)"
    } else {
        Write-Output 'PROJECT_STATE.md: fresh'
    }
}
exit 0
