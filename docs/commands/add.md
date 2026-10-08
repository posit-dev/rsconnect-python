# `rsconnect add`

Use `add --connect-cloud` to authenticate with Posit Connect Cloud. The command normally waits for browser approval. If the shell must return before approval, start device authentication and finish it separately.

Both `rsconnect add` and its `rsconnect server add` alias support these options.

## Start Connect Cloud authentication

Pass the account and nickname, then add `--no-wait`:

```{.bash filename="Terminal"}
rsconnect add --connect-cloud --account team --name cloud --no-wait
```

The command exits with JSON that includes the approval URL, the user code, and the duration until expiration. Show the user `verification_uri` and `user_code` so they can approve the request. The JSON does not include the secret device code or any token.

If a valid pending login already exists for the same account and nickname, the command reuses it.
Starting a login for a different target with that nickname fails.
The command stores pending logins under its configuration directory. Files use owner-only permissions on POSIX.
Resumable device login requires a POSIX system such as Linux or macOS. Use a private configuration directory.
Existing blocking login remains available on Windows.

Pending state contains device codes and token checkpoints in plaintext, even when final credentials use a keyring.
Owner-only permissions restrict ordinary access to your operating-system account; processes running as that account and backups can still read it.
Finish pending logins promptly. Abandoned state has no background cleanup, and deleting local state does not revoke an issued token.
Use HTTPS with certificate verification and keep the configuration directory private and outside your application directory.

Finish the login after the user approves:

```{.bash filename="Terminal"}
rsconnect add --connect-cloud --name cloud --finish --timeout 120
```

The timeout bounds the entire finish invocation, including account lookup.
Slowly streamed response headers and bodies use the remaining timeout budget. An operating-system DNS lookup can still outlast it.
Finish reuses the OAuth client selected when the login started.
The command prints JSON with `status` set to `pending` or `done`. Finish requires `--connect-cloud` and `--name`.
It accepts `--connect-cloud`, `--name`, `--finish`, optional `--timeout`, and optional verbosity flags.

Do not pass account, server, TLS, identity, client, or default options. `--timeout` accepts any positive integer and defaults to 120 seconds. Use it only with `--finish`.

A pending result exits successfully so callers can parse the JSON. A transient pending result remains available for another finish attempt.
Denied, expired, or rejected authorization requests exit with status 1 and remove the pending request.
A completed lookup that cannot find the requested account also removes the request, so you can start again with a corrected account name.
Concurrent login operations for the same nickname serialize their state updates.
If finish exhausts its timeout waiting for another operation, it reports `pending` with `server: null`.

Start reports contain `status`, `name`, `server`, `verification_uri`, `user_code`, and `expires_in`.
Pending finish reports contain `status`, `name`, and `server`. Completed finish reports also contain `account`.
Errors exit with status 1 and print diagnostics to stderr. Invalid command syntax exits with status 2.
Use `-v` or `-vv` for diagnostics on stderr; stdout remains reserved for the JSON result.

The `rsconnect server add` alias accepts the same commands:

```{.bash filename="Terminal"}
rsconnect server add --connect-cloud --account team --name cloud --no-wait
rsconnect server add --connect-cloud --name cloud --finish --timeout 120
```

Without `--no-wait` or `--finish`, `add` keeps its existing blocking behavior and options.

::: mkdocs-click
    :module: rsconnect.main
    :command: add
    :prog_name: rsconnect server add
