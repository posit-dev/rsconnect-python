# `rsconnect preflight`

Use `preflight` to compare a project's runtime constraint with versions reported by a
self-hosted Posit Connect or Snowpark Container Services (SPCS) server. It supports
OAuth credentials and does not support Posit Connect Cloud. Preflight checks runtime
availability only. It does not assess application or dependency compatibility.
Preflight requires a POSIX system such as Linux or macOS; existing deployment commands remain available on Windows.

```{.bash filename="Terminal"}
rsconnect preflight --name myserver ./project
```

The `--runtime` option accepts `python` or `nodejs` and defaults to `python`. Select
Node.js with `--runtime nodejs`:

```{.bash filename="Terminal"}
rsconnect preflight -n myserver ./node-app --runtime nodejs
```

For Node.js, preflight compares `package.json`'s `engines.node` constraint with server
Node.js installations using npm semver. Node.js must be enabled and allowed by the
server license. For first publishes, an installation must also be marked publishable.
If a legacy server omits required runtime or publishability flags, the result can be
`unknown`.

Use `--node` with a path to select the local Node.js executable. It is valid only with
`--runtime nodejs`; passing it with Python is an error. Node.js preflight does not
support `--fix` and does not modify `package.json`, `package-lock.json`, or other
project files.

The command prints a JSON report with `status` set to `ok`, `incompatible`, or
`unknown`, along with runtime diagnostics, `warnings`, and `actions`. Operational errors return an `error` report.
For Python, the
report includes:

- `status`, `runtime`, `server`, `warnings`, and `actions`: check results, runtime name, and suggested next steps
- `publishable_python_versions`: Python versions from installations the server marks publishable for first publishes
- `local_python`: the local Python version
- `local_python_publishable`: whether the server marks the local Python minor version publishable, or `null` if unknown
- `recommended_python`: a suggested Python minor version for unconstrained first publication, or `null`
- `python_requires`: the project’s declared Python requirement, if present
- `existing_content`: an object with `exists`, `app_id`, `installed_python_version`, `server_python_versions`, and `python_compatibility`
- `quarto_available`: whether the local Quarto command is available
- `changed_files`: files changed by `--fix`

For Node.js, the report includes:

- `status`, `runtime`, `server`, `warnings`, and `actions`: check results, runtime name, and suggested next steps
- `local_node`: the selected local Node.js version
- `node_requires`: the `package.json` `engines.node` range
- `server_node_versions`: the server-reported installed Node.js versions
- `publishable_node_versions`: versions marked publishable for first publishes
- `nodejs_enabled` and `nodejs_status`: server Node.js availability and status
- `existing_content`: an object with `exists`, `app_id`, `node_version`, and `compatibility`
- `changed_files`: empty because Node.js preflight does not change project files

The server's enabled, license, and publishable flags inform the status. Treat `unknown`
as unresolved and inspect `warnings` and `actions`; do not treat it as compatible. An
`incompatible` result exits with status 3. An `ok` or `unknown` result exits with status 0.
Operational errors exit with status 1. Their JSON contains `status: error`, `runtime`, `error`, `changed_files`, `warnings`, and `actions`.
Invalid command syntax exits with status 2 and prints diagnostics to stderr.
Use `-v` or `-vv` for diagnostics on stderr; stdout remains reserved for the JSON result.

Use `--new` to check a new content item when the project has a deployment record. Use `--app-id` to check a content item by its identifier (ID) or globally unique identifier (GUID). Do not combine these options.

```{.bash filename="Terminal"}
rsconnect preflight --name myserver ./project --new
rsconnect preflight --name myserver ./project --app-id 00000000-0000-0000-0000-000000000000
```

For content deployed from a notebook, manifest, bundle, or Quarto file, pass that file to select its deployment record:

```{.bash filename="Terminal"}
rsconnect preflight --name myserver ./project/report.ipynb
```

Preflight reads project metadata and local prerequisites from the file's parent directory.
An unreadable content item or ambiguous deployment record returns `unknown`; inspect its actions before deploying.
If a directory contains file deployment history, pass the exact deployed file or `--app-id` to resolve the target.
An unresolved target prevents `--fix` from creating a Python pin.
Symlinked, non-regular, or oversized deployment records also return `unknown`.
Inspect the suggested actions and repair the record, or pass `--app-id` to select the existing content directly.

## Add a Python version pin

For new content with no Python constraint, add `--fix` to create a missing `.python-version` file:

```{.bash filename="Terminal"}
rsconnect preflight --name myserver ./project --fix
```

The command chooses an installation the server marks publishable for first publishes. If its Python minor version differs from the local Python version, the report includes a compatibility warning. `--fix` never overwrites an existing `.python-version` file or adds a pin when the project declares a Python constraint. The report lists any file it creates in `changed_files`.

::: mkdocs-click
    :module: rsconnect.main
    :command: preflight
