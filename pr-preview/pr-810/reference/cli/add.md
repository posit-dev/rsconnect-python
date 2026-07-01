# rsconnect add


Associate a simple nickname with the information needed to interact with a deployment target. Specifying an existing nickname will cause its stored information to be replaced by what is given on the command line.


``` bash
rsconnect add [OPTIONS]
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect add [OPTIONS]

      Associate a simple nickname with the information needed to interact with a
      deployment target. Specifying an existing nickname will cause its stored
      information to be replaced by what is given on the command line.

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
      -A, --account TEXT              The shinyapps.io account name. (Also
                                      settable via SHINYAPPS_ACCOUNT environment
                                      variable.)
      -T, --token TEXT                The shinyapps.io token. (Also settable via
                                      SHINYAPPS_TOKEN or RSCLOUD_TOKEN environment
                                      variables.)
      -S, --secret TEXT               The shinyapps.io token secret. (Also
                                      settable via SHINYAPPS_SECRET or
                                      RSCLOUD_SECRET environment variables.)
      --set-default                   Mark this server as the default (used when
                                      -n/--name and -s/--server are not
                                      specified).
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

`-A, --account: TEXT`  
The shinyapps.io account name. (Also settable via SHINYAPPS_ACCOUNT environment variable.) Environment variable: `SHINYAPPS_ACCOUNT`.

`-T, --token: TEXT`  
The shinyapps.io token. (Also settable via SHINYAPPS_TOKEN or RSCLOUD_TOKEN environment variables.) Environment variable: `SHINYAPPS_TOKEN, RSCLOUD_TOKEN`.

`-S, --secret: TEXT`  
The shinyapps.io token secret. (Also settable via SHINYAPPS_SECRET or RSCLOUD_SECRET environment variables.) Environment variable: `SHINYAPPS_SECRET, RSCLOUD_SECRET`.

`--set-default`  
Mark this server as the default (used when `-n`/`--name` and `-s`/`--server` are not specified).
