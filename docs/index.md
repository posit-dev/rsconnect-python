# `rsconnect`

This package provides a (command-line interface) CLI for interacting
with and deploying to Posit Connect. Many types of content supported by Posit
Connect may be deployed by this package, including WSGI-style APIs, Dash, Streamlit,
Gradio, Bokeh, and Panel applications.

Content types not directly supported by the CLI may also be deployed if they include a
prepared `manifest.json` file. See ["Deploying R or Other
Content"](#deploying-r-or-other-content) for details.


### Installation

To install `rsconnect-python` from PYPI, you may use any python package manager such as
pip:

```bash
pip install rsconnect-python
```

You may also build and install a wheel directly from a repository clone:

```bash
pip install git+https://github.com/posit-dev/rsconnect-python.git
```

### Using the rsconnect CLI

Log in to Posit Connect, then deploy a Jupyter notebook:

```bash
rsconnect login https://connect.example.org --name myserver
rsconnect deploy notebook my-notebook.ipynb
```

> **Note**
> The examples here use long command line options, but there are short
> options available also. Run `rsconnect deploy notebook --help`
> for details.

### Setting up `rsconnect` CLI auto-completion

If you would like to use your shell's tab completion support with the `rsconnect`
command, use the command below for the shell you are using.

#### `bash`

If you are using the `bash` shell, use this to enable tab completion.

```bash
#~/.bashrc
eval "$(_RSCONNECT_COMPLETE=source rsconnect)"
```

#### `zsh`

If you are using the `zsh` shell, use this to enable tab completion.

```zsh
#~/.zshrc
eval "$(_RSCONNECT_COMPLETE=source_zsh rsconnect)"
```

If you get `command not found: compdef`, you need to add the following lines to your
`.zshrc` before the completion setup:

```zsh
#~/.zshrc
autoload -Uz compinit
compinit
```

### Managing Server Information

The CLI can save Posit Connect server information under a nickname, so you don't
need to repeat it on every command.

#### Remembering Server Information

Use `login` to authenticate and save a server:

```bash
rsconnect login https://connect.example.org --name myserver
```

Browser login requires Posit Connect 2026.02.0 or later. In Posit Workbench,
remote containers, or other sessions where the browser cannot reach the CLI's
local callback, use `--use-device-code`; this requires Connect 2026.06.0 or later.
The `--no-wait` device flow also requires Connect 2026.06.0 or later.

For automation, `--identity-token` and `--identity-token-file` require Connect
2026.08.0 or later, or Connect 2026.02.0 or later with identity federation.

Login sets the server as the default unless `--no-set-default` is supplied.
Later commands can omit `--name`, or select a saved server by nickname:

```bash
rsconnect deploy notebook --name myserver my-notebook.ipynb
```

See the [`login`](commands/login.md), [`logout`](commands/logout.md), and
[`token`](commands/token.md) references for more options.

As an alternative for servers older than Connect 2026.02.0 or automation that
cannot use identity tokens, [create an API key](https://docs.posit.co/connect/user/api-keys/)
and save it with `add`:

```bash
rsconnect add \
    --server https://connect.example.org \
    --api-key my-api-key \
    --name myserver
```

You can also pass `--api-key` or set `CONNECT_API_KEY` on individual commands.
The CLI verifies the server URL and API key before saving them.

> **Warning**
> Saved API keys are stored as plain text in the server information file.
> The file is accessible only by its owner; protect it from unauthorized access.
> See [Stored Information Files](deploying.md#stored-information-files) for
> OAuth token storage.

#### Listing Server Information

You can see the list of saved server information with:

```
rsconnect list
```

#### Removing Server Information

You can remove information about a server with:

```
rsconnect remove --name myserver
```

Removing may be done by its nickname (`--name`) or URL (`--server`).

### Verifying Server Information

You can verify that a URL refers to a running instance of Posit Connect by using
the `details` command:

```bash
rsconnect details --server https://connect.example.org
```

In this form, `rsconnect` will only tell you whether the URL given does, in fact, refer
to a running Posit Connect instance. If you include a valid API key:

```bash
rsconnect details --server https://connect.example.org --api-key my-api-key
```

the tool will provide the version of Posit Connect (if the server is configured to
divulge that information) and environmental information including versions of Python
that are installed on the server.

You can also use nicknames with the `details` command if you want to verify that the
stored information is still valid.


### Network Options

When specifying information that `rsconnect` needs to be able to interact with Posit
Connect, you can tailor how transport layer security is performed.

#### TLS/SSL Certificates

Posit Connect servers can be configured to use TLS/SSL. If your server's certificate
is trusted by your Jupyter Notebook server, API client or user's browser, then you
don't need to do anything special. You can test this out with the `details` command:

```bash
rsconnect details \
    --api-key my-api-key \
    --server https://connect.example.org:3939
```

If this fails with a TLS Certificate Validation error, then you have two options.

* Provide the Root CA certificate that is at the root of the signing chain for your
  Posit Connect server. This will enable `rsconnect` to securely validate the
  server's TLS certificate.

    ```bash
    rsconnect details \
        --api-key my-api-key \
        --server https://connect.example.org \
        --cacert /path/to/certificate.pem
    ```

* Posit Connect is in "insecure mode". This disables TLS certificate verification,
  which results in a less secure connection.

    ```bash
    rsconnect add \
        --api-key my-api-key \
        --server https://connect.example.org \
        --insecure
    ```

Once you work out the combination of options that allow you to successfully work with
an instance of Posit Connect, you'll probably want to use the `add` command to have
`rsconnect` remember those options and allow you to just use a nickname.
