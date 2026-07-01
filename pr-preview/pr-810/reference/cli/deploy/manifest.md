# rsconnect deploy manifest


Deploy content to Posit Connect or shinyapps.io using an existing manifest.json file. The specified file must either be named "manifest.json" or refer to a directory that contains a file named "manifest.json".


``` bash
rsconnect deploy manifest [OPTIONS] FILE
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect deploy manifest [OPTIONS] FILE

      Deploy content to Posit Connect or shinyapps.io using an existing
      manifest.json file.  The specified file must either be named "manifest.json"
      or refer to a directory that contains a file named "manifest.json".

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
      -A, --account TEXT              The shinyapps.io account name. (Also
                                      settable via SHINYAPPS_ACCOUNT environment
                                      variable.)
      -T, --token TEXT                The shinyapps.io token. (Also settable via
                                      SHINYAPPS_TOKEN or RSCLOUD_TOKEN environment
                                      variables.)
      -S, --secret TEXT               The shinyapps.io token secret. (Also
                                      settable via SHINYAPPS_SECRET or
                                      RSCLOUD_SECRET environment variables.)
      -V, --visibility [public|private]
                                      The visibility of the resource being
                                      deployed. (shinyapps.io only; must be public
                                      (default) or private)
      --help                          Show this message and exit.


# Arguments


`FILE: PATH`  
Required.


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

`-A, --account: TEXT`  
The shinyapps.io account name. (Also settable via SHINYAPPS_ACCOUNT environment variable.) Environment variable: `SHINYAPPS_ACCOUNT`.

`-T, --token: TEXT`  
The shinyapps.io token. (Also settable via SHINYAPPS_TOKEN or RSCLOUD_TOKEN environment variables.) Environment variable: `SHINYAPPS_TOKEN, RSCLOUD_TOKEN`.

`-S, --secret: TEXT`  
The shinyapps.io token secret. (Also settable via SHINYAPPS_SECRET or RSCLOUD_SECRET environment variables.) Environment variable: `SHINYAPPS_SECRET, RSCLOUD_SECRET`.

`-V, --visibility: CHOICE`  
The visibility of the resource being deployed. (shinyapps.io only; must be public (default) or private)
