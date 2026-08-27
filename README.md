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

[Get an API key from your Posit Connect server](https://docs.posit.co/connect/user/api-keys/) with at least publisher privileges:

Store your credentials:

```bash
rsconnect add --server https://connect.example.com --api-key <YOUR-CONNECT-API-KEY> --name production
```

Deploy your application:

```bash
rsconnect deploy shiny app.py --title "my shiny app"
```

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

For non-interactive use such as CI, pass a service account credential with
`--client-id` and `--client-secret`, or the `CONNECT_CLOUD_CLIENT_ID` and
`CONNECT_CLOUD_CLIENT_SECRET` environment variables.

## Contributing

[Contributing docs](./CONTRIBUTING.md)
