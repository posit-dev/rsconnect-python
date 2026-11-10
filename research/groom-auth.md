# Groom: Auth & server config

Research for #957 (map #956). Each of the 14 open issues in this batch was checked against the code at `main` @ `2ea5fdd2` (rsconnect-python 1.33.2.dev1), git history, merged PRs, and `docs/CHANGELOG.md`.

CLI behaviour was checked locally with `uv run rsconnect ...`, using a throwaway `HOME` with servers seeded at `https://<name>.invalid`, so every network call fails at DNS. No live Connect, shinyapps.io, or Connect Cloud server was contacted.

File references (`file:line`) are to `2ea5fdd2`.

## Summary

| Verdict | Count | Issues |
| --- | --- | --- |
| Resolved | 2 | #541, #858 |
| Obsolete | 0 | — |
| Still valid | 12 | #165, #215, #220, #377, #413, #646, #699, #716, #791, #799, #842, #843 |
| Unclear | 0 | — |

Proposed for closing: 2 (#541 and #858, both as `completed`).

## Duplicates and related issues

- **#646 partly overlaps #542** (in the content batch, #963, marked Still valid there). Both report that redeploying after the content was deleted on the server fails with "The requested object does not exist ... Try setting the --new flag". #542 asks only for that: treat a stale record as a new deployment. #646 also objects to the global fallback record under the config directory (`rsconnect/metadata.py:866`) and to records keyed by absolute path. **This is not a clean duplicate, so keep both.** If the human prefers one issue, keep **#542** for the "stale record → create new content" fix: it has the narrower spec, and Connect Cloud already behaves that way (`rsconnect/api.py:4022-4026`). Then narrow #646 to the global-state concern.
- **#220 and #799** are related (keeping API keys out of shell history and out of plaintext files) but ask for different changes: a `getpass` prompt versus keyring storage. Keep both.
- **#791 and #799** both concern the optional `keyring` extra. #791 asks to make it discoverable for `login` tokens, and #799 asks to use it for `add` API keys. Keep both.
- **#842 and #843** are complementary, and #843 says so: #842 is an automatic device-code fallback (Connect ≥ 2026.06), and #843 is a login path for older Connect from Workbench. Keep both.
- **#377 and #699** both report unhelpful errors for a bad server target, but on different paths: no credential versus a URL without a scheme. Keep both.

## Verdict table

| Issue | Verdict | Evidence | Proposed close reason |
| --- | --- | --- | --- |
| #165 Adding custom headers to the rsconnect add cli command | Still valid | No header option exists on `add` or `deploy`. `grep -n header rsconnect/main.py` finds only the `Generated-By` parsing (`main.py:5249-5287`). The maintainer's 2021 question went unanswered. Feature request. | — |
| #215 detect system certificates by default | Still valid | TLS still uses Python's default OpenSSL context, not the OS trust store: `http.HTTPSConnection(host_name, ...)` with no context (`rsconnect/http_support.py:272`), and `ssl.create_default_context(cadata=...)` only with `--cacert` (`:248`). There is no `truststore` dependency in `pyproject.toml`. | — |
| #220 Provide an alternative to the `--api-key` flag when adding a new server nickname | Still valid | `-k/--api-key` has no `prompt`/`hide_input` (`rsconnect/main.py:435-441`), and nothing calls `getpass`. `CONNECT_API_KEY` and `rsconnect login` (1.30.0) are partial alternatives, but the prompt was never added. A triage comment on 2026-11-05 confirms "The tool still has no prompt". | — |
| #377 Message `Error: Unable to infer Connect server type and setup server` not very informative | Still valid | Same message today (`rsconnect/api.py:1958`). Reproduced locally: `rsconnect deploy shiny -n bare <dir>` against a saved entry with no API key, and `rsconnect deploy shiny -s https://nokey3.invalid <dir>` with no key, both print `Error: Unable to infer Connect server type and setup server.` | — |
| #413 `rsconnect add server` with --cacert doesn't work with `.der` certs | Still valid | DER files are still read as `bytes` (`rsconnect/certificates.py:34-36`), `add` saves them as-is (`rsconnect/main.py:1251`), and the store serialises with `json.dumps` (`rsconnect/metadata.py:355`). Reproduced: `ServerStore(tmp).set("der", "https://x.invalid", api_key="k", ca_data=b"\x30\x82\x01")` raises `TypeError: Object of type bytes is not JSON serializable`. The base64 idea from the 2023 comments was not implemented. | — |
| #541 stack trace when you have multiple saved servers and don't pick one | **Resolved** | Root cause: the "no target" guard in `validation.py` tested `not shinyapps_options`, which is a dict and always truthy, so it never fired. #777 (1.30.0, commit `03c506f6`) changed it to `not any(shinyapps_options.values()) and not has_default_server` (`rsconnect/validation.py:302`). Reproduced locally with three saved servers and no default: `rsconnect deploy shiny <dir>` prints `Error: You must specify one of -n/--name OR -s/--server OR --connect-cloud OR -T/--token, -S/--secret ...` and exits 1, with no traceback. 1.30.0 also added `--set-default`, and 1.31.0 reuses the directory's deployment record. | completed |
| #646 deploy fails to redeploy due to global config | Still valid | A deleted item still fails the redeploy, with only a `--new` hint (`rsconnect/api.py:1129-1131`, unchanged since 2023). `AppStore` still falls back to a global record keyed by `sha1(abspath(app_file))` (`rsconnect/metadata.py:861-866`). `load()` reads it when the local record is missing (`:207-213`), so deleting `rsconnect-python/` does not reset the state. Partial overlap with #542 (see above). | — |
| #699 ValueError: The "" URL scheme is not supported. | Still valid | Reproduced on current code: `rsconnect deploy shiny -s noscheme.invalid -k abc <dir>` (a server URL without `https://`) ends in a traceback, `ValueError: The "" URL scheme is not supported.` / `Internal error: ...`, raised at `rsconnect/http_support.py:457` before any network call. The reporter most likely had a scheme-less `CONNECT_SERVER`/`-s`. The fix is to normalise the scheme or report an `RSConnectException`. With no target at all, a clear error is printed (see #541). | — |
| #716 bootstrap should error if no API key is returned | Still valid | #879 (1.33.0) added the `v1/bootstrap` endpoint with a fallback to the experimental one on 404 (`rsconnect/api.py:603-609`). However, non-200 responses still exit 0: `produce_bootstrap_output(404, {})` and `(401, {...})` return `{"status": ..., "api_key": "", "message": ...}` without raising (`rsconnect/json_web_token.py:96-131`), and `bootstrap` prints that and returns (`rsconnect/main.py:1064-1071`). Pre-2022.10 Connect is unsupported, but 401/403 still exit 0. | — |
| #791 Make system keyring discoverable (or default) for rsconnect login | Still valid | The fallback message is unchanged: `Note: keyring not available; credentials stored in local file (chmod 600).` (`rsconnect/main.py:1195`, `:1805`). It has no install hint. `rsconnect login --help` doesn't mention the `[keyring]` extra, and `keyring` is still optional (`pyproject.toml:27`). | — |
| #799 Store API keys in keyring, if available | Still valid | `add` writes the API key into `servers.json` (`rsconnect/main.py:1247-1252`). The keyring is used only for OAuth tokens and Connect Cloud secrets (`main.py:1170-1188`). | — |
| #842 Fall back to device code auth when the localhost browser callback can't complete | Still valid | The browser flow waits up to `_CALLBACK_TIMEOUT_SECONDS = 600` and then raises `OAuth browser callback timed out` (`rsconnect/oauth.py:35`, `:378-382`), with no retry. `login` uses device code only with `--use-device-code` (`rsconnect/main.py:1750-1756`). There is no environment detection. | — |
| #843 Provide a login path that works in Workbench against Connect < 2026.06 | Still valid | Neither option was implemented. Dynamic Client Registration still hardcodes `"redirect_uris": ["http://127.0.0.1/callback"]` (`rsconnect/oauth.py:238`), and the callback listens on loopback (`:345-347`). There is no `--redirect-uri` and no legacy `/__api__/tokens` claim flow. Older servers still get `Server does not support the device code flow` (`:421`). | — |
| #858 Two-step device code login for environments that cannot wait for approval | **Resolved** | #859 (merged 2026-10-14, released in 1.32.0; CHANGELOG: "`login` and `add --connect-cloud` can start device-code authentication and return approval details as JSON. Finish a pending login by nickname with `--finish`") added `--no-wait`, `--finish` and `--timeout` to `login` and `add` (both `--help` outputs show them). Each requirement is met. Pending state is written with owner-only permissions (`rsconnect/device_login.py`). Re-running start reuses an unexpired code (`device_login.py:828-836`). Results carry `"status": "pending"`/`"done"` JSON (`:786-795`, `:1082`, `:1107`). The device code is never printed (only `user_code`). Expired state is removed (`:830-832`). Both Connect and Connect Cloud are supported. `tests/test_device_login.py`: 99 passed. Caveat: it requires POSIX. | completed |

## Draft closing comments

### #541 (completed)

> 🤖 This is fixed. The check for a missing deploy target never fired, because it tested a dict that was always truthy. That's how a deploy with several saved servers and no `-n` reached the `NoneType` traceback. #777 (released in 1.30.0) fixed the check (`rsconnect/validation.py:302`). Running `rsconnect deploy shiny <dir>` with three saved servers and no default now exits 1 with:
>
> ```
> Error: You must specify one of -n/--name OR -s/--server OR --connect-cloud OR -T/--token, -S/--secret, either via command options or environment variables.
> ```
>
> Since 1.30.0 you can also mark one server as the default with `rsconnect server set-default -n <name>`, or `rsconnect add --set-default`, so `-n` isn't needed. Since 1.31.0, a directory that was deployed before redeploys to its previous target. If you still get a traceback here on 1.33 or later, please reopen with the command and output.

### #858 (completed)

> 🤖 This shipped in 1.32.0 (#859). `rsconnect login <server> --name <nick> --no-wait` and `rsconnect add --connect-cloud --account <acct> --name <nick> --no-wait` start the device-code flow, print the verification URL and user code as JSON, and exit. `rsconnect login --name <nick> --finish [--timeout 120]` (or `rsconnect add --connect-cloud --name <nick> --finish`) completes the login later.
>
> - Pending state is stored with owner-only permissions.
> - Running start again while the code is valid returns the same code.
> - Results carry a `status` of `pending` or `done`.
> - The device code itself is never printed.
>
> Resumable login requires POSIX (Linux or macOS). This should let the Cowork helper scripts drop the private-function calls. If something in your workflow still needs the internals, please reopen with details.
