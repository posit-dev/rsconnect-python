# rsconnect-python

This package is a library used by the rsconnect-jupyter package to deploy Jupyter notebooks to RStudio Connect. It can also be used by other Python-based deployment tools.

There is also a CLI deployment tool which can be used directly to deploy Jupyter notebooks. Other content types can be deployed if they include a prepared `manifest.json` file.

### Installation

Eventually this will be pip-installable. For now:

```
git clone https://github.com/rstudio/rsconnect-python
cd rsconnect-python
python setup.py install
```

### Using the rsconnect CLI

```
rsconnect deploy \
	--server https://my.connect.server:3939 \
	--api-key my-api-key \
	my-notebook.ipynb
```

Note: the examples here use long command line options, but there are short options (`-s`, `-k`, etc.) available. Run `rsconnect deploy --help` for details.

### Saving Server Information
To avoid having to provide your server information at each deployment, you can optionally save server information:

```
rsconnect add \
	--api-key my-api-key \
	--server https://my.connect.server:3939 \
	--name myserver
```

Once the server is saved, you can refer to it by name:

```
rsconnect deploy --server myserver my-notebook.ipynb
```

If there is only one server saved, this will work too:

```
rsconnect deploy my-notebook.ipynb
```

You can see the list of saved servers with:

```
rsconnect list
```

and remove servers with:

```
rsconnect remove myserver
```

You can verify a server URL (and optionally, an API key):

```
rsconnect test \
	--server https://my.connect.server:3939 \
	--api-key my-api-key
```

### Deployment Options

#### Including Extra Files
You can include extra files in the deployment bundle to make them available when your notebook is run by the Connect server. Just specify them on the command line after the notebook file:

```
rsconnect deploy my-notebook.ipynb data.csv
```

#### Package Dependencies
If a `requirements.txt` file exists in the same directory as the notebook file, it will be included in the bundle. It must specify the package dependencies needed to execute the notebook. RStudio Connect will reconstruct the python environment using the specified package list.

If there is no `requirements.txt` file, the package dependencies will be determined from the current Python environment, or from an alternative Python executable specified in the `--python` option or via the `RETICULATE_PYTHON` environment variable.

```
rsconnect deploy --python /path/to/python my-notebook.ipynb
```

You can see the packages list that will be included by running `pip freeze` yourself, ensuring that you use the same Python that you use to run your Jupyter Notebook:

```
/path/to/python -m pip freeze
```

#### Static (Snapshot) Deployment
By default, `rsconnect` deploys the original notebook with source code. This enables the RStudio Connect server to re-run the notebook upon request or on a schedule.

If you just want to publish an HTML snapshot of the notebook, you can use the `--static` option. This will cause `rsconnect` to execute your notebook locally to produce the HTML file, then publish the HTML file to the Connect server.

```
rsconnect deploy --static my-notebook.ipynb
```

#### Deploying R or Other Content
You can deploy other content that has an existing RStudio Connect `manifest.json` file. For example, if you download and unpack a source bundle from Connect, you can deploy the resulting directory.

Note that in this case, the existing content is deployed as-is. Python environment inspection and notebook pre-rendering, if needed, are assumed to be already done and represented in the manifest.

```
rsconnect deploy /path/to/manifest.json
```

If you have R content but don't have a `manifest.json` file, you can use the RStudio IDE to create the manifest. See the help for the `rsconnect::writeManifest` R function:

```
install.packages('rsconnect')
library(rsconnect)
?rsconnect::writeManifest
```

#### Creating a Manifest for Future Deployment
You can create a `manifest.json` file for a Jupyter Notebook, then use that manifest in a later deployment. 

The `manifest` command will also create a `requirements.txt` file, if it does not already exist. It will contain the package dependencies from the current Python environment, or from an alternative Python executable specified in the `--python` option or via the `RETICULATE_PYTHON` environment variable.

Note: manifests for static (pre-rendered) notebooks cannot be created.

```
rsconnect manifest my-notebook.ipynb
```

#### Title
The title of the deployed content is derived from the filename. For example, if you deploy `my-notebook.ipynb`, the title will be `my-notebook`. To change this, use the `--title` option:

```
rsconnect deploy --title "My Notebook" my-notebook.ipynb
```

### Network Options

#### TLS/SSL Certificates

RStudio Connect servers can be configured to use TLS/SSL. If your server's certificate is trusted by your Jupyter Notebook server, then you don't need to do anything special. Just provide the URL and API Key:

```
rsconnect add \
	--api-key my-api-key \
	--server https://my.connect.server:3939 \
	--name my-server
```

If this fails with a TLS Certificate Validation error, then you have two options.

1. Provide the Root CA certificate that is at the root of the signing chain for your RStudio Connect server. This will enable `rsconnect` to securely validate the server's TLS certificate.

```
rsconnect add \
	--api-key my-api-key \
	--server https://my.connect.server:3939 \
	--cacert /path/to/certificate.pem \
	--name my-server
```

1. Connect in "insecure mode". This disables TLS certificate verification, which results in a less secure connection.

```
rsconnect add \
	--api-key my-api-key \
	--server https://my.connect.server:3939 \
	--insecure \
	--name my-server
```


### Updating a Deployment

If you deploy a file again to the same server, `rsconnect` will update the previous deployment by default. This means that you can keep running `rsconnect deploy my-notebook.ipynb` as you develop new versions of your notebook.

#### Forcing a New Deployment
To bypass this behavior and force a new deployment, use the `--new` option:

```
rsconnect deploy --new my-notebook.ipynb
```

#### Updating a Different Deployment
If you want to update an existing deployment but don't have the saved deployment data, you can provide the app's numeric ID or GUID on the command line:

```
rsconnect deploy --app-id 123456 my-notebook.ipynb
```

You must be the owner of the target deployment, or a collaborator with permission to change the content. The type of content (static notebook, or notebook with source code) must match the existing deployment.

Note: there is no confirmation required to update a deployment. If you do so accidentally, use the "Source Versions" dialog in the Connect dashboard to activate the previous version and remove the erroneous one.

#### Showing the Deployment Information
You can see the information that rsconnect-python has saved for the most recent deployment
with the `info` command:

```
rsconnect info my-notebook.ipynb
```

If you have deployed to multiple servers, the most recent deployment information for each server will be shown. This command also displays the path to the file where the deployment data is stored.


## Configuration Files
Configuration files are stored in a platform-specific directory:

| Platform | Location                                                           |
| -------- | ------------------------------------------------------------------ |
| Mac      | `$HOME/Library/Application Support/rsconnect-python/`              |
| Linux    | `$HOME/.rsconnect-python/` or `$XDG_CONFIG_HOME/rsconnect-python/` |
| Windows  | `$APPDATA/rsconnect-python`                                        |

Server information is stored in the `servers.json` file in that directory.

### Deployment Data
After a deployment is completed, information about the deployment is saved
to enable later redeployment. This data is stored alongside the deployed file,
in an `rsconnect-python` subdirectory,
if possible. If that location is not writable during deployment, then
the deployment data will be stored in the global configuration directory specified above.
