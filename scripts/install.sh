#!/bin/sh
# Install (or update, or remove) remarkable-mcp for the current user and
# register it with Claude Code and Claude Desktop. macOS and Linux.
#
#   sh install.sh [--ref <tag>] [--write] [--uninstall] [--yes]
#
# The server runs from a git checkout pinned to a release tag and is started
# with `uv run --frozen`, so the exact dependency versions in uv.lock are used
# (uvx / `uv tool install` ignore the lockfile). Safe to re-run.
#
# Environment overrides:
#   REMARKABLE_MCP_REF   tag (or commit) to install, same as --ref
#   REMARKABLE_MCP_REPO  git URL to clone from (default: the GitHub repository)
#   XDG_DATA_HOME        install under $XDG_DATA_HOME/remarkable-mcp
#
# See docs/team-setup.md for details.

set -eu

DEFAULT_REF="v2.1.0-mmo.1"
REF="${REMARKABLE_MCP_REF:-$DEFAULT_REF}"
REPO="${REMARKABLE_MCP_REPO:-https://github.com/MMO-Techno/remarkable-mcp}"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/remarkable-mcp"
TOKEN_FILE="$HOME/.rmapi"
CACHE_DIR="$HOME/.remarkable"
CONNECT_URL="https://my.remarkable.com/device/desktop/connect"
SERVER_NAME="remarkable"

MODE="install"
WRITE=0
ASSUME_YES=0

say() { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<EOF
Usage: install.sh [options]

Options:
  --ref <tag>    Release tag (or commit) to install (default: $DEFAULT_REF)
  --write        Allow write tools (upload, move, rename, delete, ...).
                 Default is a read-only server.
  --uninstall    Remove the client registrations, the checkout, the token
                 (~/.rmapi) and the cache (~/.remarkable).
  --yes          Do not ask for confirmation (uninstall).
  -h, --help     Show this help.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --ref)
            [ $# -ge 2 ] || die "--ref needs a value"
            REF="$2"
            shift 2
            ;;
        --ref=*)
            REF="${1#--ref=}"
            shift
            ;;
        --write)
            WRITE=1
            shift
            ;;
        --uninstall)
            MODE="uninstall"
            shift
            ;;
        --yes | -y)
            ASSUME_YES=1
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            die "unknown option: $1"
            ;;
    esac
done

[ -n "$REF" ] || die "empty --ref"
[ -n "${HOME:-}" ] || die "HOME is not set"

# Read a line from the terminal even when this script is piped into sh.
TTY=/dev/tty
if ! { : <"$TTY"; } 2>/dev/null; then
    TTY=/dev/stdin
fi

ask() { # ask <prompt> -> REPLY
    printf '%s' "$1" >&2
    REPLY=""
    IFS= read -r REPLY <"$TTY" || true
}

ask_secret() { # ask_secret <prompt> -> REPLY, without echoing what is typed
    printf '%s' "$1" >&2
    REPLY=""
    _stty=$(stty -g <"$TTY" 2>/dev/null || true)
    if [ -n "$_stty" ]; then
        trap 'stty "$_stty" <"$TTY" 2>/dev/null; exit 130' INT TERM
        stty -echo <"$TTY"
    fi
    IFS= read -r REPLY <"$TTY" || true
    if [ -n "$_stty" ]; then
        stty "$_stty" <"$TTY"
        trap - INT TERM
    fi
    printf '\n' >&2
}

case "$(uname -s)" in
    Darwin) DESKTOP_DIR="$HOME/Library/Application Support/Claude" ;;
    Linux) DESKTOP_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/Claude" ;;
    *) die "unsupported OS $(uname -s); on Windows use install.ps1" ;;
esac
DESKTOP_CONFIG="$DESKTOP_DIR/claude_desktop_config.json"

UV=$(command -v uv 2>/dev/null || true)
if [ -z "$UV" ]; then
    say "uv is required but was not found on PATH. Install it with:"
    say ""
    say "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    say ""
    say "(or 'brew install uv'), open a new terminal, then re-run this installer."
    exit 1
