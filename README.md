# The rsconnect-python Library

This package is a library used by the [`rsconnect-jupyter`](https://github.com/rstudio/rsconnect-jupyter)
package to deploy Jupyter notebooks to RStudio Connect. It contains a full deployment
API so can also be used by other Python-based deployment tools. Other types of content
supported by RStudio Connect may also be deployed by this package, including WSGi-style
APIs and Dash applications.

> **Important:** Dash support in RStudio Connect is currently in beta. You should not
> rely on it for deployments in production.

A command-line deployment tool is also provided that can be used directly to deploy
Jupyter notebooks, Python APIs and apps. Content types not directly supported by the
CLI can also be deployed if they include a prepared `manifest.json` file. See
["Deploying R or Other Content"](#deploying-r-or-other-content) for details.

## Deploying Python Content to RStudio Connect

In addition to various kinds of R content, RStudio Connect also supports the
deployment of Jupyter notebooks, Python APIs (such as `flask`-based) and apps (such
as Dash). Much like deploying R content to RStudio Connect, there are some
caveats to understand when replicating your environment on the RStudio Connect server:

RStudio Connect insists on matching <MAJOR.MINOR> versions of Python. For example,
a server with only Python 3.5 installed will fail to match content deployed with
Python 3.4. Your administrator may also enable exact Python version matching which
will be stricter and require matching major, minor, and patch versions. For more
information see the [RStudio Connect Admin Guide chapter titled Python Version
Matching](https://docs.rstudio.com/connect/admin/python.html#python-version-matching).

### Installation

To install `rsconnect-python` from this repository:

```bash
git clone https://github.com/rstudio/rsconnect-python
cd rsconnect-python
python setup.py install
```

To install the current version directly from pip:

```bash
pip install rsconnect-python
```

### Using the rsconnect CLI

Here's an example command that deploys a Jupyter notebook to RStudio Connect.

```bash
rsconnect deploy notebook \
	--server https://my.connect.server:3939 \
	--api-key my-api-key \
	my-notebook.ipynb
```

> **Note:** The examples here use long command line options, but there are short
> options (`-s`, `-k`, etc.) available also. Run `rsconnect deploy notebook --help`
> for details.

### Setting up `rsconnect` CLI auto-completion

If you would like to use your shell's tab completion support with the `rsconnect`
command, use the command below for the shell you are using.

#### `bash`

If you are using the `bash` shell, use this to enable tab completion.

```bash
#~/.bashrc
eval "$(_RSCONNECT_COMPLETION=source rsconnect)"
```

#### `zsh`

If you are using the `zsh` shell, use this to enable tab completion.

```zsh
#~/.zshrc
eval "$(_RSCONNECT_COMPLETION=source_zsh rsconnect)"
```

If you get `command not found: compdef`, you need to add the following lines to your 
`.zshrc` before the completion setup:

```zsh
#~/.zshrc
autoload -Uz compinit
compinit
```

### Managing Server Information

The information used by the `rsconnect` command to communicate with an RStudio Connect
server can be tedious to repeat on every command.  To help, the CLI supports the idea
of saving this information, making it usable by a simple nickname.

> **Important:** One item of information saved is the API key used to authenticate with
> RStudio Connect.  Although the file where this information is saved is marked as
> accessible by the owner only, it's important to remember that the key is present
> in the file as plain text so care must be taken to prevent any unauthorized access
> to the server information file.

#### TLS Support and RStudio Connect

Usually, an RStudio Connect server will be set up to be accessed in a secure manner,
using the `https` protocol rather than simple `http`.  If RStudio Connect is set up
with a self-signed certificate, you will need to include the `--insecure` flag on
all commands.  If RStudio Connect is set up to require a client-side certificate chain,
you will need to include the `--cacert` option that points to your certificate
authority (CA) trusted certificates file.  Both of these options can be saved along
with the URL and API Key for a server.

> **Note:** When certificate information is saved for the server, the specified file
> is read and its _contents_ are saved under the server's nickname.  If the CA file's
> contents are ever changed, you will need to add the server information again.

See the [Network Options](#network-options) section for more details about these options.

#### Remembering Server Information

Use the `add` command to store information about an RStudio Connect server:

```bash
rsconnect add \
	--api-key my-api-key \
	--server https://my.connect.server:3939 \
	--name myserver
```

> **Note:** The `rsconnect` CLI will verify that the serve URL and API key
> are valid.  If either is found not to be, no information will be saved.

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

You can verify that a URL refers to a running instance of RStudio Connect by using
the `details` command:

```bash
rsconnect details --server https://my.connect.server:3939
```

In this form, `rsconnect` will only tell you whether the URL given does, in fact, refer
to a running RStudio Connect instance.  If you include a valid API key:

```bash
rsconnect details --server https://my.connect.server:3939 --api-key my-api-key
```

the tool will provide the version of RStudio Connect (if the server is configured to
divulge that information) and environmental information including versions of Python
that are installed on the server.

You can also use nicknames with the `details` command if you want to verify that the
stored information is still valid.

### Notebook Deployment Options

There are a variety of options available to you when deploying a Jupyter notebook to
RStudio Connect.

#### Including Extra Files

You can include extra files in the deployment bundle to make them available when your
notebook is run by the RStudio Connect server. Just specify them on the command line
after the notebook file:

```bash
rsconnect deploy notebook my-notebook.ipynb data.csv
```

#### Package Dependencies

If a `requirements.txt` file exists in the same directory as the notebook file, it will
be included in the bundle. It must specify the package dependencies needed to execute
the notebook. RStudio Connect will reconstruct the Python environment using the
specified package list.

If there is no `requirements.txt` file or the `--force-generate` option is specified,
the package dependencies will be determined from the current Python environment, or
from an alternative Python executable specified via the `--python` option or via the
`RETICULATE_PYTHON` environment variable:

```bash
rsconnect deploy notebook --python /path/to/python my-notebook.ipynb
```

You can see the packages list that will be included by running `pip freeze` yourself,
ensuring that you use the same Python that you use to run your Jupyter Notebook:

```bash
/path/to/python -m pip freeze
```

#### Static (Snapshot) Deployment

By default, `rsconnect` deploys the original notebook with all its source code. This
enables the RStudio Connect server to re-run the notebook upon request or on a schedule.

If you just want to publish an HTML snapshot of the notebook, you can use the `--static`
option. This will cause `rsconnect` to execute your notebook locally to produce the HTML
file, then publish the HTML file to the RStudio Connect server:

```bash
rsconnect deploy notebook --static my-notebook.ipynb
```

### Creating a Manifest for Future Deployment

You can create a `manifest.json` file for a Jupyter Notebook, then use that manifest
in a later deployment.  Use the `write-manifest` command to do this.

The `write-manifest` command will also create a `requirements.txt` file, if it does
not already exist or the `--force-generate` option is specified. It will contain the
package dependencies from the current Python environment, or from an alternative
Python executable specified in the `--python` option or via the `RETICULATE_PYTHON`
environment variable.

Here is an example of the `write-manifest` command:

```bash
rsconnect write-manifest notebook my-notebook.ipynb
```

> **Note:** Manifests for static (pre-rendered) notebooks cannot be created.

### API/Application Deployment Options

There are a variety of options available to you when deploying a Python WSGi-style
API or Dash application.  All options below apply equally to `api` and `dash`
sub-commands.

#### Including Extra Files

You can include extra files in the deployment bundle to make them available when your
API or application is run by the RStudio Connect server. Just specify them on the
command line after the API or application directory:

```bash
rsconnect deploy api flask-api/ data.csv
```

Since deploying an API or application starts at a directory level, there will be times
when some files under that directory subtree should not be included in the deployment
or manifest.  Use the `--exclude` option to specify files to exclude.  An exclusion may
be a glob pattern and the `--exclude` option may be repeated.

```bash
rsconnect deploy dash --exclude "workfiles/*" dash-app/ data.csv
```

You should always quote a glob pattern so that it will be passed to `rsconnect` as-is
instead of letting the shell expand it.  If a file is specifically listed as an extra
file that also matches an exclusion pattern, the file will still be included in the
deployment (i.e., extra files trumps exclusions).

#### Package Dependencies

If a `requirements.txt` file exists in the API/application directory, it will be
included in the bundle. It must specify the package dependencies needed to execute
the API or application. RStudio Connect will reconstruct the Python environment using
the specified package list.

If there is no `requirements.txt` file or the `--force-generate` option is specified,
the package dependencies will be determined from the current Python environment, or
from an alternative Python executable specified via the `--python` option or via the
`RETICULATE_PYTHON` environment variable:

```bash
rsconnect deploy api --python /path/to/python my-api/
```

You can see the packages list that will be included by running `pip freeze` yourself,
ensuring that you use the same Python that you use to run your API or application:

```bash
/path/to/python -m pip freeze
```

### Creating a Manifest for Future Deployment

You can create a `manifest.json` file for an API or application, then use that
manifest in a later deployment.  Use the `write-manifest` command to do this.

The `write-manifest` command will also create a `requirements.txt` file, if it does
not already exist or the `--force-generate` option is specified. It will contain
the package dependencies from the current Python environment, or from an alternative
Python executable specified in the `--python` option or via the `RETICULATE_PYTHON`
environment variable.

Here is an example of the `write-manifest` command:

```bash
rsconnect write-manifest api my-api/
```

### Deploying R or Other Content

You can deploy other content that has an existing RStudio Connect `manifest.json`
file. For example, if you download and unpack a source bundle from RStudio Connect,
you can deploy the resulting directory. The options are similar to notebook or
API/application deployment; see `rsconnect deploy manifest --help` for details.

Here is an example of the `deploy manifest` command:

```bash
rsconnect deploy manifest /path/to/manifest.json
```

> **Note:** In this case, the existing content is deployed as-is. Python environment
> inspection and notebook pre-rendering, if needed, are assumed to be done already
> and represented in the manifest.

The argument to `deploy manifest` may also be a directory so long as that directory
contains a `manifest.json` file.

If you have R content but don't have a `manifest.json` file, you can use the RStudio
IDE to create the manifest. See the help for the `rsconnect::writeManifest` R function:

```r
install.packages('rsconnect')
library(rsconnect)
?rsconnect::writeManifest
```

### Options for All Types of Deployments

These options apply to any type of content deployment.

#### Title

The title of the deployed content is, by default, derived from the filename. For
example, if you deploy `my-notebook.ipynb`, the title will be `my-notebook`. To change
this, use the `--title` option:

```
rsconnect deploy notebook --title "My Notebook" my-notebook.ipynb
```

When using `rsconnect deploy api` or `rsconnect deploy dash`, the title is derived
from the directory containing the API or application.

When using `rsconnect deploy manifest`, the title is derived from the primary
filename referenced in the manifest.

### Network Options

When specifying information that `rsconnect` needs to be able to interact with RStudio
Connect, you can tailor how transport layer security is performed.

#### TLS/SSL Certificates

RStudio Connect servers can be configured to use TLS/SSL. If your server's certificate
is trusted by your Jupyter Notebook server, API client or user's browser, then you
don't need to do anything special. You can test this out with the `details` command:

```bash
rsconnect details --api-key my-api-key --server https://my.connect.server:3939
```

If this fails with a TLS Certificate Validation error, then you have two options.

* Provide the Root CA certificate that is at the root of the signing chain for your
  RStudio Connect server. This will enable `rsconnect` to securely validate the
  server's TLS certificate.

	```bash
	rsconnect details \
		--api-key my-api-key \
		--server https://my.connect.server:3939 \
		--cacert /path/to/certificate.pem
	```

* RStudio Connect is in "insecure mode". This disables TLS certificate verification,
  which results in a less secure connection.

	```bash
	rsconnect add \
		--api-key my-api-key \
		--server https://my.connect.server:3939 \
		--insecure
	```

Once you work out the combination of options that allow you to successfully work with
an instance of RStudio Connect, you'll probably want to use the `add` command to have
`rsconnect` remember those options and allow you to just use a nickname.

### Updating a Deployment

If you deploy a file again to the same server, `rsconnect` will update the previous
deployment. This means that you can keep running `rsconnect deploy notebook my-notebook.ipynb`
as you develop new versions of your notebook. The same applies to other Python content
types.

#### Forcing a New Deployment

To bypass this behavior and force a new deployment, use the `--new` option:

```bash
rsconnect deploy dash --new my-app/
```

#### Updating a Different Deployment

If you want to update an existing deployment but don't have the saved deployment data,
you can provide the app's numeric ID or GUID on the command line:

```bash
rsconnect deploy notebook --app-id 123456 my-notebook.ipynb
```

You must be the owner of the target deployment, or a collaborator with permission to
change the content. The type of content (static notebook, notebook with source code,
API, or application) must match the existing deployment.

> **Note:** There is no confirmation required to update a deployment. If you do so
> accidentally, use the "Source Versions" dialog in the RStudio Connect dashboard to
> activate the previous version and remove the erroneous one.

##### Finding the App ID

The App ID associated with a piece of content you have previously deployed from the
`rsconnect` command line interface can be found easily by querying the deployment
information using the `info` command. For more information, see the
[Showing the Deployment Information](#showing-the-deployment-information) section.

If the content was deployed elsewhere or `info` does not return the correct App ID,
but you can open the content on RStudio Connect, find the content and open it in a
browser. The URL in your browser's location bar will contain `#/apps/NNN` where `NNN`
is your App ID. The GUID identifier for the app may be found on the **Info** tab for
the content in the RStudio Connect UI.

#### Showing the Deployment Information

You can see the information that the `rsconnect` command has saved for the most recent
deployment with the `info` command:

```bash
rsconnect info my-notebook.ipynb
```

If you have deployed to multiple servers, the most recent deployment information for
each server will be shown. This command also displays the path to the file where the
deployment data is stored.

## Stored Information Files

Stored information files are stored in a platform-specific directory:

| Platform | Location                                                           |
| -------- | ------------------------------------------------------------------ |
| Mac      | `$HOME/Library/Application Support/rsconnect-python/`              |
| Linux    | `$HOME/.rsconnect-python/` or `$XDG_CONFIG_HOME/rsconnect-python/` |
| Windows  | `$APPDATA/rsconnect-python`                                        |

Remembered server information is stored in the `servers.json` file in that directory.

### Deployment Data

After a deployment is completed, information about the deployment is saved
to enable later redeployment. This data is stored alongside the deployed file,
in an `rsconnect-python` subdirectory, if possible. If that location is not writable
during deployment, then the deployment data will be stored in the global configuration
directory specified above.
