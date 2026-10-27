# Team Setup

This guide is for rolling out remarkable-mcp to a team. Each person runs their
own copy of the server on their own computer, with their own reMarkable account,
and connects it to Claude Code and/or Claude Desktop. No shared server, and no
shared credentials.

The installer scripts in [`scripts/`](../scripts) do the setup in one step and
can be re-run safely.

## What it does

Once installed, Claude can browse, search and read the notebooks, PDFs and
EPUBs in your reMarkable cloud library, including handwriting (rendered pages
and OCR). By default the server is **read-only**: Claude cannot upload, move,
rename or delete anything.

The server runs locally over stdio. It is started by Claude Code / Claude
Desktop when needed and talks directly to the reMarkable cloud with your
device token. It does not listen on a network port.

## Prerequisites

- **uv**: <https://docs.astral.sh/uv/getting-started/installation/>
  (macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh` or
  `brew install uv`; Windows: `winget install --id=astral-sh.uv -e`).
  uv also provides Python, so you don't need to install Python yourself.
- **git**.
- **Claude Code** (`claude` on your PATH) and/or **Claude Desktop**. The
  installer configures whichever ones it finds.
- A **reMarkable account with cloud sync**. Cloud mode reads your library
  through the reMarkable cloud, which needs a reMarkable Connect subscription
  for full sync. (SSH, USB and local-folder modes don't need the cloud. See the
  [README](../README.md#choose-a-connection). The installer only sets up cloud
  mode.)

## Install

Each release of the installer is pinned to a tag. The examples use
`v2.1.0-mmo.1`; swap in the release you are rolling out.

### macOS and Linux

```bash
curl -fsSL https://raw.githubusercontent.com/MMO-Techno/remarkable-mcp/v2.1.0-mmo.1/scripts/install.sh | sh
```

To pass options, use `sh -s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/MMO-Techno/remarkable-mcp/v2.1.0-mmo.1/scripts/install.sh | sh -s -- --write
```

### Windows (PowerShell 5.1 or later)

```powershell
irm https://raw.githubusercontent.com/MMO-Techno/remarkable-mcp/v2.1.0-mmo.1/scripts/install.ps1 | iex
```

To pass options:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/MMO-Techno/remarkable-mcp/v2.1.0-mmo.1/scripts/install.ps1))) -Write
```

### Safer: clone, read, then run

Piping a script into a shell runs it without showing it to you. If you'd rather
read it first:

```bash
git clone --branch v2.1.0-mmo.1 https://github.com/MMO-Techno/remarkable-mcp
cd remarkable-mcp
less scripts/install.sh        # or open scripts/install.ps1 on Windows
sh scripts/install.sh          # Windows: powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

This clone is only used to run the script. The installer makes its own pinned
checkout (see below), so you can delete the clone afterwards.

### Connecting your reMarkable account

On first install, the script asks for a one-time code:

1. Open <https://my.remarkable.com/device/desktop/connect> and sign in.
2. Copy the one-time code shown there.
3. Paste it at the prompt. What you type is hidden, and the code is not
   printed or logged.

The code is single-use and expires after a few minutes. If registration fails,
get a new code and run the installer again.

### Options

| macOS/Linux | Windows | Meaning |
|-------------|---------|---------|
| `--ref <tag>` | `-Ref <tag>` | Install this release tag (default: the one the script was published with). Also `REMARKABLE_MCP_REF`. |
| `--write` | `-Write` | Enable write tools. See [Read-only vs. write](#read-only-vs-write). |
| `--uninstall` | `-Uninstall` | Remove everything. See [Uninstall](#uninstall). |
| `--yes` | `-Yes` | Don't ask for confirmation (uninstall). |

## What the installer changes

| Item | macOS / Linux | Windows |
|------|---------------|---------|
| Pinned git checkout + virtualenv | `${XDG_DATA_HOME:-~/.local/share}/remarkable-mcp` | `%LOCALAPPDATA%\remarkable-mcp` |
| Device token (owner-only permissions) | `~/.rmapi` (mode 600) | `%USERPROFILE%\.rmapi` (ACL: you only) |
| Claude Code | `claude mcp add remarkable -s user ...` (your user-level Claude Code config) | same |
| Claude Desktop, if installed | `mcpServers.remarkable` in `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `~/.config/Claude/claude_desktop_config.json` (Linux) | `%APPDATA%\Claude\claude_desktop_config.json` |

The Claude Desktop config is backed up first (`claude_desktop_config.json.bak-<timestamp>`).
Other settings and other MCP servers in the file are kept. If the file is not
valid JSON, the installer stops and leaves it unchanged.

Both clients start the server as:

```text
/absolute/path/to/uv run --frozen --directory <checkout> remarkable-mcp --read-only
```

The full path to `uv` is used because GUI apps like Claude Desktop don't see
your shell's `PATH` (Homebrew's `/opt/homebrew/bin`, for example).

