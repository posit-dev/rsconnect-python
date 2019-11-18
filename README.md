# rsconnect-python

This package is a library used by the rsconnect-jupyter package to deploy Jupyter notebooks to RStudio Connect. It can also be used by other Python-based deployment tools.

There is also a CLI deployment tool which can be used directly to deploy notebooks.

```
rsconnect deploy \
	--api-key my-api-key \
	--server https://my.connect.server:3939 \
	./my-notebook.ipynb
```
