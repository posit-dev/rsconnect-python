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

#### Python Version

When deploying Python content to Posit Connect,
the server will require a version of Python that matches the content
requirements.

For example, a server with only Python 3.9 installed will fail to match content
that requires Python 3.8.

`rsconnect` supports detecting Python version requirements in several ways:
    1. A `.python-version` file exists. In such case
       `rsconnect` will use its content to determine the python version requirement.
    2. A `pyproject.toml` with a `project.requires-python` field exists.
       In such case the requirement specified in the field will be used
       if no `.python-version` file exists.
    3. A `setup.cfg` with an `options.python_requires` field exists.
       In such case the requirement specified in the field will be used
       if **1** or **2** were not already satisfied.
    4. If no other source of version requirement was found, then
       the interpreter in use is considered the one required to run the content.

On Posit Connect `>=2025.03.0` the requirement detected by `rsconnect` is
always respected. Older Connect versions will instead rely only on the
python version used to deploy the content to determine the requirement.

For more information see the [Posit Connect Admin Guide chapter titled Python Version
Matching](https://docs.posit.co/connect/admin/python/#python-version-matching).

We recommend providing a `pyproject.toml` with a `project.requires-python` field
if the deployed content is an installable package and a `.python-version` file
for plain directories.

> **Note**
> The packages and package versions listed in `requirements.txt` must be
> compatible with the Python version you request.

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

> **Note**
> Manifests for static (pre-rendered) notebooks cannot be created.

### API/Application Deployment Options

You can deploy a variety of APIs and applications using sub-commands of the
`rsconnect deploy` command.

* `api`: WSGI-compliant APIs (e.g., `bottle`, `falcon`, `flask`, `flask-restx`, `flasgger`, `pycnic`).
* `flask`: Flask APIs (_Note: `flask` is an alias of `api`._).
* `fastapi`: ASGI-compliant APIs (e.g, `fastapi`, `quart`, `sanic`, `starlette`)
* `dash`: Python Dash apps
* `streamlit`: Streamlit apps
* `bokeh`: Bokeh server apps
* `gradio`: Gradio apps
* `panel`: HoloViz Panel apps

All options below apply equally to the `api`, `fastapi`, `dash`, `streamlit`,
`gradio`, `bokeh`, and `panel` sub-commands.

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

The "`**`" glob pattern will recursively match all files and directories,
while "`*`" only matches files. The "`**`" pattern is useful with complicated
project hierarchies where enumerating the _included_ files is simpler than
listing the _exclusions_.

```bash
rsconnect deploy quarto . _quarto.yml index.qmd requirements.txt --exclude "**"
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

#### Python Version

When deploying Python content to Posit Connect,
the server will require matching `<MAJOR.MINOR>` versions of Python. For example,
a server with only Python 3.9 installed will fail to match content deployed with
Python 3.8. Your administrator may also enable exact Python version matching which
will be stricter and require matching major, minor, and patch versions. For more
information see the [Posit Connect Admin Guide chapter titled Python Version
Matching](https://docs.posit.co/connect/admin/python/#python-version-matching).

We recommend installing a version of Python on your client that is also available
in your Connect installation. If that's not possible, you can override
rsconnect-python's detected Python version and request a version of Python
that is installed in Connect, For example, this command:

```bash
rsconnect deploy api --override-python-version 3.11.5 my-api/
```

will deploy the content in `my-api` while requesting that Connect
use Python version 3.11.5.

> **Note**
> The packages and package versions listed in `requirements.txt` must be
> compatible with the Python version you request.

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

> **Note**
> In this case, the existing content is deployed as-is. Python environment
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
`rsconnect deploy streamlit`, `rsconnect deploy bokeh`, `rsconnect deploy gradio`, or `rsconnect deploy panel`,
the title is derived from the directory containing the API or application.

When using `rsconnect deploy manifest`, the title is derived from the primary
filename referenced in the manifest.

#### Verification After Deployment

After deploying your content, rsconnect accesses the deployed content
to verify that the deployment is live. This is done with a `GET` request
to the content, without parameters. The request is
considered successful if there isn't a 5xx code returned. Errors like
400 Bad Request or 405 Method Not Allowed because not all apps support `GET /`.
For cases where this is not desired, use the `--no-verify` flag on the command line.

### Environment variables

You can set environment variables during deployment. Their names and values will be
passed to Posit Connect during deployment so you can use them in your code. Note that
if you are using `rsconnect` to deploy to shinyapps.io, environment variable management
is not supported on that platform.

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

> **Note**
> There is no confirmation required to update a deployment. If you do so
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

You can render a Jupyter notebook without its corresponding input code cells by passing the '--hide-all-input' flag through the cli:

```bash
rsconnect deploy notebook \
    --server https://connect.example.org \
    --api-key my-api-key \
    --hide-all-input \
    my-notebook.ipynb
```

To selectively hide input cells in a Jupyter notebook, you need to do two things:

1. tag cells with the 'hide_input' tag,
2. then pass the ' --hide-tagged-input' flag through the cli:

```bash
rsconnect deploy notebook \
    --server https://connect.example.org \
    --api-key my-api-key \
    --hide-tagged-input \
    my-notebook.ipynb
```

By default, rsconnect-python does not install Jupyter notebook-related depenencies.
To use these hide input features in rsconnect-python you need to install these extra dependencies:

```
notebook
nbformat
nbconvert>=5.6.1
```
