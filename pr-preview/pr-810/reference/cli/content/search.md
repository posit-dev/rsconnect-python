# rsconnect content search


``` bash
rsconnect content search [OPTIONS]
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect content search [OPTIONS]

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
      --published                     Search only published content.
      --unpublished                   Search only unpublished content.
      --content-type [unknown|shiny|rmd-static|rmd-shiny|static|api|tensorflow-saved-model|jupyter-static|python-api|python-dash|python-streamlit|python-bokeh|python-fastapi|quarto-shiny|quarto-static|python-shiny|jupyter-voila|python-gradio|python-panel|nodejs]
                                      Filter content results by content type.
      --r-version VERSIONSEARCHFILTER
                                      Filter content results by R version.
      --py-version VERSIONSEARCHFILTER
                                      Filter content results by Python version.
      --title-contains TEXT           Filter content results by title.
      --order-by [created|last_deployed]
                                      Order content results.
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

`--published`  
Search only published content.

`--unpublished`  
Search only unpublished content.

`--content-type: CHOICE`  
Filter content results by content type.

`--r-version: VERSIONSEARCHFILTER`  
Filter content results by R version.

`--py-version: VERSIONSEARCHFILTER`  
Filter content results by Python version.

`--title-contains: TEXT`  
Filter content results by title.

`--order-by: CHOICE`  
Order content results.
