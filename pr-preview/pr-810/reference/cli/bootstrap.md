# rsconnect bootstrap


Creates an initial admin user to bootstrap a Connect instance. Returns the provisioned API key.


``` bash
rsconnect bootstrap [OPTIONS]
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect bootstrap [OPTIONS]

      Creates an initial admin user to bootstrap a Connect instance. Returns the
      provisioned API key.

    Options:
      -s, --server TEXT       The URL for the RStudio Connect server. (Also
                              settable via CONNECT_SERVER environment variable.)
                              [required]
      -i, --insecure          Disable TLS certification/host validation. (Also
                              settable via CONNECT_INSECURE environment variable.)
      -c, --cacert FILE       The path to trusted TLS CA certificates. (Also
                              settable via CONNECT_CA_CERTIFICATE environment
                              variable.)
      -j, --jwt-keypath TEXT  The path to the file containing the private key used
                              to sign the JWT.
      -r, --raw               Return the API key as raw output rather than a JSON
                              object
      -v, --verbose           Enable verbose output. Use -vv for very verbose
                              (debug) output.
      --help                  Show this message and exit.


# Options


`-s, --server: TEXT`  
**Required.** The URL for the RStudio Connect server. (Also settable via CONNECT_SERVER environment variable.) Environment variable: `CONNECT_SERVER`.

`-i, --insecure`  
Disable TLS certification/host validation. (Also settable via CONNECT_INSECURE environment variable.) Environment variable: `CONNECT_INSECURE`.

`-c, --cacert: FILE`  
The path to trusted TLS CA certificates. (Also settable via CONNECT_CA_CERTIFICATE environment variable.) Environment variable: `CONNECT_CA_CERTIFICATE`.

`-j, --jwt-keypath: TEXT`  
The path to the file containing the private key used to sign the JWT.

`-r, --raw`  
Return the API key as raw output rather than a JSON object

`-v, --verbose: INTEGER RANGE = 0`  
Enable verbose output. Use `-v`v for very verbose (debug) output.
