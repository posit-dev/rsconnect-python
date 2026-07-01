# rsconnect quickstart


Create a new Posit Connect project of the given TYPE in .//. Supported TYPE values: streamlit, shiny, fastapi, api, flask, notebook, voila, quarto. Writes a pyproject.toml with a \[tool.rsconnect\] section, creates a uv-managed virtualenv, and prints the local-run and deploy commands.


``` bash
rsconnect quickstart [OPTIONS] TYPE NAME
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect quickstart [OPTIONS] TYPE NAME

      Create a new Posit Connect project of the given TYPE in ./<name>/. Supported
      TYPE values: streamlit, shiny, fastapi, api, flask, notebook, voila, quarto.
      Writes a pyproject.toml with a [tool.rsconnect] section, creates a uv-
      managed virtualenv, and prints the local-run and deploy commands.

    Options:
      --python VERSION  Python version for 'requires-python' in the generated
                        pyproject.toml. A bare 'major.minor' like '3.10' means any
                        3.10.x; a full '3.11.14' is exact; pass an operator for
                        full control (e.g. '>=3.11' or '>=3.11,<3.14'). Defaults
                        to '>=<major.minor>' of the interpreter running rsconnect.
      --help            Show this message and exit.


# Arguments


`TYPE: CHOICE`  
Required.

`NAME: TEXT`  
Required.


# Options


`--python: TEXT`  
Python version for `requires-python` in the generated pyproject.toml. A bare `major.minor` like `3.10` means any 3.10.x; a full `3.11.14` is exact; pass an operator for full control (e.g. `>=3.11` or `>=3.11,<3.14`). Defaults to `>=<major.minor>` of the interpreter running rsconnect.
