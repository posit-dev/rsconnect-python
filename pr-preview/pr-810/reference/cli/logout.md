# rsconnect logout


Remove locally`-s`tored OAuth credentials for a Posit Connect server. The server is identified by a positional SERVER argument, `-s`/`--server`, or `-n`/`--name`. The server entry is preserved (for re-login without re-registration); use `rsconnect remove` to delete the entry entirely.


``` bash
rsconnect logout [OPTIONS] [SERVER]
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect logout [OPTIONS] SERVER

      Remove locally-stored OAuth credentials for a Posit Connect server. The
      server is identified by a positional SERVER argument, -s/--server, or
      -n/--name. The server entry is preserved (for re-login without re-
      registration); use 'rsconnect remove' to delete the entry entirely.

    Options:
      -n, --name TEXT    The nickname of the Posit Connect server to log out from.
      -s, --server TEXT  The URL of the Posit Connect server to log out from.
      -v, --verbose      Enable verbose output. Use -vv for very verbose (debug)
                         output.
      --help             Show this message and exit.


# Arguments


`SERVER: TEXT`  
Optional.


# Options


`-n, --name: TEXT`  
The nickname of the Posit Connect server to log out from.

`-s, --server: TEXT`  
The URL of the Posit Connect server to log out from.

`-v, --verbose: INTEGER RANGE = 0`  
Enable verbose output. Use `-v`v for very verbose (debug) output.
