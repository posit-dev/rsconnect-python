# rsconnect login


Authenticate with a Posit Connect server using OAuth 2.1. This opens a browser for interactive login (or uses `--use-device-code` for headless environments). Tokens are stored in the system keyring when available, with fallback to the local credential store.


``` bash
rsconnect login [OPTIONS] [SERVER]
```


Alternatively, pass `--identity-token` (or `--identity-token-file`) with an OIDC identity token, such as a GitHub Actions OIDC token, to exchange it for a short-lived Connect API key without interactive login. The resulting API key is saved as the server credential.


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect login [OPTIONS] SERVER

      Authenticate with a Posit Connect server using OAuth 2.1. This opens a
      browser for interactive login (or uses --use-device-code for headless
      environments). Tokens are stored in the system keyring when available, with
      fallback to the local credential store.

      Alternatively, pass --identity-token (or --identity-token-file) with an OIDC
      identity token, such as a GitHub Actions OIDC token, to exchange it for a
      short-lived Connect API key without interactive login. The resulting API key
      is saved as the server credential.

    Options:
      -s, --server TEXT           The URL of the Posit Connect server.
      -n, --name TEXT             Nickname for the server (defaults to server
                                  hostname).
      -i, --insecure              Disable TLS certificate verification.
      -c, --cacert FILE           Path to a trusted CA certificate file for TLS.
      --identity-token TEXT       An OIDC identity token to exchange for a Connect
                                  API key (RFC 8693), instead of interactive OAuth
                                  login. Use '-' to read the token from stdin. May
                                  also be set via the CONNECT_IDENTITY_TOKEN
                                  environment variable.
      --identity-token-file FILE  Path to a file containing an OIDC identity token
                                  to exchange for a Connect API key. May also be
                                  set via the CONNECT_IDENTITY_TOKEN_FILE
                                  environment variable. Prefer this over
                                  --identity-token to avoid exposing the token in
                                  process arguments or CI/CD logs.
      --use-device-code           Use device code flow for headless/non-
                                  interactive environments.
      --client-id TEXT            OAuth client ID (skips Dynamic Client
                                  Registration).
      --no-set-default            Do not mark this server as the default after
                                  login.
      -v, --verbose               Enable verbose output. Use -vv for very verbose
                                  (debug) output.
      --help                      Show this message and exit.


# Arguments


`SERVER: TEXT`  
Optional.


# Options


`-s, --server: TEXT`  
The URL of the Posit Connect server. Environment variable: `CONNECT_SERVER`.

`-n, --name: TEXT`  
Nickname for the server (defaults to server hostname).

`-i, --insecure`  
Disable TLS certificate verification. Environment variable: `CONNECT_INSECURE`.

`-c, --cacert: FILE`  
Path to a trusted CA certificate file for TLS. Environment variable: `CONNECT_CA_CERTIFICATE`.

`--identity-token: TEXT`  
An OIDC identity token to exchange for a Connect API key (RFC 8693), instead of interactive OAuth login. Use '-' to read the token from stdin. May also be set via the CONNECT_IDENTITY_TOKEN environment variable. Environment variable: `CONNECT_IDENTITY_TOKEN`.

`--identity-token-file: FILE`  
Path to a file containing an OIDC identity token to exchange for a Connect API key. May also be set via the CONNECT_IDENTITY_TOKEN_FILE environment variable. Prefer this over `--identity-token` to avoid exposing the token in process arguments or CI/CD logs. Environment variable: `CONNECT_IDENTITY_TOKEN_FILE`.

`--use-device-code`  
Use device code flow for headless/non`-i`nteractive environments.

`--client-id: TEXT`  
OAuth client ID (skips Dynamic Client Registration).

`--no-set-default`  
Do not mark this server as the default after login.

`-v, --verbose: INTEGER RANGE = 0`  
Enable verbose output. Use `-v`v for very verbose (debug) output.
