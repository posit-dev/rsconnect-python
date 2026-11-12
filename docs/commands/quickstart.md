# Python version selection

Without `--python`, quickstart uses the newest usable Python installation
marked publishable for new content on the selected Posit Connect server.
It writes a `>=major.minor` requirement and asks uv to create the environment
with that major/minor. uv may download Python according to your uv settings.
Server selection and credentials use the usual `--name`, `--server`,
`--api-key`, TLS options, environment variables, and saved servers.

If no server is configured, quickstart uses the Python interpreter running
rsconnect. If the server cannot be queried or credentials are missing, it
warns and uses that interpreter without checking server compatibility. If a
successful lookup finds no usable publishable Python, quickstart fails: check
the server's Python configuration or use `--python`. A failed Python download
or dependency installation also fails and removes the incomplete project.

`--python` overrides discovery and makes no server request. A major/minor
version permits any patch release, a full version is exact, and a specifier
such as `>=3.10,<3.13` is used as supplied.

::: mkdocs-click
    :module: rsconnect.main
    :command: quickstart
