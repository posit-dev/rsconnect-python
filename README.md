# [rsconnect-python](https://docs.posit.co/rsconnect-python)

The command-line interface for [Posit Connect](https://docs.posit.co/connect/) and [Posit Connect Cloud](https://connect.posit.cloud).

## Installation

### uv

```bash
uv tool install rsconnect-python
```

### pipx

```bash
pipx install rsconnect-python
```

### into your project

```bash
python -m pip install rsconnect-python
```

## Usage with Posit Connect

Log in to your Posit Connect server:

```bash
rsconnect login https://connect.example.com --name production
```

Deploy your application:

```bash
rsconnect deploy shiny app.py --title "my shiny app"
```

Browser login requires Posit Connect 2026.02.0 or later. In remote containers,
or other sessions where the browser cannot reach the CLI's local callback, use
`--use-device-code` with Connect 2026.06.0 or later.

For older servers, or automation that cannot use identity tokens, [get an API
key](https://docs.posit.co/connect/user/api-keys/) and store it with
`rsconnect add --server https://connect.example.com --api-key <YOUR-CONNECT-API-KEY> --name production`.
See the [authentication guide](https://docs.posit.co/rsconnect-python/#managing-server-information)
for identity token requirements and other login options.

[Read more about publisher and admin capabilities on the docs site.](https://docs.posit.co/rsconnect-python)

## Usage with Posit Connect Cloud

Store your credentials, logging in to [Posit Connect Cloud](https://connect.posit.cloud) through your browser:

```bash
rsconnect add --connect-cloud --account <YOUR-ACCOUNT-NAME> --name cloud
```

Deploy your application:

```bash
rsconnect deploy shiny app.py --name cloud --title "my shiny app"
```

For non-interactive use such as CI, pass client credentials with
`--client-id` and `--client-secret`, or the `CONNECT_CLOUD_CLIENT_ID` and
`CONNECT_CLOUD_CLIENT_SECRET` environment variables.

## Contributing

[Contributing docs](./CONTRIBUTING.md)
