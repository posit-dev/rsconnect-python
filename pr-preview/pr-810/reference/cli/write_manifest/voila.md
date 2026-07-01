# rsconnect write-manifest voila


Create a manifest.json file for a Voila notebook for later deployment. This will create an environment file ("requirements.txt") if one does not exist. All files are created in the same directory as the notebook file.


``` bash
rsconnect write-manifest voila [OPTIONS] PATH [EXTRA_FILES]...
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect write-manifest voila [OPTIONS] PATH [EXTRA_FILES]...

      Create a manifest.json file for a Voila notebook for later deployment. This
      will create an environment file ("requirements.txt") if one does not exist.
      All files are created in the same directory as the notebook file.

    Options:
      -o, --overwrite                 Overwrite manifest.json, if it exists.
      -p, --python PATH               Path to Python interpreter whose environment
                                      should be used. The Python environment must
                                      have the rsconnect package installed.
      --override-python-version PYTHON-VERSION
                                      An optional python version to use instead of
                                      the version from the detected environment.
      -g, --force-generate            Force generating "requirements.txt", even if
                                      it already exists.
      -r, --requirements-file FILE    Path to requirements file listing the
                                      project dependencies. Any file compatible
                                      with requirements.txt format, uv.lock, or
                                      pyproject.toml is accepted, a
                                      requirements.txt.lock retrieved with
                                      'rsconnect content get-lockfile' is also
                                      supported. Must be inside the project
                                      directory.
      --package-installer [PIP|UV]    Select the Python package installer for
                                      installs in the manifest. By default,
                                      behavior is server-driven.
      -v, --verbose                   Print detailed messages
      -e, --entrypoint TEXT           The module and executable object which
                                      serves as the entry point.
      -x, --exclude TEXT              Specify a glob pattern for ignoring files
                                      when building the bundle. Note that your
                                      shell may try to expand this which will not
                                      do what you expect. Generally, it's safest
                                      to quote the pattern. This option may be
                                      repeated.
      -m, --multi-notebook            Set the manifest for multi-notebook mode.
      -I, --image TEXT                Target image to be used during content build
                                      and execution. This option is only
                                      applicable if the Connect server is
                                      configured to use off-host execution.
      --disable-env-management        Shorthand to disable environment management
                                      for both Python and R.
      --disable-env-management-py     Disable Python environment management for
                                      this bundle. Connect will not create an
                                      environment or install packages. An
                                      administrator must install the required
                                      packages in the correct Python environment
                                      on the Connect server.
      --disable-env-management-r      Disable R environment management for this
                                      bundle. Connect will not create an
                                      environment or install packages. An
                                      administrator must install the required
                                      packages in the correct R environment on the
                                      Connect server.
      --exclude-renv                  Skip renv.lock detection. R dependencies
                                      will not be added to the manifest, even when
                                      an renv.lock file is present (in the content
                                      directory or at RENV_PATHS_LOCKFILE).
      --help                          Show this message and exit.


# Arguments


`PATH: PATH`  
Required.

`EXTRA_FILES: FILE`  
Optional.


# Options


`-o, --overwrite`  
Overwrite manifest.json, if it exists.

`-p, --python: PATH`  
Path to Python interpreter whose environment should be used. The Python environment must have the rsconnect package installed.

`--override-python-version: PYTHON-VERSION`  
An optional python version to use instead of the version from the detected environment.

`-g, --force-generate`  
Force generating "requirements.txt", even if it already exists.

`-r, --requirements-file: FILE`  
Path to requirements file listing the project dependencies. Any file compatible with requirements.txt format, uv.lock, or pyproject.toml is accepted, a requirements.txt.lock retrieved with `rsconnect content get-lockfile` is also supported. Must be inside the project directory.

`--package-installer: CHOICE`  
Select the Python package installer for installs in the manifest. By default, behavior is server-driven.

`-v, --verbose`  
Print detailed messages

`-e, --entrypoint: TEXT`  
The module and executable object which serves as the entry point.

`-x, --exclude: TEXT`  
Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try to expand this which will not do what you expect. Generally, it's safest to quote the pattern. This option may be repeated.

`-m, --multi-notebook`  
Set the manifest for multi-notebook mode.

`-I, --image: TEXT`  
Target image to be used during content build and execution. This option is only applicable if the Connect server is configured to use off-host execution.

`--disable-env-management`  
Shorthand to disable environment management for both Python and R.

`--disable-env-management-py`  
Disable Python environment management for this bundle. Connect will not create an environment or install packages. An administrator must install the required packages in the correct Python environment on the Connect server.

`--disable-env-management-r`  
Disable R environment management for this bundle. Connect will not create an environment or install packages. An administrator must install the required packages in the correct R environment on the Connect server.

`--exclude-renv`  
Skip renv.lock detection. R dependencies will not be added to the manifest, even when an renv.lock file is present (in the content directory or at RENV_PATHS_LOCKFILE).
