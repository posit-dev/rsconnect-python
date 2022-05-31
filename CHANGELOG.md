# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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


[Unreleased]: https://github.com/rstudio/rsconnect-python/compare/1.5.0...HEAD
[1.5.0]: https://github.com/rstudio/rsconnect-python/compare/1.4.5...1.5.0
[1.4.5]: https://github.com/rstudio/rsconnect-python/compare/1.4.4...1.4.5
[1.4.4]: https://github.com/rstudio/rsconnect-python/compare/1.4.3...1.4.4
[1.4.3]: https://github.com/rstudio/rsconnect-python/compare/1.4.2...1.4.3
[1.4.2]: https://github.com/rstudio/rsconnect-python/compare/1.4.1...1.4.2
[1.4.1]: https://github.com/rstudio/rsconnect-python/compare/1.4.0...1.4.1
[1.4.0]: https://github.com/rstudio/rsconnect-python/compare/1.3.0...1.4.0
[1.3.0]: https://github.com/rstudio/rsconnect-python/releases/tag/1.3.0
