# PushToGit.ps1
# Auto-push to GitHub main with SSH by default; HTTPS fallback if needed.

# Find git repo root (current folder or parents)
function Find-GitRepoRoot([string]$startPath) {
    $path = (Resolve-Path $startPath).Path
    while ($path) {
        if (Test-Path (Join-Path $path ".git")) { return $path }
        $parent = [System.IO.Directory]::GetParent($path)
        if ($parent -eq $null) { break }
        $path = $parent.FullName
    }
    # Fallback: if still not found, try current dir
    if (Test-Path (Join-Path (Get-Location).Path ".git")) { return (Get-Location).Path }
    return $null
}

$repoRoot = Find-GitRepoRoot (Get-Location).Path
if (-not $repoRoot) {
    Write-Host "No git repo found in this folder or its parents." -ForegroundColor Red
    exit 1
}
Write-Host "Repo root: $repoRoot"

# Ensure git is available
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

$originUrl = & git -C "$repoRoot" config --get remote.origin.url 2>$null
if (-not $originUrl) {
    & git -C "$repoRoot" remote add origin git@github.com:slnquangtran/CUE.git
} else {
    & git -C "$repoRoot" remote set-url origin git@github.com:slnquangtran/CUE.git
}
$branch = "main"
$currentBranch = & git -C "$repoRoot" rev-parse --abbrev-ref HEAD
Write-Host "Pushing from '$currentBranch' to '$branch' on origin..."

# Try SSH push first
$sshPush = & git -C "$repoRoot" push -u origin HEAD:$branch 2>&1
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "SSH push succeeded." -ForegroundColor Green
    exit 0
}

Write-Warning "SSH push failed. Output:"
Write-Host $sshPush

# Fallback: if SSH auth failed, try HTTPS (will prompt for credentials)
if ($sshPush -match "Permission denied|Authentication failed|Could not read from remote repository") {
    Write-Host "SSH authentication failed. Attempt HTTPS fallback (will prompt for credentials)." -ForegroundColor Yellow
    & git -C "$repoRoot" remote set-url origin https://github.com/slnquangtran/CUE.git
    $httpsPush = & git -C "$repoRoot" push -u origin HEAD:$branch 2>&1
    $exitCode2 = $LASTEXITCODE
    if ($exitCode2 -eq 0) {
        & git -C "$repoRoot" remote set-url origin git@github.com:slnquangtran/CUE.git
        Write-Host "HTTPS push succeeded. Remote reset to SSH." -ForegroundColor Green
        exit 0
    } else {
        Write-Host "HTTPS push failed." -ForegroundColor Red
        Write-Host $httpsPush
        exit $exitCode2
    }
} else {
    Write-Host "Push failed for an unexpected reason." -ForegroundColor Red
    Exit $exitCode
}
