# rsconnect content venv


Create a ENV_PATH Python virtual environment that mimics the environment of a deployed content item on Posit Connect. This will use the `uv` tool to locally create and manage the virtual environment. If the required Python version isn't already installed, uv will download it automatically.


``` bash
rsconnect content venv [OPTIONS] ENV_PATH
```


run it from the directory of a deployed content item to auto-detect the GUID, or provide the `--guid` option to specify a content item explicitly.


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect content venv [OPTIONS] ENV_PATH

      Create a ENV_PATH Python virtual environment that mimics the environment of
      a deployed content item on Posit Connect. This will use the 'uv' tool to
      locally create and manage the virtual environment. If the required Python
      version isn't already installed, uv will download it automatically.

      run it from the directory of a deployed content item to auto-detect the
      GUID, or provide the --guid option to specify a content item explicitly.

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
      -g, --guid TEXT                 The GUID of a content item whose lockfile
                                      will be used to build the environment. If
                                      omitted, rsconnect will try to auto-detect
                                      the last deployed GUID for the current
                                      server from local deployment metadata.
      --help                          Show this message and exit.


# Arguments


`ENV_PATH: PATH`  
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

`-g, --guid: STRIPPEDSTRING`  
The GUID of a content item whose lockfile will be used to build the environment. If omitted, rsconnect will try to auto-detect the last deployed GUID for the current server from local deployment metadata.
