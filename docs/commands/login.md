# `rsconnect login`

Use `login` to authenticate with Posit Connect through OAuth. The command normally opens a browser and waits for approval. If the shell must return before approval, start device authentication and finish it in separate commands.

The `--identity-token` and `--identity-token-file` options accept OpenID Connect (OIDC) identity tokens for token exchange.

## Start device authentication

Pass the server base URL, a nickname, and `--no-wait`. This option selects device authentication without requiring `--use-device-code`:

```{.bash filename="Terminal"}
rsconnect login https://connect.example.com --name myserver --no-wait
```

The command exits with JSON that includes the approval URL, the user code, and the duration until expiration:

```json
{
  "status": "pending",
  "name": "myserver",
  "server": "https://connect.example.com",
  "verification_uri": "https://connect.example.com/activate",
  "user_code": "ABCD-EFGH",
  "expires_in": 900
}
```

Show the user `verification_uri` and `user_code` so they can approve the request. The JSON does not include the secret device code or any token.

If a valid pending login already exists for the same server and nickname, `login --no-wait` reuses it.
Starting a login for a different target with that nickname fails.
The command stores pending logins under its configuration directory. Files use owner-only permissions on POSIX.
Resumable device login requires a POSIX system such as Linux or macOS. Use a private configuration directory.
Existing blocking login remains available on Windows.

Pending state contains device codes and token checkpoints in plaintext, even when final credentials use a keyring.
Owner-only permissions restrict ordinary access to your operating-system account; processes running as that account and backups can still read it.
Finish pending logins promptly. Abandoned state has no background cleanup, and deleting local state does not revoke an issued token.
Use HTTPS with certificate verification and keep the configuration directory private and outside your application directory.

## Finish device authentication

After the user approves the request, finish the login by naming the saved nickname:

```{.bash filename="Terminal"}
rsconnect login --name myserver --finish --timeout 120
```

The timeout bounds the entire finish invocation. The command prints JSON with `status` set to `pending` or `done`.
Slowly streamed response headers and bodies use the remaining timeout budget. An operating-system DNS lookup can still outlast it.
`--timeout` accepts any positive integer and defaults to 120 seconds. Use it only with `--finish`.

Finish selects the pending login by `--name`, so omit the `SERVER` argument. It accepts `--name`, `--finish`, optional `--timeout`, and optional verbosity flags.
Do not pass the server URL or any other start option.

A pending result exits successfully so callers can parse the JSON. A transient pending result remains available for another finish attempt.
Denied, expired, or rejected authorization requests exit with status 1 and remove the pending request.
Concurrent login operations for the same nickname serialize their state updates.
If finish exhausts its timeout waiting for another operation, it reports `pending` with `server: null`.

Start reports contain `status`, `name`, `server`, `verification_uri`, `user_code`, and `expires_in`.
Finish reports contain `status`, `name`, and `server`. Errors exit with status 1 and print diagnostics to stderr.
Invalid command syntax exits with status 2. Use `-v` or `-vv` for diagnostics on stderr; stdout remains reserved for the JSON result.

Without `--no-wait` or `--finish`, `login` keeps its existing blocking behavior and options.

::: mkdocs-click
    :module: rsconnect.main
    :command: login
