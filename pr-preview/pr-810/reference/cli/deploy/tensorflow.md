# rsconnect deploy tensorflow


Deploy a TensorFlow model to Posit Connect. Requires Posit Connect 2024.05.0 or later.


``` bash
rsconnect deploy tensorflow [OPTIONS] DIRECTORY [EXTRA_FILES]...
```


DIRECTORY is the path containing a TensorFlow model.


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect deploy tensorflow [OPTIONS] DIRECTORY [EXTRA_FILES]...

      Deploy a TensorFlow model to Posit Connect. Requires Posit Connect 2024.05.0
      or later.

      DIRECTORY is the path containing a TensorFlow model.

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
      -x, --exclude TEXT              Specify a glob pattern for ignoring files
                                      when building the bundle. Note that your
                                      shell may try to expand this which will not
                                      do what you expect. Generally, it's safest
                                      to quote the pattern. This option may be
                                      repeated.
      --help                          Show this message and exit.


# Arguments


`DIRECTORY: DIRECTORY`  
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

`-x, --exclude: TEXT`  
Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try to expand this which will not do what you expect. Generally, it's safest to quote the pattern. This option may be repeated.
