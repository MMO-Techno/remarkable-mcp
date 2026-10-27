<#
.SYNOPSIS
    Install (or update, or remove) remarkable-mcp for the current Windows user
    and register it with Claude Code and Claude Desktop.

.DESCRIPTION
    Clones the repository at a pinned release tag into
    %LOCALAPPDATA%\remarkable-mcp, installs the locked dependencies with
    `uv sync --frozen`, registers this computer with your reMarkable account
    (hidden one-time code prompt) and adds a read-only MCP server to Claude
    Code (user scope) and Claude Desktop. Safe to re-run.

    The server runs with `uv run --frozen` from the checkout so the exact
    versions in uv.lock are used (uvx / `uv tool install` ignore the lockfile).

    Environment overrides: REMARKABLE_MCP_REF (same as -Ref) and
    REMARKABLE_MCP_REPO (git URL to clone from). See docs/team-setup.md.

.PARAMETER Ref
    Release tag (or commit) to install. Default: v2.1.0-mmo.1.

.PARAMETER Write
    Allow write tools (upload, move, rename, delete, ...). Default is read-only.

.PARAMETER Uninstall
    Remove the client registrations, the checkout, the token (~\.rmapi) and
    the cache (~\.remarkable).

.PARAMETER Yes
    Do not ask for confirmation (uninstall).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -Ref v2.1.0-mmo.1
#>
[CmdletBinding()]
param(
    [string]$Ref = $(if ($env:REMARKABLE_MCP_REF) { $env:REMARKABLE_MCP_REF } else { 'v2.1.0-mmo.1' }),
    [switch]$Write,
    [switch]$Uninstall,
    [switch]$Yes
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Repo = if ($env:REMARKABLE_MCP_REPO) { $env:REMARKABLE_MCP_REPO } else { 'https://github.com/MMO-Techno/remarkable-mcp' }
$InstallDir = Join-Path $env:LOCALAPPDATA 'remarkable-mcp'
$TokenFile = Join-Path $env:USERPROFILE '.rmapi'
$CacheDir = Join-Path $env:USERPROFILE '.remarkable'
$DesktopDir = Join-Path $env:APPDATA 'Claude'
$DesktopConfig = Join-Path $DesktopDir 'claude_desktop_config.json'
$ConnectUrl = 'https://my.remarkable.com/device/desktop/connect'
$ServerName = 'remarkable'

# Merge or remove our entry in claude_desktop_config.json. Other keys are kept;
# invalid JSON is never overwritten. Runs with uv's Python in isolated mode.
$DesktopPy = @'
import json, os, shutil, sys, tempfile, time
action, path, name = sys.argv[1], sys.argv[2], sys.argv[3]
data = {}
if os.path.exists(path):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    if text.strip():
        try:
            data = json.loads(text)
        except ValueError as e:
            sys.exit(f"{path} is not valid JSON ({e}); not modifying it. Fix or remove it and re-run.")
    if not isinstance(data, dict):
        sys.exit(f"{path} does not contain a JSON object; not modifying it.")
servers = data.get("mcpServers")
if servers is None:
    servers = {}
if not isinstance(servers, dict):
    sys.exit(f"mcpServers in {path} is not a JSON object; not modifying it.")
if action == "add":
    servers[name] = {"command": sys.argv[4], "args": sys.argv[5:]}
    data["mcpServers"] = servers
elif name in servers:
    del servers[name]
else:
    sys.exit(0)
if os.path.exists(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.bak-{stamp}"
    shutil.copy2(path, backup)
    print(f"Backed up {path} to {backup}")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".claude_desktop_config.")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
os.replace(tmp, path)
'@

function Invoke-Native {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "'$File $($Arguments -join ' ')' failed with exit code $LASTEXITCODE"
    }
}

function Test-GitRef {
    param([string]$Name)
    & git -C $InstallDir rev-parse -q --verify "$Name^{commit}" | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-DesktopConfig {
    param([string]$Uv, [string[]]$Arguments)
    $script = Join-Path ([IO.Path]::GetTempPath()) ("remarkable-mcp-desktop-{0}.py" -f [Guid]::NewGuid())
    [IO.File]::WriteAllText($script, $DesktopPy)
    try {
        if (Test-Path (Join-Path $InstallDir '.git')) {
            Invoke-Native $Uv (@('run', '--frozen', '--quiet', '--directory', $InstallDir, 'python', '-I', $script) + $Arguments)
        } else {
            Invoke-Native $Uv (@('run', '--no-project', '--quiet', 'python', '-I', $script) + $Arguments)
        }
    } finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $script
    }
}

function Remove-ClaudeCodeEntry {
    if (Get-Command claude -ErrorAction SilentlyContinue) {
        try { & claude mcp remove $ServerName -s user *> $null } catch { }
        $global:LASTEXITCODE = 0
        return $true
    }
    return $false
}

function Protect-TokenFile {
    # Owner-only access: drop inherited ACEs and grant just the current user.
    if (Get-Command icacls -ErrorAction SilentlyContinue) {
        $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        Invoke-Native 'icacls' @($TokenFile, '/inheritance:r', '/grant:r', "*${sid}:(F)") | Out-Null
    }
}