At runtime the server also writes a blob cache to `~/.remarkable/cache/`
(owner-only permissions).

**Why a checkout instead of `uvx`?** `uvx` and `uv tool install` resolve
dependencies fresh and ignore `uv.lock`. Running from a checkout with
`uv run --frozen` means everyone gets exactly the dependency versions that were
locked and tested for the release, and nothing changes until you choose to
update.

## Read-only vs. write

By default the server starts with `--read-only` and Claude only gets the read
tools (`remarkable_browse`, `remarkable_read`, `remarkable_search`,
`remarkable_recent`, `remarkable_image`, `remarkable_export`,
`remarkable_status`). `remarkable_export` writes a temporary file on your
computer, but nothing on the tablet or in the cloud is changed.

`--write` / `-Write` adds `remarkable_upload`, `remarkable_markdown_to_pdf`,
`remarkable_mkdir`, `remarkable_move`, `remarkable_rename` and
`remarkable_delete`. Only enable it if people actually need Claude to change
their library. The reason is **prompt injection**: any text Claude reads (a
document on the tablet, a web page, an email, a file in your repo) can contain
instructions, and a model can be tricked into following them. With write tools
enabled, those instructions could move, rename or delete your documents, or
upload local PDFs to your account. Deletes go to the reMarkable trash and can be
recovered, and clients that support it ask for confirmation first, but read-only
is the safer default.

