# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added
- Ability to hide code cells when rendering Jupyter notebooks. 

After setting up Connect and rsconnect-python, the user can render a Jupyter notebook without its corresponding code cells by passing the ' hide-all-input' flag through the rsconnect cli:

```
rsconnect deploy notebook \
    -n server \
    -k APIKey \
    --hide-all-input \
    hello_world.ipynb
```

To selectively hide the input of cells, the user can add a tag call 'hide_input' to the cell, then pass the ' hide-tagged-input' flag through the rsconnect cli:

```
rsconnect deploy notebook \
    -n server \
    -k APIKey \
    --hide-tagged-input \
    hello_world.ipynb
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
