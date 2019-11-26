# rsconnect-python

This package is a library used by the rsconnect-jupyter package to deploy Jupyter notebooks to RStudio Connect. It can also be used by other Python-based deployment tools.

There is also a CLI deployment tool which can be used directly to deploy notebooks.

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

#### Static (Snapshot) Deployment
By default, `rsconnect` deploys the original notebook with source code. This enables the RStudio Connect server to re-run the notebook upon request or on a schedule.

If you just want to publish an HTML snapshot of the notebook, you can use the `--static` option. This will cause `rsconnect` to execute your notebook locally to produce the HTML file, then publish the HTML file to the Connect server.

```
rsconnect deploy --static my-notebook.ipynb
```

#### Title
The title of the deployed content is derived from the filename. For example, if you deploy `my-notebook.ipynb`, the title will be `my-notebook`. To change this, use the `--title` option:

```
rsconnect deploy --title "My Notebook" my-notebook.ipynb
```


### Updating a Deployment

If you deploy a file again to the same server, `rsconnect` will update the previous deployment by default. This means that you can keep running `rsconnect deploy my-notebook.ipynb` as you develop new versions of your notebook.

#### Forcing a New Deployment
To bypass this behavior and force a new deployment, use the `--new` option:

```
rsconnect deploy --new my-notebook.ipynb
```

#### Updating a Different Deployment
If you want to update an existing deployment but don't have the saved metadata, you can provide the app's numeric ID or GUID on the command line:

```
rsconnect deploy --app-id 123456 my-notebook.ipynb
```

You must be the owner of the target deployment, or a collaborator with permission to change the content. The type of content (static notebook, or notebook with source code) must match the existing deployment.


## Configuration Files
Configuration files are stored in a platform-specific directory:

| Platform | Location                                                           |
| -------- | ------------------------------------------------------------------ |
| Mac      | `$HOME/Library/Application Support/rsconnect-python/`              |
| Linux    | `$HOME/.rsconnect-python/` or `$XDG_CONFIG_HOME/rsconnect-python/` |
| Windows  | `$APPDATA/rsconnect-python`                                        |

Server information is stored in the `servers.json` file in that directory.

### Deployment Metadata
After a deployment is completed, information about the deployment is saved
to enable later redeployment. This data is stored alongside the deployed file,
in an `rsconnect-python` subdirectory,
if possible. If that location is not writable during deployment, then
the metadata will be stored in the global configuration directory specified above.
