---
name: papervpn
description: "Download paywalled papers (IEEE Xplore, Elsevier/ScienceDirect and other publishers) through the Hainan University WebVPN using the user's own institutional session. Use when the user asks to download or fetch a paper by title, DOI, IEEE arnumber, ScienceDirect PII or WebVPN URL, or mentions 海南大学 / WebVPN / IEEE / ScienceDirect / 下载论文 / 下载文献 / 电子资源. Fetches one paper at a time with polite delays and never bulk-scrapes."
license: MIT
metadata:
  short-description: "经海大 WebVPN 下载 IEEE/Elsevier 等授权论文"
  homepage: "https://webvpn.hainanu.edu.cn/"
---

# papervpn

Drive the `papervpn` tool to fetch papers the user is institutionally entitled to
read, through the Hainan University WebVPN (`webvpn.hainanu.edu.cn`). It resolves
a paper to a publisher PDF URL, proxies it through WebVPN with the user's own
session, and saves the PDF locally.

## Requirements

- An authenticated WebVPN session the user already created in their browser
  (cookie `wengine_vpn_ticket`). The tool never asks for the user's password.
- `requests` + `cryptography` (usually present); `playwright` for ScienceDirect.
- The `papervpn` CLI on `PATH`, or the launcher shipped with this skill at
  `<SKILL_ROOT>/scripts/papervpn`.

Session state (cookies, token cache, download history) lives in `~/.papervpn/`
— override with `PAPERVPN_STATE`. It is intentionally independent of the
current directory, so the CLI and the MCP server share one session regardless
of where the harness runs them. Never copy `.papervpn` into a project.

Check and set up once:

```bash
papervpn --help || "$SKILL_ROOT/scripts/setup.sh"
```

If neither works, install the package from the cloned repo:

```bash
pip install --user --break-system-packages -e .
```

## 1. Session (do this first)

```bash
papervpn check          # authenticated: True  => ready
```

### When the WebVPN session expires

`wengine_vpn_ticket` is a short-lived session cookie. When `check` (or the
`check_session` MCP tool) reports `authenticated: False`, renew it. If the user
is still logged into WebVPN in a local browser, no password is needed:

```bash
papervpn login --from-chrome     # imports the LIVE ticket from Chrome/Chromium/Firefox
```

This reads the browser's cookie store, copies the current ticket into
`~/.papervpn/cookies.json`, and re-validates. Chrome needs the `secretstorage`
package (installed by `scripts/setup.sh`); Firefox needs nothing extra.

Other renewal options:

```bash
# paste a fresh cookie from DevTools or the browser's "Copy as cURL"
papervpn login --cookie "<whole curl command>"
papervpn login --cookie "wengine_vpn_ticket=...; route=..."

# open a browser and log in by hand (needs a display)
papervpn login
```

If `--from-chrome` finds no ticket, ask the user to open
<https://webvpn.hainanu.edu.cn/> and complete the unified-identity / CARSI
login themselves, then run it again. Never ask for or record the account
password, one-time code, or CAPTCHA answer.

A valid session also unlocks the AES key automatically (via `/user/info`),
which lets `papervpn` build WebVPN URLs for new publisher hosts.

## 2. Turn the request into an identifier

The user usually gives a **title**. Resolve it to a stable id with your web
search tool, then download by that id:

| Publisher | Identifier | Example |
| --- | --- | --- |
| IEEE Xplore | arnumber (from `/document/<n>`) | `https://ieeexplore.ieee.org/document/11376648` |
| Elsevier / ScienceDirect | DOI or PII | `10.1016/j.meegid.2016.09.017` or `S1567134816304002` |
| Other (Springer, Wiley, ACM, CNKI, …) | DOI or direct URL | `10.1000/xyz` |

Prefer DOI. IEEE conference/journal papers always have an arnumber; find it via
search, do not guess.

## 3. Download