If you do enable writes, you can narrow them with environment variables in the
client config (see [Customizing](#customizing)):

- `REMARKABLE_ROOT_PATH=/Claude`: confine all tools, reads and writes, to one
  folder.
- `REMARKABLE_UPLOAD_DIRS=/Users/me/Documents/to-remarkable`: only allow
  uploads from these directories (separated by `:` on macOS/Linux, `;` on
  Windows).
- `REMARKABLE_UPLOAD_MAX_BYTES`: maximum upload size (default 200 MiB).

## Updating

Run the installer again with the new tag:

```bash
curl -fsSL https://raw.githubusercontent.com/MMO-Techno/remarkable-mcp/<new-tag>/scripts/install.sh | sh -s -- --ref <new-tag>
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/MMO-Techno/remarkable-mcp/<new-tag>/scripts/install.ps1))) -Ref <new-tag>
```

The existing checkout is fetched and switched to the new tag, dependencies are
re-synced, and both client entries are rewritten. Your token is kept, so you
won't be asked for a new code. Restart Claude Desktop afterwards. Pass
`--write` again if you used it before; a rerun without it reinstalls in
read-only mode.

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/MMO-Techno/remarkable-mcp/v2.1.0-mmo.1/scripts/install.sh | sh -s -- --uninstall
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/MMO-Techno/remarkable-mcp/v2.1.0-mmo.1/scripts/install.ps1))) -Uninstall
```

After you confirm, this removes the Claude Code and Claude Desktop entries, the
checkout, the token file and the cache.

Deleting the token file does **not** revoke it. To do that, sign in at
<https://my.remarkable.com>, find the connected desktop app this installer
registered, and remove it. Do this whenever a laptop is lost, reassigned or
wiped.

## Security notes

- **Token.** `~/.rmapi` holds a long-lived device token for your reMarkable
  account. Anyone who can read it can read your whole library (and change it, if
  they run their own client). The server writes it with owner-only permissions
  and the installer tightens existing files. Don't copy it between machines or
  commit it anywhere. Revoke the device at my.remarkable.com if it may have
  leaked.
- **Cache.** Document content is cached at `~/.remarkable/cache/blobs`, readable
  only by you. It's safe to delete at any time. Set
  `REMARKABLE_DISABLE_CACHE=1` to turn it off.
- **Prompt injection.** Treat everything in your library as untrusted input to
  the model. See [Read-only vs. write](#read-only-vs-write). Even in read-only
  mode, a document could ask Claude to copy its contents into another tool
  you've connected (email, chat, a web request), so check what Claude does with
  your notes.
- **No network listener.** The installer uses stdio. Don't run the server with
  `--http` unless it sits behind a reverse proxy that authenticates every
  request. The HTTP transport has no authentication of its own, and anyone who
  can reach the port can use your account. See
  [Remote access through an authenticated reverse proxy](../README.md#remote-access-through-an-authenticated-reverse-proxy).
- **Pinned versions.** Both clients run `uv run --frozen` from a checkout at a
  release tag. Upgrades only happen when you rerun the installer with a new
  `--ref`.

### TLS inspection (Cloudflare WARP/Gateway, Zscaler, corporate proxies)

The server connects directly to these hosts (cloud mode):

| Host | Used for |
|------|----------|
| `webapp-prod.cloud.remarkable.engineering` | Device registration and token renewal |
| `internal.cloud.remarkable.com` | Library sync (listing, downloading, uploading) |
| `vision.googleapis.com` | Handwriting OCR, only if you set `GOOGLE_VISION_API_KEY` |

You open `my.remarkable.com` yourself in a browser to get the one-time code.
The server never contacts it.

If your network inspects TLS, you'll see `CERTIFICATE_VERIFY_FAILED` errors,
because the server uses Python's `requests` library, which trusts its own CA
bundle (certifi) and not the OS trust store. There are two fixes:

1. **Exclude the hosts from inspection** (preferred). Add `*.remarkable.com`
   and `*.remarkable.engineering` to your TLS-inspection bypass list (for
   Cloudflare Gateway, a *Do Not Inspect* HTTP policy). Large file transfers
   may be redirected to cloud storage hosts. If downloads still fail after the
   bypass, check your gateway logs for the blocked hostname and add it too.
2. **Trust your organization's root CA.** Point `REQUESTS_CA_BUNDLE` at a PEM
   bundle that contains the public roots *and* your organization's root.
   `REQUESTS_CA_BUNDLE` replaces the default bundle, so a file with only your
   root breaks every other site. Set it in the server's environment
   (see [Customizing](#customizing)). For the install step itself, `uv` honors
   `SSL_CERT_FILE` (the same combined bundle) or `UV_NATIVE_TLS=1` (use the OS
   trust store), and `git` uses `git config --global http.sslCAInfo <bundle>`.

## Customizing

The installer doesn't set any environment variables. To add some (CA bundle,
root folder, OCR key), edit the client entries:

- **Claude Code:** re-add the server with `-e`:

  ```bash
  claude mcp remove remarkable -s user
  claude mcp add remarkable -s user -e REQUESTS_CA_BUNDLE=/path/to/bundle.pem -e REMARKABLE_ROOT_PATH=/Claude -- \
    "$(command -v uv)" run --frozen --directory ~/.local/share/remarkable-mcp remarkable-mcp --read-only
  ```

- **Claude Desktop:** add an `env` object to the `mcpServers.remarkable`
  entry in `claude_desktop_config.json`, then restart Claude Desktop:

  ```json
  "remarkable": {
    "command": "/opt/homebrew/bin/uv",
    "args": ["run", "--frozen", "--directory", "...", "remarkable-mcp", "--read-only"],
    "env": { "REQUESTS_CA_BUNDLE": "/path/to/bundle.pem" }
  }
  ```

Rerunning the installer rewrites both entries and drops these additions, so
re-apply them after an update.

See the [README](../README.md) for every environment variable.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `uv is required but was not found` | Install uv (see [Prerequisites](#prerequisites)), open a new terminal, rerun. |
| `registration failed` | Codes are single-use and expire quickly. Get a new one at <https://my.remarkable.com/device/desktop/connect> and rerun. Behind TLS inspection, see [above](#tls-inspection-cloudflare-warpgateway-zscaler-corporate-proxies). |
| `... is not valid JSON; not modifying it` | Your `claude_desktop_config.json` is broken. Fix it (or restore a `.bak-*` copy) and rerun. |
| `ref '...' not found` | Check the tag name on the repository's Releases/Tags page. |
| Claude Desktop doesn't show the server | Fully quit and restart it. In Claude Desktop, *Settings → Developer → Edit Config* opens the file it actually reads. Check the entry is there. |
| Server fails to start after moving or upgrading uv | The config stores uv's absolute path. Rerun the installer. |
| Claude Code doesn't list it | `claude mcp list` should show `remarkable`. Rerun the installer if not. Run `claude mcp get remarkable` for details. |
| Tools report `CERTIFICATE_VERIFY_FAILED` | See [TLS inspection](#tls-inspection-cloudflare-warpgateway-zscaler-corporate-proxies). |
| Anything else | Ask Claude to run `remarkable_status`, or run the server by hand: `uv run --frozen --directory <checkout> remarkable-mcp --read-only` (Ctrl+C to stop). |
