# UI-TARS Policy Matrix

TaijiOS treats UI-TARS style model output as a proposal, not as executable
authority. Every action must pass a policy matrix before an operator can run it.

## Surfaces

| Surface | Purpose | Execution |
| --- | --- | --- |
| `browser_readonly` | Read registered browser content and produce reports. | Only registered pages; no network fetch from the adapter. |
| `desktop_shadow` | Review local GUI actions suggested by a visual model. | Requires confirmation; default POC does not execute. |
| `desktop` | Future production desktop control surface. | Must still pass policy and confirmation gates. |

## Default Effects

| Action group | Examples | Effect |
| --- | --- | --- |
| Browser read-only | `navigate`, `open_url`, `read_page`, `read_current_page`, `wait` | Allow only on `browser_readonly`. |
| Desktop GUI | `click`, `drag`, `scroll`, `type`, `hotkey`, `press`, `release` | Shadow; requires TaijiOS review. |
| Terminal | `finished`, `call_user`, `error_env`, `max_loop`, `user_stop` | Allow; no external side effect. |
| Forbidden | `delete_file`, `overwrite_file`, `move_file`, `trade`, `buy`, `sell`, `checkout`, `transfer`, `copy_secret`, `paste_secret` | Block. |
| Secret-bearing input | Any action input containing token/API-key/secret-like text | Block. |
| Live workflow | Any non-terminal action when `live_workflow=true` | Block. |

## Browser-Only Adapters

`ReadOnlyBrowserAdapter` is intentionally narrow and offline:

- It opens only URLs pre-registered in its page map.
- It returns sanitized title/text extracted from HTML.
- It records `network=false` for opens.
- It blocks clicks, typing, hotkeys, submit/checkout/trade actions and unknown actions.
- It does not embed screenshots or execute live browser automation.

`PlaywrightReadOnlyBrowserAdapter` is the first real-browser layer:

- `allowed_hosts` is required.
- Navigation is limited to `http`/`https` URLs on allowed hosts.
- It extracts sanitized title/body text only.
- It records `network=true`.
- It blocks non-GET/HEAD/OPTIONS requests through Playwright route guards.
- It exposes no click, type, submit, upload, download or checkout helpers.
- Side-effect actions through `execute()` return `blocked`.

Optional local setup:

```bash
pip install -e ".[browser]"
python -m playwright install chromium
```

The combined package gate remains:

```bash
python -m aios.gui_agent.ops_check_gate
python examples/validate_gui_agent_ops_check.py
```

The gate writes a machine-readable manifest at:

```text
runs/ops_check/gui_agent_ops_check_20260511/policy_matrix.json
```

The validator checks that required controls are enabled, forbidden actions keep
`effect=block`, browser read-only rows remain scoped to `browser_readonly`, and
desktop GUI rows remain `effect=shadow` with confirmation required.
It also replays event flows against this manifest: browser open/read events must
have a prior allowed policy decision, and desktop shadow proposals must remain
pending confirmation rather than executing.

The gate must return `ok=true` before any browser executor work is promoted.
Its combined summary also keeps top-level `trade=false`, `promote=false`,
`live_workflow=false`, `side_effects=false`, and `secret_detected=false`
fields that are enforced by `validate_gui_agent_ops_check.py`.

For the standalone browser read-only task runner:

```bash
python examples/browser_readonly_task.py
python examples/validate_browser_readonly_task.py
```