```bash
papervpn download "<URL-or-DOI>"
papervpn download "10.1016/j.meegid.2016.09.017" "https://ieeexplore.ieee.org/document/11376648"
papervpn download -b urls.txt --max 10           # small, approved batch only
papervpn download "<URL>" -o some/dir            # optional: choose the directory
```

Accepted inputs: WebVPN URLs, publisher URLs, IEEE arnumber URLs, DOIs, PIIs.
The downloader is **serial** with a 3–8 s random delay, de-duplicates against a
history file, and refuses batches over 50 items (`--max` defaults to 10).

PDFs are written to the **current working directory** by default (override with
`-o <dir>`); each file is named by arnumber or PII.

## 4. What happens per publisher

- **IEEE**: `/document/<n>` or `/stamp/stamp.jsp?arnumber=<n>` → requests
  `/stampPDF/getPDF.jsp?tp=&arnumber=<n>&ref=` (after warming up the viewer page).
- **ScienceDirect**: resolves `"pdfDownload"` from the article JSON; the
  `pdfft` endpoint is protected by a JS anti-bot challenge, so the tool falls
  back to a real Chrome window (Playwright) that clears it and captures the PDF
  response. Requires a display; pass `--browser-headed` to force a window,
  `--no-browser` to disable the fallback.
- Otherwise: follows redirects and saves the first real `application/pdf`.

## 5. Politeness and limits (required)

- One paper at a time; keep batches small (≤10) and spaced out.
- Never loop over hundreds of DOIs. ScienceDirect rate-limits hard and will
  return an anti-bot page (`CPE00001`) for several minutes.
- Re-running the same command is safe: already-downloaded items report `exists`.

## 6. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `authenticated: False` | WebVPN session expired — re-run `papervpn login --cookie ...` |
| `ScienceDirect anti-bot block (CPE00001)` | Throttled; wait a few minutes and retry one paper. Ensure the fallback runs with a display (`--browser-headed`). |
| `no PDF link found` / `not a PDF` | The paper may not be in the entitlement, or the host has no cached token; open any page on that host via WebVPN once, then `papervpn token add <webvpn-url>` (or run `papervpn key-discover`). |
| IEEE `HTTP 418` / `403` | Session/anti-bot; re-login and retry one paper. |
| Need a new publisher host | `papervpn key-discover` then `papervpn token list` |

## 7. Optional: expose as an MCP tool

The package ships an MCP server (`papervpn-mcp`) with `download_paper`,
`download_papers`, and `check_session`. Add it to a harness config:

- opencode (`~/.config/opencode/opencode.jsonc`):
  `"mcp": { "papervpn": { "type": "local", "command": ["papervpn-mcp"], "enabled": true } }`
- Codex (`~/.codex/config.toml`):
  `[mcp_servers.papervpn]` `command = "papervpn-mcp"` and `tool_timeout_sec = 900`
- DeepSeek harness (`~/.dsh/profiles/web/cordis.patch.yml`):
  an `@deepseek-ai/dsh-mcp-client` entry with `serverName: papervpn`,
  `command: papervpn-mcp` and `toolCallTimeoutMs: 1200000`

Two operational notes when calling `download_paper` over MCP:

- **Give it time.** A ScienceDirect fetch drives a real browser and can take
  ~60–120 s. Set the client tool timeout generously (900 s+), otherwise the
  call reports a timeout even though the download actually completed.
- **Prefer the working directory over `/tmp`.** Downloads default to the
  current working directory; if you pass `output_dir`, keep it inside the
  project. Some harness sandboxes give each shell call a private, empty `/tmp`,
  so a file the MCP server wrote to `/tmp` is invisible to the agent's later
  `ls`/`file`.

Restart the harness after changing config.

## Boundaries

- Use only the user's own entitled access; do not share or persist credentials
  beyond the local session file.
- Download for the user's personal reading, one paper at a time; do not
  mass-download, redistribute, or bypass paywalls the institution lacks.
- For unsubscribed items, offer legal alternatives (open access, author
  manuscript, interlibrary loan).