fi
case "$UV" in
    /*) ;;
    *) UV="$(cd "$(dirname "$UV")" && pwd)/$(basename "$UV")" ;;
esac

# Merge or remove our entry in claude_desktop_config.json. Other keys are kept;
# invalid JSON is never overwritten. Runs with uv's Python in isolated mode.
DESKTOP_PY='
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
if os.path.exists(path):
    shutil.copymode(path, tmp)
os.replace(tmp, path)
'

desktop_config() { # desktop_config add|remove [command args...]
    _action="$1"
    shift
    if [ -d "$INSTALL_DIR/.git" ]; then
        "$UV" run --frozen --quiet --directory "$INSTALL_DIR" python -I -c "$DESKTOP_PY" \
            "$_action" "$DESKTOP_CONFIG" "$SERVER_NAME" "$@"
    else
        "$UV" run --no-project --quiet python -I -c "$DESKTOP_PY" \
            "$_action" "$DESKTOP_CONFIG" "$SERVER_NAME" "$@"
    fi
}

uninstall() {
    say "This will remove:"
    say "  - the '$SERVER_NAME' MCP server from Claude Code (user scope) and Claude Desktop"
    say "  - $INSTALL_DIR"
    say "  - $TOKEN_FILE (your reMarkable device token)"
    say "  - $CACHE_DIR (cached documents)"
    if [ "$ASSUME_YES" -ne 1 ]; then
        ask "Continue? [y/N] "
        case "$REPLY" in
            y | Y | yes | YES) ;;
            *) die "aborted" ;;
        esac
    fi

    if command -v claude >/dev/null 2>&1; then
        claude mcp remove "$SERVER_NAME" -s user >/dev/null 2>&1 || true
        say "Removed from Claude Code (if it was registered)."
    fi
    if [ -f "$DESKTOP_CONFIG" ]; then
        desktop_config remove
        say "Removed from Claude Desktop config (if it was there)."
    fi
    case "$INSTALL_DIR" in
        */remarkable-mcp) ;;
        *) die "refusing to delete unexpected path $INSTALL_DIR" ;;
    esac
    rm -rf "$INSTALL_DIR"
    rm -f "$TOKEN_FILE"
    rm -rf "$CACHE_DIR"
    say ""
    say "Done. Finally, revoke the device on the reMarkable side: sign in at"
    say "https://my.remarkable.com and remove the desktop app this installer"
    say "registered from your connected devices."
}

if [ "$MODE" = "uninstall" ]; then
    uninstall
    exit 0
fi

command -v git >/dev/null 2>&1 || die "git is required but was not found on PATH"

# 1. Checkout at the pinned ref.
if [ -d "$INSTALL_DIR/.git" ]; then
    say "Updating $INSTALL_DIR to $REF ..."
    git -C "$INSTALL_DIR" remote set-url origin "$REPO"
elif [ -e "$INSTALL_DIR" ]; then
    die "$INSTALL_DIR exists but is not a git checkout; move it away and re-run"
else
    say "Cloning $REPO into $INSTALL_DIR ..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --quiet --no-checkout "$REPO" "$INSTALL_DIR"
fi
git -C "$INSTALL_DIR" fetch --quiet --force --tags origin
if git -C "$INSTALL_DIR" rev-parse -q --verify "refs/tags/$REF^{commit}" >/dev/null; then
    TARGET="refs/tags/$REF"
elif git -C "$INSTALL_DIR" rev-parse -q --verify "refs/remotes/origin/$REF^{commit}" >/dev/null; then
    TARGET="refs/remotes/origin/$REF"
elif git -C "$INSTALL_DIR" rev-parse -q --verify "$REF^{commit}" >/dev/null; then
    TARGET="$REF"
else
    die "ref '$REF' not found in $REPO"
fi
git -C "$INSTALL_DIR" -c advice.detachedHead=false checkout --quiet --detach "$TARGET"
say "Installing locked dependencies ..."
"$UV" sync --frozen --quiet --directory "$INSTALL_DIR"

# 2. reMarkable cloud token.
if [ -s "$TOKEN_FILE" ]; then
    say "Using existing token in $TOKEN_FILE."
else
    say ""
    say "Connect this computer to your reMarkable account:"
    say "  1. Open $CONNECT_URL"
    say "  2. Copy the one-time code shown there."
    ask_secret "  3. Paste the code here (input is hidden): "
    CODE=$(printf '%s' "$REPLY" | tr -d '[:space:]')
    REPLY=""
    [ -n "$CODE" ] || die "no code entered; re-run the installer when you have one"
    if ! "$UV" run --frozen --quiet --directory "$INSTALL_DIR" remarkable-mcp --register "$CODE" >/dev/null; then
        CODE=""
        die "registration failed (codes are single-use and expire quickly; get a new one)"
    fi
    CODE=""
    say "Registered. Token saved to $TOKEN_FILE."
fi
chmod 600 "$TOKEN_FILE"

# 3. MCP client registration.
if [ "$WRITE" -eq 1 ]; then
    set -- run --frozen --directory "$INSTALL_DIR" remarkable-mcp
    warn "installing WITH write tools. Anything Claude reads (documents, web pages,"
    warn "emails) can contain instructions that make it upload, move, rename or delete"
    warn "files on your reMarkable. Deletes go to the trash, but review tool calls."
else
    set -- run --frozen --directory "$INSTALL_DIR" remarkable-mcp --read-only
fi

if command -v claude >/dev/null 2>&1; then
    claude mcp remove "$SERVER_NAME" -s user >/dev/null 2>&1 || true
    claude mcp add "$SERVER_NAME" -s user -- "$UV" "$@" >/dev/null
    say "Registered with Claude Code (user scope)."
else
    say "Claude Code ('claude') not found on PATH; skipped."
fi

if [ -d "$DESKTOP_DIR" ]; then
    desktop_config add "$UV" "$@"
    say "Registered with Claude Desktop ($DESKTOP_CONFIG). Restart Claude Desktop to load it."
else
    say "Claude Desktop config folder not found; skipped."
fi

say ""
say "remarkable-mcp $REF installed in $INSTALL_DIR ($([ "$WRITE" -eq 1 ] && echo read-write || echo read-only))."
say "Re-run with --ref <tag> to update, or --uninstall to remove."
