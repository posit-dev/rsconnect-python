# rsconnect-python

This package is a library used by the rsconnect-jupyter package to deploy Jupyter notebooks to RStudio Connect. It can also be used by other Python-based deployment tools.

There is also a CLI deployment tool which can be used directly to deploy notebooks.

```
rsconnect deploy \
	--server https://my.connect.server:3939 \
	--api-key my-api-key \
	./my-notebook.ipynb
```

To avoid having to provide your server information at each deployment, you can optionally save server information:

```
rsconnect add \
	--api-key my-api-key \
	--server https://my.connect.server:3939 \
	--name myserver

rsconnect deploy --server myserver ./my-notebook.ipynb

# since there is only one server saved, this will work too:
rsconnect deploy ./my-notebook.ipynb
```

You can see the list of saved servers with:

```
rsconnect list
```

Servers can be removed with:

```
rsconnect remove myserver
```

You can check a server URL (and optionally, the API key):

```
rsconnect test \
	--server https://my.connect.server:3939 \
	--api-key my-api-key
```


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
if possible. If that location is not writable during deployment, then
the metadata will be stored in the global configuration directory specified above.
