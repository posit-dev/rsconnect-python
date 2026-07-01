# rsconnect deploy voila


Deploy a Jupyter notebook in Voila mode to Posit Connect.


``` bash
rsconnect deploy voila [OPTIONS] PATH [EXTRA_FILES]...
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect deploy voila [OPTIONS] PATH [EXTRA_FILES]...

      Deploy a Jupyter notebook in Voila mode to Posit Connect.

    Options:
      -n, --name TEXT                 The nickname of the Posit Connect server to
                                      deploy to.
      -s, --server TEXT               The URL for the Posit Connect server to
                                      deploy to. (Also settable via CONNECT_SERVER
                                      environment variable.)
      -k, --api-key TEXT              The API key to use to authenticate with
                                      Posit Connect. (Also settable via
                                      CONNECT_API_KEY environment variable.)
      -i, --insecure                  Disable TLS certification/host validation.
                                      (Also settable via CONNECT_INSECURE
                                      environment variable.)
      -c, --cacert FILE               The path to trusted TLS CA certificates.
                                      (Also settable via CONNECT_CA_CERTIFICATE
                                      environment variable.)
      -v, --verbose                   Enable verbose output. Use -vv for very
                                      verbose (debug) output.
      --snowflake-connection-name TEXT
                                      The name of the Snowflake connection in the
                                      configuration file
      -N, --new                       Force a new deployment, even if there is
                                      saved metadata from a previous deployment.
                                      Cannot be used with --app-id.
      -a, --app-id TEXT               Existing app ID or GUID to replace. Cannot
                                      be used with --new.
      -t, --title TEXT                Title of the content (default is the same as
                                      the filename).
      -E, --environment TEXT          Set an environment variable. Specify a value
                                      with NAME=VALUE, or just NAME to use the
                                      value from the local environment. May be
                                      specified multiple times. [v1.8.6+]
      --no-verify                     Don't access the deployed content to verify
                                      that it started correctly. Implies
                                      activating the new bundle immediately rather
                                      than verifying it first.
      --draft                         Deploy the application as a draft and verify
                                      it, but do not activate it. The previous
                                      bundle will continue to be served until the
                                      draft is published.
      --metadata TEXT                 Include metadata key-value pair with the
                                      bundle upload. Use format: key=value. May be
                                      specified multiple times. Use key= (empty
                                      value) to clear a detected value. Forces
                                      metadata upload even on older servers that
                                      don't officially support it. [v2025.12.0+]
      --no-metadata                   Disable automatic git metadata detection and
                                      upload.
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
      -e, --entrypoint TEXT           The module and executable object which
                                      serves as the entry point.
      -m, --multi-notebook            Deploy in multi-notebook mode.
      -x, --exclude TEXT              Specify a glob pattern for ignoring files
                                      when building the bundle. Note that your
                                      shell may try to expand this which will not
                                      do what you expect. Generally, it's safest
                                      to quote the pattern. This option may be
                                      repeated.
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
      --help                          Show this message and exit.


# Arguments


`PATH: PATH`  
Required.

`EXTRA_FILES: FILE`  
Optional.


# Options


`-n, --name: TEXT`  
The nickname of the Posit Connect server to deploy to.

`-s, --server: TEXT`  
The URL for the Posit Connect server to deploy to. (Also settable via CONNECT_SERVER environment variable.) Environment variable: `CONNECT_SERVER`.

`-k, --api-key: TEXT`  
The API key to use to authenticate with Posit Connect. (Also settable via CONNECT_API_KEY environment variable.) Environment variable: `CONNECT_API_KEY`.

`-i, --insecure`  
Disable TLS certification/host validation. (Also settable via CONNECT_INSECURE environment variable.) Environment variable: `CONNECT_INSECURE`.

`-c, --cacert: FILE`  
The path to trusted TLS CA certificates. (Also settable via CONNECT_CA_CERTIFICATE environment variable.) Environment variable: `CONNECT_CA_CERTIFICATE`.

`-v, --verbose: INTEGER RANGE = 0`  
Enable verbose output. Use `-v`v for very verbose (debug) output.

`--snowflake-connection-name: TEXT`  
The name of the Snowflake connection in the configuration file

`-N, --new`  
Force a new deployment, even if there is saved metadata from a previous deployment. Cannot be used with `--app-id`.

`-a, --app-id: TEXT`  
Existing app ID or GUID to replace. Cannot be used with `--new`.

`-t, --title: TEXT`  
Title of the content (default is the same as the filename).

`-E, --environment: TEXT`  
Set an environment variable. Specify a value with NAME=VALUE, or just NAME to use the value from the local environment. May be specified multiple times. \[v1.8.6+\]

`--no-verify`  
Don't access the deployed content to verify that it started correctly. Implies activating the new bundle immediately rather than verifying it first.

`--draft`  
Deploy the application as a draft and verify it, but do not activate it. The previous bundle will continue to be served until the draft is published.

`--metadata: TEXT`  
Include metadata key`-v`alue pair with the bundle upload. Use format: key=value. May be specified multiple times. Use key= (empty value) to clear a detected value. Forces metadata upload even on older servers that don't officially support it. \[v2025.12.0+\]

`--no-metadata`  
Disable automatic git metadata detection and upload.

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

`-e, --entrypoint: TEXT`  
The module and executable object which serves as the entry point.

`-m, --multi-notebook`  
Deploy in multi`-n`otebook mode.

`-x, --exclude: TEXT`  
Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try to expand this which will not do what you expect. Generally, it's safest to quote the pattern. This option may be repeated.

`-p, --python: PATH`  
Path to Python interpreter whose environment should be used. The Python environment must have the rsconnect package installed.

`--override-python-version: PYTHON-VERSION`  
An optional python version to use instead of the version from the detected environment.

`-g, --force-generate`  
Force generating "requirements.txt", even if it already exists.

`-r, --requirements-file: FILE = requirements.txt`  
Path to requirements file listing the project dependencies. Any file compatible with requirements.txt format, uv.lock, or pyproject.toml is accepted, a requirements.txt.lock retrieved with `rsconnect content get-lockfile` is also supported. Must be inside the project directory.

`--package-installer: CHOICE`  
Select the Python package installer for installs in the manifest. By default, behavior is server-driven.
