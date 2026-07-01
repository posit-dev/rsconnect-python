# rsconnect deploy git


Deploy content to Posit Connect directly from a remote Git repository. The repository must contain a manifest.json file (in the root or specified subdirectory). Connect will regularly poll the repository for updates.


``` bash
rsconnect deploy git [OPTIONS]
```


This command creates a new git`-b`acked content item. To update an existing git`-b`acked content item, use the `--app-id` option with the content's GUID.


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect deploy git [OPTIONS]

      Deploy content to Posit Connect directly from a remote Git repository. The
      repository must contain a manifest.json file (in the root or specified
      subdirectory). Connect will regularly poll the repository for updates.

      This command creates a new git-backed content item. To update an existing
      git-backed content item, use the --app-id option with the content's GUID.

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
      -r, --repository TEXT           URL of the Git repository (https:// URLs
                                      only).  [required]
      -b, --branch TEXT               Branch to deploy from. [default: main]
      -d, --subdirectory TEXT         Subdirectory containing manifest.json. Use
                                      path syntax (e.g., 'path/to/content').
      --polling / --no-polling        Enable/disable regular polling of the
                                      repository for updates. [default: enabled]
      --help                          Show this message and exit.


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

`-r, --repository: TEXT`  
**Required.** URL of the Git repository (https:// URLs only).

`-b, --branch: TEXT = main`  
Branch to deploy from. \[default: main\]

`-d, --subdirectory: TEXT =`  
Subdirectory containing manifest.json. Use path syntax (e.g., `path/to/content`).

`--polling, --no-polling`  
Enable/disable regular polling of the repository for updates. \[default: enabled\]