function Invoke-Uninstall {
    param([string]$Uv)
    Write-Host 'This will remove:'
    Write-Host "  - the '$ServerName' MCP server from Claude Code (user scope) and Claude Desktop"
    Write-Host "  - $InstallDir"
    Write-Host "  - $TokenFile (your reMarkable device token)"
    Write-Host "  - $CacheDir (cached documents)"
    if (-not $Yes) {
        $answer = Read-Host 'Continue? [y/N]'
        if ($answer -notmatch '^(y|yes)$') { throw 'aborted' }
    }
    if (Remove-ClaudeCodeEntry) { Write-Host 'Removed from Claude Code (if it was registered).' }
    if (Test-Path $DesktopConfig) {
        Invoke-DesktopConfig $Uv @('remove', $DesktopConfig, $ServerName)
        Write-Host 'Removed from Claude Desktop config (if it was there).'
    }
    foreach ($path in @($InstallDir, $TokenFile, $CacheDir)) {
        if (Test-Path $path) { Remove-Item -Recurse -Force $path }
    }
    Write-Host ''
    Write-Host 'Done. Finally, revoke the device on the reMarkable side: sign in at'
    Write-Host 'https://my.remarkable.com and remove the desktop app this installer'
    Write-Host 'registered from your connected devices.'
}

function Invoke-Main {
    if (-not $Ref) { throw 'empty -Ref' }

    $uvCommand = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $uvCommand) {
        Write-Host 'uv is required but was not found on PATH. Install it with:'
        Write-Host ''
        Write-Host '    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
        Write-Host ''
        Write-Host '(or "winget install --id=astral-sh.uv -e"), open a new terminal, then re-run this installer.'
        throw 'uv not found'
    }
    $uv = $uvCommand.Path

    if ($Uninstall) {
        Invoke-Uninstall $uv
        return
    }

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw 'git is required but was not found on PATH (winget install --id Git.Git -e)'
    }

    # 1. Checkout at the pinned ref.
    if (Test-Path (Join-Path $InstallDir '.git')) {
        Write-Host "Updating $InstallDir to $Ref ..."
        Invoke-Native git @('-C', $InstallDir, 'remote', 'set-url', 'origin', $Repo)
    } elseif (Test-Path $InstallDir) {
        throw "$InstallDir exists but is not a git checkout; move it away and re-run"
    } else {
        Write-Host "Cloning $Repo into $InstallDir ..."
        Invoke-Native git @('clone', '--quiet', '--no-checkout', $Repo, $InstallDir)
    }
    Invoke-Native git @('-C', $InstallDir, 'fetch', '--quiet', '--force', '--tags', 'origin')
    if (Test-GitRef "refs/tags/$Ref") {
        $target = "refs/tags/$Ref"
    } elseif (Test-GitRef "refs/remotes/origin/$Ref") {
        $target = "refs/remotes/origin/$Ref"
    } elseif (Test-GitRef $Ref) {
        $target = $Ref
    } else {
        throw "ref '$Ref' not found in $Repo"
    }
    Invoke-Native git @('-C', $InstallDir, '-c', 'advice.detachedHead=false', 'checkout', '--quiet', '--detach', $target)
    Write-Host 'Installing locked dependencies ...'
    Invoke-Native $uv @('sync', '--frozen', '--quiet', '--directory', $InstallDir)

    # 2. reMarkable cloud token.
    if ((Test-Path $TokenFile) -and ((Get-Item $TokenFile).Length -gt 0)) {
        Write-Host "Using existing token in $TokenFile."
    } else {
        Write-Host ''
        Write-Host 'Connect this computer to your reMarkable account:'
        Write-Host "  1. Open $ConnectUrl"
        Write-Host '  2. Copy the one-time code shown there.'
        $secure = Read-Host '  3. Paste the code here (input is hidden)' -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $code = ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)) -replace '\s', ''
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
        if (-not $code) { throw 'no code entered; re-run the installer when you have one' }
        & $uv run --frozen --quiet --directory $InstallDir remarkable-mcp --register $code | Out-Null
        $failed = ($LASTEXITCODE -ne 0)
        $code = $null
        if ($failed) { throw 'registration failed (codes are single-use and expire quickly; get a new one)' }
        Write-Host "Registered. Token saved to $TokenFile."
    }
    Protect-TokenFile

    # 3. MCP client registration.
    $serverArgs = @('run', '--frozen', '--directory', $InstallDir, 'remarkable-mcp')
    if ($Write) {
        Write-Warning 'Installing WITH write tools. Anything Claude reads (documents, web pages, emails) can contain instructions that make it upload, move, rename or delete files on your reMarkable. Deletes go to the trash, but review tool calls.'
    } else {
        $serverArgs += '--read-only'
    }

    if (Remove-ClaudeCodeEntry) {
        Invoke-Native claude (@('mcp', 'add', $ServerName, '-s', 'user', '--', $uv) + $serverArgs) | Out-Null
        Write-Host 'Registered with Claude Code (user scope).'
    } else {
        Write-Host "Claude Code ('claude') not found on PATH; skipped."
    }

    if (Test-Path $DesktopDir) {
        Invoke-DesktopConfig $uv (@('add', $DesktopConfig, $ServerName, $uv) + $serverArgs)
        Write-Host "Registered with Claude Desktop ($DesktopConfig). Restart Claude Desktop to load it."
    } else {
        Write-Host 'Claude Desktop config folder not found; skipped.'
    }

    $mode = if ($Write) { 'read-write' } else { 'read-only' }
    Write-Host ''
    Write-Host "remarkable-mcp $Ref installed in $InstallDir ($mode)."
    Write-Host 'Re-run with -Ref <tag> to update, or -Uninstall to remove.'
}

try {
    Invoke-Main
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    # Only set an exit code when run as a script file; `exit` inside an
    # `irm | iex` scriptblock would close the user's PowerShell window.
    if ($PSCommandPath) { exit 1 }
}
