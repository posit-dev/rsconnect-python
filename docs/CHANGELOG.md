# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.28.2] - 2025-12-05

### Fixed

- Corrected Changelog to show the correct version number of the 1.28.1 release.

## [1.28.1] - 2025-12-05

### Removed

- Removed support for publishing to Posit Cloud. Posit Cloud no longer hosts
  deployed content. Users should migrate to Connect Cloud or Posit Connect.

### Fixed

- `rsconnect list` now properly functions when a stored server has no nickname.
- Fixes the HTTP User-Agent string to use PascalCase formatting. HTTP requests now identify the client as `RSConnectPython/x.y.z` instead of `rsconnect-python/x.y.z`.

### Changed

- Most callers of internal, undocumented Connect APIs have been updated to use
  documented v1 APIs.

## [1.28.0] - 2025-11-06

### Added

- Added `rsconnect mcp-server` command to expose rsconnect-python functionality to
  LLM clients via the Model Context Protocol. The server provides a `get_command_info`
  tool that returns parameter schemas for any rsconnect command, allowing LLMs
  to more easily construct valid CLI commands.

- You can now deploy Holoviz Panel applications. This requires Posit Connect release 2025.11.0
  or later. Use `rsconnect deploy panel` to deploy, or `rsconnect write-manifest panel`
  to create a manifest file.

### Fixed

- Snowflake SPCS (Snowpark Container Services) authentication now properly handles API keys
  and aligns with codebase patterns for server type detection and initialization.

## [1.27.1] - 2025-08-12

### Fixed

