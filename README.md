# The rsconnect-python CLI

!!! warning

    As of version 1.14.0, rsconnect-python requires Python version 3.7 or higher.

This package provides a CLI (command-line interface) for interacting
with and deploying to Posit Connect. This is also used by the
[`rsconnect-jupyter`](https://github.com/rstudio/rsconnect-jupyter) package to deploy
Jupyter notebooks via the Jupyter web console. Many types of content supported by Posit
Connect may be deployed by this package, including WSGI-style APIs, Dash, Streamlit, and
Bokeh applications.

Content types not directly supported by the CLI may also be deployed if they include a
prepared `manifest.json` file. See ["Deploying R or Other
Content"](#deploying-r-or-other-content) for details.


## Deploying Python Content to Posit Connect

Posit Connect supports the deployment of Jupyter notebooks, Python APIs (such as
those based on Flask or FastAPI) and apps (such as Dash, Streamlit, and Bokeh apps).
Much like deploying R
content to Posit Connect, there are some caveats to understand when replicating your
environment on the Posit Connect server:

Posit Connect insists on matching `<MAJOR.MINOR>` versions of Python. For example,
a server with only Python 3.8 installed will fail to match content deployed with
Python 3.7. Your administrator may also enable exact Python version matching which
will be stricter and require matching major, minor, and patch versions. For more
information see the [Posit Connect Admin Guide chapter titled Python Version
Matching](https://docs.posit.co/connect/admin/python.html#python-version-matching).

### Installation

To install `rsconnect-python` from PYPI, you may use any python package manager such as
pip:

```bash
pip install rsconnect-python
```

You may also build and install a wheel directly from a repository clone:

```bash
git clone https://github.com/rstudio/rsconnect-python.git
cd rsconnect-python
pip install pipenv
make deps dist
pip install ./dist/rsconnect_python-*.whl
```

### Using the rsconnect CLI

Here's an example command that deploys a Jupyter notebook to Posit Connect.

```bash
rsconnect deploy notebook \
    --server https://connect.example.org:3939 \
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

> **Important:** One item of information saved is the API key used to authenticate with
> Posit Connect. Although the file where this information is saved is marked as
> accessible by the owner only, it's important to remember that the key is present
> in the file as plain text so care must be taken to prevent any unauthorized access
> to the server information file.

#### TLS Support and Posit Connect

Usually, a Posit Connect server will be set up to be accessed in a secure manner,
using the `https` protocol rather than simple `http`. If Posit Connect is set up
with a self-signed certificate, you will need to include the `--insecure` flag on
all commands. If Posit Connect is set up to require a client-side certificate chain,
you will need to include the `--cacert` option that points to your certificate
authority (CA) trusted certificates file. Both of these options can be saved along
with the URL and API Key for a server.

> **Note:** When certificate information is saved for the server, the specified file
> is read and its _contents_ are saved under the server's nickname. If the CA file's
> contents are ever changed, you will need to add the server information again.

See the [Network Options](#network-options) section for more details about these options.

#### Remembering Server Information

Use the `add` command to store information about a Posit Connect server:

```bash
rsconnect add \
    --api-key my-api-key \
    --server https://connect.example.org:3939 \
    --name myserver
```

> **Note:** The `rsconnect` CLI will verify that the serve URL and API key
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
rsconnect details --server https://connect.example.org:3939
```

In this form, `rsconnect` will only tell you whether the URL given does, in fact, refer
to a running Posit Connect instance. If you include a valid API key:

```bash
rsconnect details --server https://connect.example.org:3939 --api-key my-api-key
```

the tool will provide the version of Posit Connect (if the server is configured to
divulge that information) and environmental information including versions of Python
that are installed on the server.

You can also use nicknames with the `details` command if you want to verify that the
stored information is still valid.

### Notebook Deployment Options

There are a variety of options available to you when deploying a Jupyter notebook to
Posit Connect.

#### Including Extra Files

You can include extra files in the deployment bundle to make them available when your
notebook is run by the Posit Connect server. Just specify them on the command line
after the notebook file:

```bash
rsconnect deploy notebook my-notebook.ipynb data.csv
```

#### Package Dependencies

If a `requirements.txt` file exists in the same directory as the notebook file, it will
be included in the bundle. It must specify the package dependencies needed to execute
the notebook. Posit Connect will reconstruct the Python environment using the
specified package list.

If there is no `requirements.txt` file or the `--force-generate` option is specified,
the package dependencies will be determined from the current Python environment, or
from an alternative Python executable specified via the `--python` option:

```bash
rsconnect deploy notebook --python /path/to/python my-notebook.ipynb
```

You can see the packages list that will be included by running `pip list --format=freeze` yourself,
ensuring that you use the same Python that you use to run your Jupyter Notebook:

```bash
/path/to/python -m pip list --format=freeze
```

#### Static (Snapshot) Deployment

By default, `rsconnect` deploys the original notebook with all its source code. This
enables the Posit Connect server to re-run the notebook upon request or on a schedule.

If you just want to publish an HTML snapshot of the notebook, you can use the `--static`
option. This will cause `rsconnect` to execute your notebook locally to produce the HTML
file, then publish the HTML file to the Posit Connect server:

```bash
rsconnect deploy notebook --static my-notebook.ipynb
```

### Creating a Manifest for Future Deployment

You can create a `manifest.json` file for a Jupyter Notebook, then use that manifest
in a later deployment. Use the `write-manifest` command to do this.

The `write-manifest` command will also create a `requirements.txt` file, if it does
not already exist or the `--force-generate` option is specified. It will contain the
package dependencies from the current Python environment, or from an alternative
Python executable specified in the `--python` option.

Here is an example of the `write-manifest` command:

```bash
rsconnect write-manifest notebook my-notebook.ipynb
```

> **Note:** Manifests for static (pre-rendered) notebooks cannot be created.

### API/Application Deployment Options

You can deploy a variety of APIs and applications using sub-commands of the
`rsconnect deploy` command.

* `api`: WSGI-compliant APIs such as Flask and packages based on Flask
* `fastapi`: ASGI-compliant APIs (FastAPI, Quart, Sanic, and Falcon)
* `dash`: Python Dash apps
* `streamlit`: Streamlit apps
* `bokeh`: Bokeh server apps

All options below apply equally to the `api`, `fastapi`, `dash`, `streamlit`,
and `bokeh` sub-commands.

#### Including Extra Files

You can include extra files in the deployment bundle to make them available when your
API or application is run by the Posit Connect server. Just specify them on the
command line after the API or application directory:

```bash
rsconnect deploy api flask-api/ data.csv
```

Since deploying an API or application starts at a directory level, there will be times
when some files under that directory subtree should not be included in the deployment
or manifest. Use the `--exclude` option to specify files or directories to exclude.

```bash
rsconnect deploy dash --exclude dash-app-venv --exclude TODO.txt dash-app/
```

You can exclude a directory by naming it:
```bash
rsconnect deploy dash --exclude dash-app-venv --exclude output/ dash-app/
```

The `--exclude` option may be repeated, and may include a glob pattern.
You should always quote a glob pattern so that it will be passed to `rsconnect` as-is
instead of letting the shell expand it. If a file is specifically listed as an extra
file that also matches an exclusion pattern, the file will still be included in the
deployment (i.e., extra files take precedence).

```bash
rsconnect deploy dash --exclude dash-app-venv --exclude “*.txt” dash-app/
```

The following shows an example of an extra file taking precedence:

```bash
rsconnect deploy dash --exclude “*.csv” dash-app/ important_data.csv
```

Some directories are excluded by default, to prevent bundling and uploading files that are not needed or might interfere with the deployment process:

```
.Rproj.user
.env
.git
.svn
.venv
__pycache__
env
packrat
renv
rsconnect-python
rsconnect
venv
```

Any directory that appears to be a Python virtual environment (by containing
`bin/python`) will also be excluded.


#### Package Dependencies

If a `requirements.txt` file exists in the API/application directory, it will be
included in the bundle. It must specify the package dependencies needed to execute
the API or application. Posit Connect will reconstruct the Python environment using
the specified package list.

If there is no `requirements.txt` file or the `--force-generate` option is specified,
the package dependencies will be determined from the current Python environment, or
from an alternative Python executable specified via the `--python` option:

```bash
rsconnect deploy api --python /path/to/python my-api/
```

You can see the packages list that will be included by running `pip list --format=freeze` yourself,
ensuring that you use the same Python that you use to run your API or application:

```bash
/path/to/python -m pip list --format=freeze
```

### Creating a Manifest for Future Deployment

You can create a `manifest.json` file for an API or application, then use that
manifest in a later deployment. Use the `write-manifest` command to do this.

The `write-manifest` command will also create a `requirements.txt` file, if it does
not already exist or the `--force-generate` option is specified. It will contain
the package dependencies from the current Python environment, or from an alternative
Python executable specified in the `--python` option.

Here is an example of the `write-manifest` command:

```bash
rsconnect write-manifest api my-api/
```

### Deploying R or Other Content

You can deploy other content that has an existing Posit Connect `manifest.json`
file. For example, if you download and unpack a source bundle from Posit Connect,
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

When using `rsconnect deploy api`, `rsconnect deploy fastapi`, `rsconnect deploy dash`,
`rsconnect deploy streamlit`, or `rsconnect deploy bokeh`, the title is derived from the directory
containing the API or application.

When using `rsconnect deploy manifest`, the title is derived from the primary
filename referenced in the manifest.

### Environment Variables
You can set environment variables during deployment. Their names and values will be
passed to Posit Connect during deployment so you can use them in your code.

For example, if `notebook.ipynb` contains
```python
print(os.environ["MYVAR"])
```

You can set the value of `MYVAR` that will be set when your code runs in Posit Connect
using the `-E/--environment` option:
```bash
rsconnect deploy notebook --environment MYVAR='hello world' notebook.ipynb
```

To avoid exposing sensitive values on the command line, you can specify
a variable without a value. In this case, it will use the value from the
environment in which rsconnect-python is running:
```bash
export SECRET_KEY=12345

rsconnect deploy notebook --environment SECRET_KEY notebook.ipynb
```

If you specify environment variables when updating an existing deployment,
new values will be set for the variables you provided. Other variables will
remain unchanged. If you don't specify any variables, all of the existing
variables will remain unchanged.

Environment variables are set on the content item before the content bundle
is uploaded and deployed. If the deployment fails, the new environment variables
will still take effect.

### Network Options

When specifying information that `rsconnect` needs to be able to interact with Posit
Connect, you can tailor how transport layer security is performed.

#### TLS/SSL Certificates

Posit Connect servers can be configured to use TLS/SSL. If your server's certificate
is trusted by your Jupyter Notebook server, API client or user's browser, then you
don't need to do anything special. You can test this out with the `details` command:

```bash
rsconnect details --api-key my-api-key --server https://connect.example.org:3939
```

If this fails with a TLS Certificate Validation error, then you have two options.

* Provide the Root CA certificate that is at the root of the signing chain for your
  Posit Connect server. This will enable `rsconnect` to securely validate the
  server's TLS certificate.

    ```bash
    rsconnect details \
        --api-key my-api-key \
        --server https://connect.example.org:3939 \
        --cacert /path/to/certificate.pem
    ```

* Posit Connect is in "insecure mode". This disables TLS certificate verification,
  which results in a less secure connection.

    ```bash
    rsconnect add \
        --api-key my-api-key \
        --server https://connect.example.org:3939 \
        --insecure
    ```

Once you work out the combination of options that allow you to successfully work with
an instance of Posit Connect, you'll probably want to use the `add` command to have
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
> accidentally, use the "Source Versions" dialog in the Posit Connect dashboard to
> activate the previous version and remove the erroneous one.

##### Finding the App ID

The App ID associated with a piece of content you have previously deployed from the
`rsconnect` command line interface can be found easily by querying the deployment
information using the `info` command. For more information, see the
[Showing the Deployment Information](#showing-the-deployment-information) section.

If the content was deployed elsewhere or `info` does not return the correct App ID,
but you can open the content on Posit Connect, find the content and open it in a
browser. The URL in your browser's location bar will contain `#/apps/NNN` where `NNN`
is your App ID. The GUID identifier for the app may be found on the **Info** tab for
the content in the Posit Connect UI.

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

<div style="display:none">
Generated from <code>rsconnect-python {{ rsconnect_python.version }}</code>
</div>

### Hide Jupyter Notebook Input Code Cells

The user can render a Jupyter notebook without its corresponding input code cells by passing the '--hide-all-input' flag through the cli:

```
rsconnect deploy notebook \
    --server https://connect.example.org:3939 \
    --api-key my-api-key \
    --hide-all-input \
    my-notebook.ipynb
```

To selectively hide input cells in a Jupyter notebook, the user needs to follow a two step process:
1. tag cells with the 'hide_input' tag,
2. then pass the ' --hide-tagged-input' flag through the cli:

```
rsconnect deploy notebook \
    --server https://connect.example.org:3939 \
    --api-key my-api-key \
    --hide-tagged-input \
    my-notebook.ipynb
```

By default, rsconnect-python does not install Jupyter notebook related depenencies. These dependencies are installed via rsconnect-jupyter. When the user is using the hide input features in rsconnect-python by itself without rsconnect-jupyter, he/she needs to install the following package depenecies:

```
notebook
nbformat
nbconvert>=5.6.1
```

## Content subcommands

rsconnect-python supports multiple options for interacting with Posit Connect's
`/v1/content` API. Both administrators and publishers can use the content subcommands
to search, download, and rebuild content on Posit Connect without needing to access the
dashboard from a browser.

> **Note:** The `rsconnect content` CLI subcommands are intended to be easily scriptable.
> The default output format is `JSON` so that the results can be easily piped into
> other command line utilities like [`jq`](https://stedolan.github.io/jq/) for further post-processing.

```bash
$ rsconnect content --help
Usage: rsconnect content [OPTIONS] COMMAND [ARGS]...

  Interact with Posit Connect's content API.

Options:
  --help  Show this message and exit.

Commands:
  build            Build content on Posit Connect.
  describe         Describe a content item on Posit Connect.
  download-bundle  Download a content item's source bundle.
  search           Search for content on Posit Connect.
```

### Content Search

The `rsconnect content search` subcommands can be used by administrators and publishers
to find specific content on a given Posit Connect server. The search returns
metadata for each content item that meets the search criteria.

```bash
$ rsconnect content search --help
Usage: rsconnect content search [OPTIONS]

Options:
  -n, --name TEXT                 The nickname of the Posit Connect server.
  -s, --server TEXT               The URL for the Posit Connect server.
  -k, --api-key TEXT              The API key to use to authenticate with
                                  Posit Connect.

  -i, --insecure                  Disable TLS certification/host validation.
  -c, --cacert FILENAME           The path to trusted TLS CA certificates.
  --published                     Search only published content.
  --unpublished                   Search only unpublished content.
  --content-type [unknown|shiny|rmd-static|rmd-shiny|static|api|tensorflow-saved-model|jupyter-static|python-api|python-dash|python-streamlit|python-bokeh|python-fastapi|quarto-shiny|quarto-static]
                                  Filter content results by content type.
  --r-version VERSIONSEARCHFILTER
                                  Filter content results by R version.
  --py-version VERSIONSEARCHFILTER
                                  Filter content results by Python version.
  --title-contains TEXT           Filter content results by title.
  --order-by [created|last_deployed]
                                  Order content results.
  -v, --verbose                   Print detailed messages.
  --help                          Show this message and exit.

$ rsconnect content search
[
  {
    "max_conns_per_process": null,
    "content_category": "",
    "load_factor": null,
    "cluster_name": "Local",
    "description": "",
    "bundle_id": "142",
    "image_name": null,
    "r_version": null,
    "content_url": "https://connect.example.org:3939/content/4ffc819c-065c-420c-88eb-332db1133317/",
    "connection_timeout": null,
    "min_processes": null,
    "last_deployed_time": "2021-12-02T18:09:11Z",
    "name": "logs-api-python",
    "title": "logs-api-python",
    "created_time": "2021-07-19T19:17:32Z",
    "read_timeout": null,
    "guid": "4ffc819c-065c-420c-88eb-332db1133317",
    "parameterized": false,
    "run_as": null,
    "py_version": "3.8.2",
    "idle_timeout": null,
    "app_role": "owner",
    "access_type": "acl",
    "app_mode": "python-api",
    "init_timeout": null,
    "id": "18",
    "quarto_version": null,
    "dashboard_url": "https://connect.example.org:3939/connect/#/apps/4ffc819c-065c-420c-88eb-332db1133317",
    "run_as_current_user": false,
    "owner_guid": "edf26318-0027-4d9d-bbbb-54703ebb1855",
    "max_processes": null
  },
  ...
]
```

See [this section](#searching-for-content) for more comprehensive usage examples
of the available search flags.


### Content Build

> **Note:** The `rsconnect content build` subcommand requires Posit Connect >= 2021.11.1

Posit Connect caches R and Python packages in the configured
[`Server.DataDir`](https://docs.posit.co/connect/admin/appendix/configuration/#Server.DataDir).
Under certain circumstances (examples below), these package caches can become stale
and need to be rebuilt. This refresh automatically occurs when a Posit Connect
user visits the content. You may wish to refresh some content before it is visited
because it is high priority or is not visited frequently (API content, emailed reports).
In these cases, it is possible to preemptively build specific content items using
the `rsconnect content build` subcommands. This way the user does not have to pay
the build cost when the content is accessed next.

The following are some common scenarios where performing a content build might be necessary:

- OS upgrade
- changes to gcc or libc libraries
- changes to Python or R installations
- switching from source to binary package repositories or vice versa

> **Note:** The `content build` command is non-destructive, meaning that it does nothing to purge
> existing packrat/python package caches before a build. If you have an
> existing cache, it should be cleared prior to starting a content build.
> See the [migration documentation](https://docs.posit.co/connect/admin/appendix/cli/#migration) for details.

> **Note:** You may use the [`rsconnect content search`](#content-search) subcommand to help
> identify high priority content items to build.

```
rsconnect content build --help
Usage: rsconnect content build [OPTIONS] COMMAND [ARGS]...

  Build content on Posit Connect. Requires Connect >= 2021.11.1

Options:
  --help  Show this message and exit.

Commands:
  add      Mark a content item for build. Use `build run` to invoke the build
           on the Connect server.

  history  Get the build history for a content item.
  logs     Print the logs for a content build.
  ls       List the content items that are being tracked for build on a given
           Connect server.

  rm       Remove a content item from the list of content that are tracked for
           build. Use `build ls` to view the tracked content.

  run      Start building content on a given Connect server.
```

To build a specific content item, first `add` it to the list of content that is
"tracked" for building using its GUID.

> **Note:** Metadata for "tracked" content items is stored in a local directory called
> `rsconnect-build` which will be automatically created in your current working directory.
> You may set the environment variable `CONNECT_CONTENT_BUILD_DIR` to override this directory location.

```bash
$ rsconnect content build add --guid 4ffc819c-065c-420c-88eb-332db1133317
```

> **Note:** See [this section](#add-to-build-from-search-results) for
> an example of how to add multiple content items in bulk, from the results
> of a `rsconnect content search` command.

To view all currently "tracked" content items, use the `rsconnect content build ls` subcommand.

```bash
$ rsconnect content build ls
```

To view only the "tracked" content items that have not yet been built, use the `--status NEEDS_BUILD` flag.

```bash
$ rsconnect content build ls --status NEEDS_BUILD
```

Once the content items have been added, you may initiate a build
using the `rsconnect content build run` subcommand. This command will attempt to
build all "tracked" content that has the status `NEEDS_BUILD`.

```bash
$ rsconnect content build run
[INFO] 2021-12-14T13:02:45-0500 Initializing ContentBuildStore for https://connect.example.org:3939
[INFO] 2021-12-14T13:02:45-0500 Starting content build (https://connect.example.org:3939)...
[INFO] 2021-12-14T13:02:45-0500 Starting build: 4ffc819c-065c-420c-88eb-332db1133317
[INFO] 2021-12-14T13:02:50-0500 Running = 1, Pending = 0, Success = 0, Error = 0
[INFO] 2021-12-14T13:02:50-0500 Build succeeded: 4ffc819c-065c-420c-88eb-332db1133317
[INFO] 2021-12-14T13:02:55-0500 Running = 0, Pending = 0, Success = 1, Error = 0
[INFO] 2021-12-14T13:02:55-0500 1/1 content builds completed in 0:00:10
[INFO] 2021-12-14T13:02:55-0500 Success = 1, Error = 0
[INFO] 2021-12-14T13:02:55-0500 Content build complete.
```

Sometimes content builds will fail and require debugging by the publisher or administrator.
Use the `rsconnect content build ls` to identify content builds that resulted in errors
and inspect the build logs with the `rsconnect content build logs` subcommand.

```
$ rsconnect content build ls --status ERROR
[INFO] 2021-12-14T13:07:32-0500 Initializing ContentBuildStore for https://connect.example.org:3939
[
  {
    "rsconnect_build_status": "ERROR",
    "last_deployed_time": "2021-12-02T18:09:11Z",
    "owner_guid": "edf26318-0027-4d9d-bbbb-54703ebb1855",
    "rsconnect_last_build_log": "/Users/david/code/posit/rsconnect-python/rsconnect-build/logs/connect_example_org_3939/4ffc819c-065c-420c-88eb-332db1133317/pZoqfBoi6BgpKde5.log",
    "guid": "4ffc819c-065c-420c-88eb-332db1133317",
    "rsconnect_build_task_result": {
      "user_id": 1,
      "error": "Cannot find compatible environment: no compatible Local environment with Python version 3.9.5",
      "code": 1,
      "finished": true,
      "result": {
        "data": "An error occurred while building the content",
        "type": "build-failed-error"
      },
      "id": "pZoqfBoi6BgpKde5"
    },
    "dashboard_url": "https://connect.example.org:3939/connect/#/apps/4ffc819c-065c-420c-88eb-332db1133317",
    "name": "logs-api-python",
    "title": "logs-api-python",
    "content_url": "https://connect.example.org:3939/content/4ffc819c-065c-420c-88eb-332db1133317/",
    "bundle_id": "141",
    "rsconnect_last_build_time": "2021-12-14T18:07:16Z",
    "created_time": "2021-07-19T19:17:32Z",
    "app_mode": "python-api"
  }
]

$ rsconnect content build logs --guid 4ffc819c-065c-420c-88eb-332db1133317
[INFO] 2021-12-14T13:09:27-0500 Initializing ContentBuildStore for https://connect.example.org:3939
Building Python API...
Cannot find compatible environment: no compatible Local environment with Python version 3.9.5
Task failed. Task exited with status 1.
```

## Common Usage Examples

### Searching for content

The following are some examples of how publishers might use the
`rsconnect content search` subcommand to find content on Posit Connect.
By default, the `rsconnect content search` command will return metadata for ALL
of the content on a Posit Connect server, both published and unpublished content.

> **Note:** When using the `--r-version` and `--py-version` flags, users should
> make sure to quote the arguments to avoid conflicting with your shell. For
> example, bash would interpret `--py-version >3.0.0` as a shell redirect because of the
> unquoted `>` character.

```bash
# return only published content
$ rsconnect content search --published

# return only unpublished content
$ rsconnect content search --unpublished

# return published content where the python version is at least 3.9.0
$ rsconnect content search --published --py-version ">=3.9.0"

# return published content where the R version is exactly 3.6.3
$ rsconnect content search --published --r-version "==3.6.3"

# return published content where the content type is a static RMD
$ rsconnect content search --content-type rmd-static

# return published content where the content type is either shiny OR fast-api
$ rsconnect content search --content-type shiny --content-type python-fastapi

# return all content, published or unpublished, where the title contains the text "Stock Report"
$ rsconnect content search --title-contains "Stock Report"

# return published content, results are ordered by when the content was last deployed
$ rsconnect content search --published --order-by last_deployed

# return published content, results are ordered by when the content was created
$ rsconnect content search --published --order-by created
```

### Finding r and python versions

One common use for the `search` command might be to find the versions of
r and python that are currently in use on your Posit Connect server before a migration.

```bash
# search for all published content and print the unique r and python version combinations
$ rsconnect content search --published | jq -c '.[] | {py_version,r_version}' | sort |
uniq
{"py_version":"3.8.2","r_version":"3.5.3"}
{"py_version":"3.8.2","r_version":"3.6.3"}
{"py_version":"3.8.2","r_version":null}
{"py_version":null,"r_version":"3.5.3"}
{"py_version":null,"r_version":"3.6.3"}
{"py_version":null,"r_version":null}
```

### Finding recently deployed content

```bash
# return only the 10 most recently deployed content items
$ rsconnect content search --order-by last_deployed --published | jq -c 'limit(10; .[]) | { guid, last_deployed_time }'
{"guid":"4ffc819c-065c-420c-88eb-332db1133317","last_deployed_time":"2021-12-02T18:09:11Z"}
{"guid":"aa2603f8-1988-484f-a335-193f2c57e6c4","last_deployed_time":"2021-12-01T20:56:07Z"}
{"guid":"051252f0-4f70-438f-9be1-d818a3b5f8d9","last_deployed_time":"2021-12-01T20:37:01Z"}
{"guid":"015143da-b75f-407c-81b1-99c4a724341e","last_deployed_time":"2021-11-30T16:56:21Z"}
{"guid":"bcc74209-3a81-4b9c-acd5-d24a597c256c","last_deployed_time":"2021-11-30T15:51:07Z"}
{"guid":"f21d7767-c99e-4dd4-9b00-ff8ec9ae2f53","last_deployed_time":"2021-11-23T18:46:28Z"}
{"guid":"da4f709c-c383-4fbc-89e2-f032b2d7e91d","last_deployed_time":"2021-11-23T18:46:28Z"}
{"guid":"9180809d-38fd-4730-a0e0-8568c45d87b7","last_deployed_time":"2021-11-23T15:16:19Z"}
{"guid":"2b1d2ab8-927d-4956-bbf9-29798d039bc5","last_deployed_time":"2021-11-22T18:33:17Z"}
{"guid":"c96db3f3-87a1-4df5-9f58-eb109c397718","last_deployed_time":"2021-11-19T20:25:33Z"}
```

### Add to build from search results

One common use case might be to `rsconnect content build add` content for build
based on the results of a `rsconnect content search`. For example:

```bash
# search for all API type content, then
# for each guid, add it to the "tracked" content items
$ for guid in $(rsconnect content search \
--published \
--content-type python-api \
--content-type api | jq -r '.[].guid'); do \
rsconnect content build add --guid $guid; done
```

Adding content items one at a time can be a slow operation. This is because
`rsconnect content build add` must fetch metadata for each content item before it
is added to the "tracked" content items. By providing multiple `--guid` arguments
to the `rsconnect content build add` subcommand, we can fetch metadata for multiple content items
in a single api call, which speeds up the operation sigificantly.

```bash
# write the guid of every published content item to a file called guids.txt
rsconnect content search --published | jq '.[].guid' > guids.txt

# bulk-add from the guids.txt by executing a single `rsconnect content build add` command
xargs printf -- '-g %s\n' < guids.txt | xargs rsconnect content build add
```
## Programmatic Provisioning

RStudio Connect supports the programmatic bootstrapping of an admininistrator API key 
for scripted provisioning tasks. This process is supported by the `rsconnect bootstrap` command,
which uses a JSON Web Token to request an initial API key from a fresh Connect instance. 

!!! warning 
  
    This feature **requires Python version 3.6 or higher**.

```bash
$ rsconnect bootstrap --server https://connect.example.org:3939 --jwt-keypath /path/to/secret.key
```

A full description on how to use `rsconnect bootstrap` in a provisioning workflow is provided in the Connect administrator guide's 
[programmatic provisioning](https://docs.posit.co/connect/admin/programmatic-provisioning) documentation.
