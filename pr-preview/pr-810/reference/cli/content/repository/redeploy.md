# rsconnect content repository redeploy


Trigger a new deployment from the git repository.


``` bash
rsconnect content repository redeploy [OPTIONS]
```


This creates a new bundle from the git repository and deploys it. Optionally specify a different ref (branch, tag, or commit) to deploy from.


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect content repository redeploy [OPTIONS]

      Trigger a new deployment from the git repository.

      This creates a new bundle from the git repository and deploys it. Optionally
      specify a different ref (branch, tag, or commit) to deploy from.

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
      -g, --guid GUID                 The GUID of the content item.  [required]
      -r, --ref TEXT                  Git ref to deploy from (branch, tag, or
                                      commit SHA). Uses the configured branch if
                                      not specified.
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

`-g, --guid: STRIPPEDSTRING`  
**Required.** The GUID of the content item.

`-r, --ref: TEXT`  
Git ref to deploy from (branch, tag, or commit SHA). Uses the configured branch if not specified.
