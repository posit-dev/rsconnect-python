# `rsconnect`

This package provides a (command-line interface) CLI for interacting
with and deploying to Posit Connect. Many types of content supported by Posit
Connect may be deployed by this package, including WSGI-style APIs, Dash, Streamlit,
Gradio, Bokeh, and HoloViz Panel applications.

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

Here's an example command that deploys a Jupyter notebook to Posit Connect.

```bash
rsconnect deploy notebook \
    --server https://connect.example.org \
    --api-key my-api-key \
    my-notebook.ipynb
```

> **Note**
> The examples here use long command line options, but there are short
> options (`-s`, `-k`, etc.) available also. Run `rsconnect deploy notebook --help`
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

The information used by the `rsconnect` command to communicate with a Posit Connect
server can be tedious to repeat on every command. To help, the CLI supports the idea
of saving this information, making it usable by a simple nickname.

> **Warning**
> One item of information saved is the API key used to authenticate with
> Posit Connect. Although the file where this information is saved is marked as
> accessible by the owner only, it's important to remember that the key is present
> in the file as plain text so care must be taken to prevent any unauthorized access
> to the server information file.

#### Remembering Server Information

Use the `add` command to store information about a Posit Connect server:

```bash
rsconnect add \
    --api-key my-api-key \
    --server https://connect.example.org \
    --name myserver
```

> **Note**
> The `rsconnect` CLI will verify that the serve URL and API key
> are valid. If either is found not to be, no information will be saved.

If any of the access information for the server changes, simply rerun the
`add` command with the new information and it will replace the original
information.

Once the server's information is saved, you can refer to it by its nickname:

```bash
rsconnect deploy notebook --name myserver my-notebook.ipynb
```

If there is information for only one server saved, this will work too:

```bash
rsconnect deploy notebook my-notebook.ipynb
```

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
