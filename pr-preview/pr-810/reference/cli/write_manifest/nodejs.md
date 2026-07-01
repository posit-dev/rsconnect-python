# rsconnect write-manifest nodejs


Create a manifest.json file for a Node.js application for later deployment. All files are created in the same directory as the application code.


``` bash
rsconnect write-manifest nodejs [OPTIONS] DIRECTORY [EXTRA_FILES]...
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect write-manifest nodejs [OPTIONS] DIRECTORY [EXTRA_FILES]...

      Create a manifest.json file for a Node.js application for later deployment.
      All files are created in the same directory as the application code.

    Options:
      -o, --overwrite                Overwrite manifest.json, if it exists.
      -e, --entrypoint TEXT          The JavaScript or TypeScript file that serves
                                     as the entry point for the application (e.g.,
                                     app.js, server.ts). Auto-detected from
                                     package.json if not specified.
      -x, --exclude TEXT             Specify a glob pattern for ignoring files
                                     when building the bundle. Note that your
                                     shell may try to expand this which will not
                                     do what you expect. Generally, it's safest to
                                     quote the pattern. This option may be
                                     repeated.
      --node PATH                    Path to the Node.js executable whose version
                                     should be used.
      -I, --image TEXT               Target image to be used during content build
                                     and execution. This option is only applicable
                                     if the Connect server is configured to use
                                     off-host execution.
      --disable-env-management-node  Disable Node.js environment management for
                                     this bundle.
      -v, --verbose                  Print detailed messages
      --help                         Show this message and exit.


# Arguments


`DIRECTORY: DIRECTORY`  
Required.

`EXTRA_FILES: FILE`  
Optional.


# Options


`-o, --overwrite`  
Overwrite manifest.json, if it exists.

`-e, --entrypoint: TEXT`  
The JavaScript or TypeScript file that serves as the entry point for the application (e.g., app.js, server.ts). Auto-detected from package.json if not specified.

`-x, --exclude: TEXT`  
Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try to expand this which will not do what you expect. Generally, it's safest to quote the pattern. This option may be repeated.

`--node: PATH`  
Path to the Node.js executable whose version should be used.

`-I, --image: TEXT`  
Target image to be used during content build and execution. This option is only applicable if the Connect server is configured to use off-host execution.

`--disable-env-management-node`  
Disable Node.js environment management for this bundle.

`-v, --verbose`  
Print detailed messages
