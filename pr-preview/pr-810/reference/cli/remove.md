# rsconnect remove


Remove the information about a Posit Connect server by nickname or URL. One of `--name` or `--server` is required.


``` bash
rsconnect remove [OPTIONS]
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect remove [OPTIONS]

      Remove the information about a Posit Connect server by nickname or URL. One
      of --name or --server is required.

    Options:
      -n, --name TEXT    The nickname of the Posit Connect server to remove.
      -s, --server TEXT  The URL of the Posit Connect server to remove.
      -v, --verbose      Enable verbose output. Use -vv for very verbose (debug)
                         output.
      --help             Show this message and exit.


# Options


`-n, --name: TEXT`  
The nickname of the Posit Connect server to remove.

`-s, --server: TEXT`  
The URL of the Posit Connect server to remove.

`-v, --verbose: INTEGER RANGE = 0`  
Enable verbose output. Use `-v`v for very verbose (debug) output.
