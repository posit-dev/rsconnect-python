# rsconnect write-manifest pyproject


Create a manifest.json file for later deployment, for content described by a project's pyproject.toml. The given directory must contain a pyproject.toml with a \[tool.rsconnect\] table specifying app_mode and entrypoint. This will also write the environment file the manifest references (e.g. "requirements.txt"), regenerating it on each run unless it is itself the requirements source. Designed as the write-manifest partner for projects scaffolded by `rsconnect quickstart`.


``` bash
rsconnect write-manifest pyproject [OPTIONS] DIRECTORY
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect write-manifest pyproject [OPTIONS] DIRECTORY

      Create a manifest.json file for later deployment, for content described by a
      project's pyproject.toml. The given directory must contain a pyproject.toml
      with a [tool.rsconnect] table specifying app_mode and entrypoint. This will
      also write the environment file the manifest references (e.g.
      "requirements.txt"), regenerating it on each run unless it is itself the
      requirements source. Designed as the write-manifest partner for projects
      scaffolded by 'rsconnect quickstart'.

    Options:
      -o, --overwrite               Overwrite manifest.json, if it exists.
      -r, --requirements-file FILE  Path to the requirements source, relative to
                                    the project directory. Overrides
                                    ``[tool.rsconnect].requirements_file`` in
                                    pyproject.toml; defaults to ``pyproject.toml``
                                    (the project's declared dependencies). Pass
                                    ``uv.lock`` for a fully resolved manifest, or
                                    any ``requirements.txt``-compatible file.
      -v, --verbose                 Print detailed messages
      --exclude-renv                Skip renv.lock detection. R dependencies will
                                    not be added to the manifest, even when an
                                    renv.lock file is present (in the content
                                    directory or at RENV_PATHS_LOCKFILE).
      --help                        Show this message and exit.


# Arguments


`DIRECTORY: DIRECTORY`  
Required.


# Options


`-o, --overwrite`  
Overwrite manifest.json, if it exists.

`-r, --requirements-file: FILE`  
Path to the requirements source, relative to the project directory. Overrides `[tool.rsconnect].requirements_file` in pyproject.toml; defaults to `pyproject.toml` (the project's declared dependencies). Pass `uv.lock` for a fully resolved manifest, or any `requirements.txt`-compatible file.

`-v, --verbose`  
Print detailed messages

`--exclude-renv`  
Skip renv.lock detection. R dependencies will not be added to the manifest, even when an renv.lock file is present (in the content directory or at RENV_PATHS_LOCKFILE).