- Python Shiny apps can be deployed when Connect server version is hidden. (#695)

## [1.27.0] - 2025-07-10

### Added

- Added support for the `--draft` option when deploying content,
  this allows to deploy a new bundle for the content without exposing
  it as a the activated one.
- Improved support for Posit Connect deployments
  hosted in Snowpark Container Services.
- Relicensed package from GPL to MIT.

### Fixed

- Command-line options like `--api-key` and associated environment variables
  like `CONNECT_API_KEY` take precedence over values in a stored deployment
  target. (#684)

## [1.26.0] - 2025-05-28

### Added

- Added support for interaction with Posit Connect deployments
  hosted in Snowpark Container Services.
- `rsconnect` now detects Python interpreter version requirements from
  `.python-version`, `pyproject.toml` and `setup.cfg`
- `--python` and `--override-python-version` options are now deprecated
  in favor of using `.python-version` requirement file.

## [1.25.2] - 2025-02-26

### Fixed

- Display system error message when `rsconnect.environment` inspection fails

## [1.25.1] - 2024-12-20

### Added

- Added validation for required flags for the `rsconnect system caches delete` command.
- Added `--force` flag to `rsconnect content build run` command. This allows users
  to force builds when a build is already marked as running. (#630)

## [1.25.0] - 2024-12-18

### Added

- You can now deploy Gradio applications. This requires Posit Connect release 2024.12.0
  or later. Use `rsconnect deploy gradio` to deploy, or `rsconnect write-manifest gradio`
  to create a manifest file.

### Changed

- The `rsconnect content build run --poll-wait` argument specifies an integral
  number of seconds. It previously allowed fractional seconds. (#608)

- Uses the public Connect server API endpoint `/v1/tasks/{id}` to poll task
  progress. (#608)

### Removed

- Uncalled `RSConnectClient.app_publish()` function, which referenced an
  obsolete workflow.

## [1.24.0] - 2024-05-28

### Added
- Added support for creating manifests for TensorFlow models.
- Added support for deploying TensorFlow models.

## [1.23.0] - 2024-04-04

### Added
- Added support for creating manifests for Shiny Express apps.
- Added support for deploying interactive Quarto dashboards that use Shiny Express syntax.

### Changed

- When deploying Shiny for Python applications on servers using a version of
  Connect prior to 2024.01.0, there is an incompatibility with
  `starlette>=0.35.0`. When deploying to these servers, the starlette version
  is now automatically set to `starlette<0.35.0`.

### Fixed

- Quarto content is marked as a "site" only when there are multiple input
  files. (#552)

- Quarto content automatically ignores `name.html` and `name_files` when
  `name.md`, `name.ipynb`, `name.Rmd`, or `name.qmd` is an input. (#553)

- Patterns provided to `--exclude` allow NT-style paths on Windows. (#320)

### Removed

- Python 3.7 support.

## [1.22.0] - 2024-01-23

### Added
- Added support for deploying Shiny express apps.
- Added support for deploying Shiny Express applications.
- Added a `--retry` flag to the `rsconnect content build run` command to re-run
  builds for all content in the NEEDS_BUILD, ABORTED, ERROR, or RUNNING state.

### Changed
- Improved the error and warning outputs when options conflict by providing the source
  from which the values have been determined. This allows for faster resolution of issues
  when combinations of stored credentials, environment variables and command line options
  are used.
- Updated verbose mode to output the source of all options being used when processing the
  CLI command.

### Fixed
- Interrupting a long-running `rsconnect content build run` command with `^C`
  will now update the local state file before attempting graceful cleanup. This
  should help prevent users from getting stuck a "build already running" state.
  See [#467](https://github.com/posit-dev/rsconnect-python/issues/467) for details.

- Addressed an error which occurred when attempting to create manifests for
  Quarto documents. (#534)

## [1.21.0] - 2023-10-26

### Fixed
- The `https_proxy` environment variable is recognized as a synonym for
  `HTTPS_PROXY`.
- When adding a new server, the initial request now includes an
  authorization header containing the API key. This is needed
  for Connect installations behind a proxy that only passes
  authenticated requests.
- Common environment directories (`env, venv, .env, .venv`) are no longer
  excluded by name. Environments are detected by the presence of a python
  executable in `bin` or `Scripts` and excluded.
- Lines output from `pip freeze` which start with [notice] are filtered out from the generated `requirements.txt`.

### Added
- Added support for the `no_proxy` or `NO_PROXY` environment variables to specify
  hosts that should not be accessed via proxy server. It's a comma-separated list
  of host or domain suffixes. For example, specifying `example.com` will
  bypass the proxy for example.com, host.example.com, etc.
- If an entrypoint is not specified with `--entrypoint`, rsconnect-python will try
  harder than before to choose an entrypoint file. In addition to the previously
  recognized filename patterns, the file patterns `app-*.py`, `app_*.py`, `*-app.py`,
  and `*_app.py` are now considered. However, if the directory contains more than
  one file matching these new patterns, you must provide rsconnect-python with an
  explicit `--entrypoint` argument.
- Added a new verbose logging level. Specifying `-v` on the command line uses this
  new level. Currently this will cause filenames to be logged as they are added to
  a bundle. To enable maximum verbosity (debug level), use `-vv`.
- Added a verification step to the deployment process that accesses the deployed content.
  This is a `GET` request to the content without parameters. The request is
  considered successful if there isn't a 5xx code returned (errors like
  400 Bad Request or 405 Method Not Allowed because not all apps support `GET /`).
  For cases where this is not desired, use the `--no-verify` flag on the command line.
- Added the `deploy flask` command.
- Added the `write-manifest flask` command.

### Changed
- Removing experimental support for Conda. Connect does not support restoring Conda environments.

## [1.20.0] - 2023-09-11

### Fixed
- Python virtualenvs are now detected in Windows environments, and are automatically
  excluded from the uploaded bundle.
- Error deploying to shinyapps.io when `--app-id` is provided [#464](https://github.com/posit-dev/rsconnect-python/issues/464).

### Added

- Add `--disable-env-management`, `--disable-env-management-py` and `--disable-env-management-r` flags for all content types
  that support environment restores. These flags indicate to Connect that the user is responsible for Python/R package
  installation, and Connect should not install packages during the build. The Python/R packages must still be available in the runtime
  environment in order to run the content. This is especially useful if off-host execution is enabled when the execution environment
  (specified by `--image`) already contains the required packages. Requires Posit Connect `>=2023.07.0`.

## [1.19.1] - 2023-08-01

### Added
- Failed deploys to shinyapps.io will now output build logs. Posit Cloud application deploys will also output build logs once supported server-side.
- Redeploy to Posit Cloud from a project now correctly associates the content with that project.

## [1.19.0] - 2023-07-12

### Added

- The `CONNECT_TASK_TIMEOUT` environment variable, which configures the timeout for [task based operations](https://docs.posit.co/connect/api/#get-/v1/tasks/-id-). This value translates into seconds (e.g., `CONNECT_TASK_TIMEOUT=60` is equivalent to 60 seconds.) By default, this value is set to 86,400 seconds (e.g., 24 hours).
- Deploys for Posit Cloud now support Quarto source files or projects with `markdown` or `jupyter` engines.


## [1.18.0] - 2023-06-27

### Added
- Deploys for Posit Cloud and shinyapps.io now accept the `--visibility` flag.

### Changed
- Removes redundant client-side compatibility checks in favor of server-side compatibility checks when deploying Python content. Note that the error handling may differ between versions of Connect. See Connect release notes for additional details regarding compatibility.

## [1.17.1] - 2023-05-25

### Fixed
- Shiny app deployment fails when static content is present in the app [#373](https://github.com/posit-dev/rsconnect-python/issues/373).

## [1.17.0] - 2023-05-12

### Added
- `deploy html` and `deploy manifest` now support deployment to Posit Cloud.

- Added `system caches list` and `system caches delete` commands which allow administrators to enumerate and delete R and Python runtime caches from Connect servers [#384](https://github.com/posit-dev/rsconnect-python/pull/384). Read more about the feature in our [docs](https://docs.posit.co/connect/admin/server-management/runtime-caches/).

### Changed
- Cloud deployments accept the content id instead of application id in the --app-id field.
- The `app_id` field in application store files also stores the content id instead of the application id.
- Application store files include a `version` field, set to 1 for this release.

### Fixed
- cacert read error when adding/updating a server [#403](https://github.com/posit-dev/rsconnect-python/issues/403).
- getdefaultlocale no longer work with newer versions of Python [#397](https://github.com/posit-dev/rsconnect-python/issues/397) [#399](https://github.com/posit-dev/rsconnect-python/issues/399).
- extra files not being included in write-manifest [#416](https://github.com/posit-dev/rsconnect-python/issues/416).

## [1.16.0] - 2023-03-27

### Added
- The `CONNECT_REQUEST_TIMEOUT` environment variable, which configures the request timeout for all blocking HTTP and HTTPS operations. This value translates into seconds (e.g., `CONNECT_REQUEST_TIMEOUT=60` is equivalent to 60 seconds.) By default, this value is 300.

### Fixed

- Extra files were not being included in deploy Voila.

- Error message to indicate the Python also has to be configured in Connect.

## [1.15.0] - 2023-03-15

### Added
- Added `deploy voila` command to deploy Jupyter Voila notebooks. See the [user documentation](https://docs.posit.co/connect/user/publishing-cli-notebook/#interactive-voila-deployment)
    for more information.

### Changed
- `deploy html` was refactored. Its behavior is described below.

#### Deploying HTML
Specifying a directory in the path will result in that entire directory*, subdirectories, and sub contents included in the deploy bundle. The entire directory is included whether or not an entrypoint was supplied


e.g.
using the following directory,
```
├─ my_project/
│ ├─ index.html
│ ├─ second.html
```
and the following command:
```
rsconnect deploy html -n local my_project
```
or this command:
```
rsconnect deploy html -n local my_project -e my_project/index.html
```
we will have a bundle which includes both `index.html` and `second.html`

- specifying a file in the path will result in that file* - not the entire directory - included in the deploy bundle

e.g.
using the following directory,
```
├─ my_project/
│ ├─ index.html
│ ├─ second.html
```
and the following command:
```
rsconnect deploy html -n local my_project/second.html
```
we will have a bundle which includes `second.html`

- a note regarding entrypiont
    - providing an entrypoint is optional if there's an `index.html` inside the project directory, or if there's a *single* html file in the project directory.
    - if there are multiple html files in the project directory and it contains no `index.html`, we will get an exception when deploying that directory unless an entrypoint is specified.

- if we want to specify an entrypint, and we are executing the deploy command outside a project folder, we must specify the full path of the entrypoint:

```
rsconnect deploy html -n local my_project -e my_project/second.html
```

- if we want to specify an entrypint,  and we are executing the deploy command inside the project folder, we can abbreviate the entrypoint, like so:
```
cd my_project
rsconnect deploy html -n local ./ -e second.html
```


*Plus the manifest & other necessary files needed for the bundle to work on Connect.

## [1.14.1] - 2023-02-09

### Fixed

- Extra files were not being included in certain deploy and write-manifest commands.

### Added

- The `--cacert` option now supports certificate files encoded in the Distinguished Encoding Rules (DER) binary format. Certificate files with DER encoding must end in a `.cer` or `.der` suffix.
- The `--python` option now provides additional user guidance when an invalid path is provided.

### Changed

- The `--cacert` option now requires that Privacy Enhanced Mail (PEM) formatted certificate files end in a `.ca-bundle`, `.crt`, `.key`, or `.pem` suffix.

## [1.14.0] - 2023-01-19

### Changed
- You can now redeploy to a content with an "unknown" app mode. A content item's app mode is "unknown" if it was created, but never deployed to, or its deployment failed before an app mode could be determined.

### Removed

- Python 3.5 & 3.6 support.

- `rsconnect-python` no longer considers the `RETICULATE_PYTHON` environment variable.
  In environments where `RETICULATE_PYTHON` is set outside a project context (e.g. by a Posit Workbench administrator),
  attempting to deploy content or write manifests in projects using virtual environments required explicitly setting `--python /path/to/virtualenv/python`.
  Removing `RETICULATE_PYTHON` detection should simplify the use of the CLI in this case.

## [1.13.0] - 2022-12-02

### Added
- When running rsconnect bootstrap, you can now specify the jwt secret using the CONNECT_BOOTSTRAP_SECRETKEY environment variable.

### Changed
- Update pip_freeze to use `pip freeze` since Connect filters for valid package paths in the backend and it no longer depends on the undocumented behavior of `pip list --format=freeze`. This reverts the change made in 1.5.2.

- Renamed the deploy_html `excludes` flag to `exclude` for consistency with other deploy commands.

## [1.12.1] - 2022-11-07

### Changed
- Updated actions.py to reuse code in main, minus the CLI parts. As a result deploy_jupyter_notebook and deploy_by_manifest had their return signatures changed. They now return None.

## [1.12.0] - 2022-10-26

### Added
- You can now use the new rsconnect bootstrap command to programmatically provision an initial administrator api key on a fresh Connect instance. This requires RStudio Connect release 2022.10.0 or later and Python version >= 3.6.

## [1.11.0] - 2022-10-12

### Added
- Add support for deployment on RStudio Cloud

### Changed
- rsconnect-python will now issue warnings if it detects environmental variables that overlap with stored credentials

## [1.10.0] - 2022-07-27

### Added
- You can now deploy Shiny for Python applications with `deploy shiny`
- In addition to deploying to Connect, you can now deploy to shinyapps.io with `deploy shiny` or `deploy manifest`
- The `add` option now supports shinyapps.io credentials.

## [1.9.0] - 2022-07-06
### Added

- You can now deploy Quarto documents in addition to Quarto projects. This
  requires RStudio Connect release 2021.08.0 or later. Use `rsconnect deploy
  quarto` to deploy, or `rsconnect write-manifest quarto` to create a manifest
  file.

### Changed

- As a prelude to setting and documenting rsconnect-python APIs, various functions in `actions` have been moved to `bundle`, or replaced with RSConnectExecutor. The moved functions now include a deprecation warning, and will be fully deprecated in a future release.

## [1.8.1] - 2022-05-31

### Changed

Corrected changelog heading.

## [1.8.0] - 2022-05-31

### Added

- You can now set environment variables for the deployed content with the `-E` option.
  These will be passed to RStudio Connect during the deployment process,
  so they are available in your code whenever it runs within RStudio Connect.
  Requires RStudio Connect version 1.8.6 or later.

- You can now deploy Quarto projects. This requires RStudio Connect release
  2021.08.0 or later. Use `rsconnect deploy quarto` to deploy, or `rsconnect
  write-manifest quarto` to create a manifest file.

- An `image` command line option has been added to the `write-manifest` and
  `deploy` commands to specify the target image to be used on the RStudio Connect
  server during content execution. This is only supported for the `api`, `bokeh`, `dash`,
  `fastapi`, `notebook`, `quarto` and `streamlit` sub-commands. It is only
  applicable if the RStudio Connect server is configured to use off-host execution.

- You can now deploy static content such as html and its associated assets with
  `rsconnect deploy html`.

## [1.7.1] - 2022-02-15

### Added

- Publish supported python versions announcement.

## [1.7.0] - 2022-02-11

### Added

- Adds `rsconnect content` subcommands for interacting with RStudio Connect's `/v1/content`
  REST API. This allows users to search, download, and (re)build content. Users should
  note that the `rsconnect content build` subcommand requires RStudio Connect release 2021.11.1
  or later.

### Changed

- Support for Python 2.7 has been removed in this release.

## [1.6.0] - 2021-08-30

### Added

- You can now deploy FastAPI applications. This requires RStudio Connect release 2021.08.0
  or later. Use `rsconnect deploy fastapi` to deploy, or `rsconnect write-manifest fastapi`
  to create a manifest file.
- In addition to FastAPI, you can also deploy Quart, Sanic, and Falcon ASGI applications.

### Changed

- rsconnect-python will now issue a warning during deployment if there isn't a requirements.txt
  file in the deployment directory. Using a requirements file ensures consistency in the
  environment that will be created by the RStudio Connect server during deployment. This helps avoid
  unnecessary package installations and issues that can occur if rsconnect-python falls back
  to inferring packages from the local Python environment.

## [1.5.4] - 2021-07-29

### Added

- If an entrypoint is not specified with `--entrypoint`, rsconnect-python will attempt
  to choose an entrypoint file. It looks for common names (`app.py`, `application.py`,
  `main.py`, `api.py`). If there is a single python source file in the directory,
  that will be used as the entrypoint.
  rsconnect-python does not inspect the file contents to identify the object name, which must be
  one of the default names that Connect expects (`app`, `application`, `create_app`, or `make_app`).

- Ability to hide code cells when rendering Jupyter notebooks.

After setting up Connect (>=1.9.0) and rsconnect-python, the user can render a Jupyter notebook without its corresponding code cells by passing the ' hide-all-input' flag through the rsconnect cli:

```
rsconnect deploy notebook \
    --server https://connect.example.org:3939 \
    --api-key my-api-key \
    --hide-all-input \
    mynotebook.ipynb
```

To selectively hide the input of cells, the user can add a tag call 'hide_input' to the cell, then pass the ' hide-tagged-input' flag through the rsconnect cli:

```
rsconnect deploy notebook \
    --server https://connect.example.org:3939 \
    --api-key my-api-key \
    --hide-tagged-input \
    mynotebook.ipynb
```

## [1.5.3] - 2021-05-06

### Added
- Support for generating md5 file upload checksums, even if Python's `hashlib`
  was configured for FIPS mode. The fallback uses the `usedforsecurity` option which is
  available in Python 3.9 and later.


## [1.5.2] - 2021-04-02

### Added
- support for HTTPS_PROXY

### Changed
- Environments are now introspected with `pip list --format=freeze` instead of `pip freeze`,
  since the latter injects nonexistent paths into the requirements file when run in a conda environment.
  This issue started occurring when pip 20.1 added support for PEP 610 metadata.
- Conda environments contain Conda-only versions of setuptools, which are now filtered out from requirements.txt for non-Conda environments.

## [1.5.1] - 2020-11-02

### Fixed
- Python 2 encoding error when using rsconnect-jupyter to publish a notebook containing binary data.
- Preserve more details when raising exceptions.

## [1.5.0] - 2020-07-10

### Added
- support for deploying Streamlit and Bokeh applications
- improved handling of HTTP timeouts
- CI verification on macos with python3.8
- trigger [rsconnect-jupyter](https://github.com/rstudio/rsconnect-jupyter) workflow on
  successful pushes to main branch

### Changed
- default exclusion list to include common virtual environment directory names (`env`,
  `venv`, `.env`, and `.venv`)
- environment internally represented as data class instead of dict
- replace all internal "compatibility mode" references with "conda mode"
- CI moved to GitHub Actions

### Removed
- generation and publishing of `sdist` artifact

### Fixed
- explicitly set the `--to-html` option to `nbconvert` when publishing a static notebook,
  as required by the latest version of `nbconvert`


## [1.4.5] - 2020-04-10

### Changed
- provide clearer feedback when errors happen while building bundles from a manifest
- pin required versions of the `click` and `six` libraries that we use
- help text touch up

### Fixed
- output alignment under Python 2


## [1.4.4] - 2020-04-02

### Changed
- converted a traceback to a more appropriate message
- updated `CookieJar` class to support marshalling/un-marshalling
  to/from a dictionary

### Fixed
- an issue with cookie jar continuity across connections


## [1.4.3] - 2020-04-01

### Changed
- being more distinguishing between a server that's not running Connect and a credentials
  problem


## [1.4.2] - 2020-03-27

### Added
- more helpful feedback when a "requested object does not exist" error is returned by
  Connect

### Changed
- be more distinguishing between a server that's not running Connect and a credentials
  problem

### Fixed
- an issue where cookie header size could grow inappropriately (#107)
- corrected the instructions to enable auto-completion


## [1.4.1] - 2020-03-26

### Fixed
- sticky sessions so we will track deploys correctly when RStudio Connect is in an
  HA/clustered environment


## [1.4.0] - 2020-03-16

### Added
- functions in `actions` that provide the same functionality as the CLI

### Changed
- command line handling of options is more consistent across all commands
- `test` command replaced with a more broadly functional `details` command
- errors handled much more consistently and are more informative
- CLI output is more clean
- overall code has been refactored and improved for clarity, testability and stability
- all CLI help has been improved for consistency, correctness and completeness
- many documentation improvements in content and appearance


## [1.3.0] - 2020-01-07

### Added
- first release


[Unreleased]: https://github.com/posit-dev/rsconnect-python/compare/1.5.0...HEAD
[1.5.0]: https://github.com/posit-dev/rsconnect-python/compare/1.4.5...1.5.0
[1.4.5]: https://github.com/posit-dev/rsconnect-python/compare/1.4.4...1.4.5
[1.4.4]: https://github.com/posit-dev/rsconnect-python/compare/1.4.3...1.4.4
[1.4.3]: https://github.com/posit-dev/rsconnect-python/compare/1.4.2...1.4.3
[1.4.2]: https://github.com/posit-dev/rsconnect-python/compare/1.4.1...1.4.2
[1.4.1]: https://github.com/posit-dev/rsconnect-python/compare/1.4.0...1.4.1
[1.4.0]: https://github.com/posit-dev/rsconnect-python/compare/1.3.0...1.4.0
[1.3.0]: https://github.com/posit-dev/rsconnect-python/releases/tag/1.3.0
