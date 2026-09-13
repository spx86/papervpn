# papervpn

Fetch papers you are **institutionally entitled to read** — IEEE Xplore,
Elsevier ScienceDirect, and other publishers Hainan University subscribes to —
through the university's **WebVPN** (`webvpn.hainanu.edu.cn`).

It works as a CLI, as an **MCP server** for AI agents, and as a bundled
**skill** for opencode / Codex / Claude Code / the DeepSeek harness.

It downloads **one paper at a time, with polite delays**, and never bypasses a
paywall the institution does not have — it only automates access the user
already has.

## How it works

The Hainan WebVPN is a 网瑞达 / Wengine gateway. A proxied URL looks like

```
https://webvpn.hainanu.edu.cn/https/<TOKEN>/<original-path>
```

where `TOKEN = IV(16 bytes) + AES-CFB(hostname)` and is deterministic per host.
papervpn:

1. reuses your browser's authenticated `wengine_vpn_ticket` session;
2. builds/reuses the per-host token (and can regenerate tokens for new hosts
   after reading `wrdvpnKey` / `wrdvpnIV` from the portal's `/user/info`);
3. rewrites the publisher page into its real PDF endpoint — IEEE
   `stamp/stamp.jsp` → `stampPDF/getPDF.jsp`, ScienceDirect `"pdfDownload"` →
   `pdfft` (clearing the JS challenge with a real Chrome window);
4. saves the PDF, de-duplicates, and throttles.

## Requirements

- Python ≥ 3.10, `requests`, `cryptography`.
- Optional: `playwright` (ScienceDirect), `secretstorage` (renew the session
  from the browser keyring).
- An existing, logged-in WebVPN session in a local browser.

## Install

```bash
pip install --user --break-system-packages -e .
# or just run the launchers in skill/papervpn/scripts/
```

Install the agent skill. By default it goes to `~/.agents/skills`, the shared
directory that opencode, Codex, Claude Code and dsh all read — one copy covers
them all:

```bash
./install_skill.sh                 # -> ~/.agents/skills (default)
./install_skill.sh -a codex,dsh    # or pick specific agents (multi-select)
./install_skill.sh --all           # install to every known agent
./install_skill.sh --list          # show install status
./install_skill.sh -r --all        # remove from everywhere
```

## Quick start

```bash
papervpn check                                     # authenticated: True ?
papervpn login --from-chrome                       # import the live ticket from your browser
papervpn download "10.1016/j.jare.2020.03.005"     # saves into the current directory
papervpn download "https://ieeexplore.ieee.org/document/11376648" -o some/dir
```

Accepted inputs: WebVPN URLs, publisher URLs, IEEE `/document/<arnumber>`
URLs, DOIs, and ScienceDirect PIIs.

## CLI

| Command | Purpose |
| --- | --- |
| `papervpn check` | Validate the session; prints the token/key status |
| `papervpn login` | Authenticate: `--from-chrome`, `--cookie "<header\|curl\|file>"`, or open a browser |
| `papervpn download <urls…>` | Download PDFs (`-b/--batch`, `-o/--output`, `--max`, `--no-browser`, `--browser-headed`) |
| `papervpn key-discover` | Read `wrdvpnKey`/`wrdvpnIV` from the portal to encode new hosts |
| `papervpn token list\|add` | Inspect / extend the per-host token cache |

Download politeness: serial, 3–8 s random delay, de-duplicated history,
`--max 10` per run, hard cap 50 items.

## When the session expires

`wengine_vpn_ticket` is short-lived. When `check` reports
`authenticated: False`, renew it — no password needed if the browser is still
logged in:

```bash
papervpn login --from-chrome
```

This reads the live ticket from Chrome/Chromium (keyring via `secretstorage`)
or Firefox (plaintext) and saves it to `~/.papervpn/cookies.json`. Fallbacks:

```bash
papervpn login --cookie "<browser 'Copy as cURL'>"
papervpn login --cookie "wengine_vpn_ticket=...; route=..."
papervpn login            # open a browser and log in by hand
```

## MCP server

`papervpn-mcp` speaks stdio MCP and exposes `download_paper`,
`download_papers`, and `check_session`.

```jsonc
// opencode ~/.config/opencode/opencode.jsonc
"mcp": { "papervpn": { "type": "local", "command": ["papervpn-mcp"], "enabled": true } }
```

```toml
# Codex ~/.codex/config.toml
[mcp_servers.papervpn]
command = "papervpn-mcp"
tool_timeout_sec = 900
```

Give the client a generous tool timeout: a ScienceDirect fetch drives a real
browser and can take ~60–120 s. Downloads default to the current working
directory; if you pass `output_dir`, keep it inside the project (not a
sandbox-private `/tmp`).

## Configuration

State lives in `~/.papervpn/` (cookies, token cache, download history) and is
independent of the working directory, so the CLI and MCP server share one
session.

| Env var | Meaning |
| --- | --- |
| `PAPERVPN_STATE` | State directory (default `~/.papervpn`) |
| `PAPERVPN_OUTPUT` | Default download directory (default: current working directory) |
| `PAPERVPN_HOST` | WebVPN host (default `webvpn.hainanu.edu.cn`) |
| `PAPERVPN_AES_KEY` / `PAPERVPN_AES_IV` | Override the host-token codec key/IV |
| `PAPERVPN_ROOT` | Source tree used by the skill launchers |

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `authenticated: False` | `papervpn login --from-chrome` |
| `ScienceDirect anti-bot block (CPE00001)` | Throttled — wait a few minutes and retry one paper with `--browser-headed` |
| `must be accessed through the WebVPN but no token is cached` | Open the host once through the WebVPN, then `papervpn token add <url>` or `papervpn key-discover` |
| IEEE `HTTP 418` / `403` | Re-login and retry a single paper |
| ScienceDirect returns HTML, not PDF | Chrome must be available; run with a display (`--browser-headed`) |

## Legal & acceptable use

Use only **your own** institutional entitlement, for **personal reading**.
Download one paper at a time; do not mass-download, redistribute, or attempt to
access content the university does not subscribe to. This tool automates a
logged-in session that the user controls; it never asks for or stores an
account password, one-time code, or CAPTCHA answer.

## License

[MIT](LICENSE)
