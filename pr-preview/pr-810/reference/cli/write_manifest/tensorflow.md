# rsconnect write-manifest tensorflow


Create a manifest.json file for a TensorFlow model for later deployment. All files are created in the same directory as the content. Requires Posit Connect 2024.05.0 or later.


``` bash
rsconnect write-manifest tensorflow [OPTIONS] DIRECTORY [EXTRA_FILES]...
```


DIRECTORY is the path to a directory containing a TensorFlow model.


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect write-manifest tensorflow [OPTIONS] DIRECTORY
                                               [EXTRA_FILES]...

      Create a manifest.json file for a TensorFlow model for later deployment. All
      files are created in the same directory as the content. Requires Posit
      Connect 2024.05.0 or later.

      DIRECTORY is the path to a directory containing a TensorFlow model.

    Options:
      -o, --overwrite     Overwrite manifest.json, if it exists.
      -x, --exclude TEXT  Specify a glob pattern for ignoring files when building
                          the bundle. Note that your shell may try to expand this
                          which will not do what you expect. Generally, it's
                          safest to quote the pattern. This option may be
                          repeated.
      -v, --verbose       Print detailed messages
      -I, --image TEXT    Target image to be used during content build and
                          execution. This option is only applicable if the Connect
                          server is configured to use off-host execution.
      --help              Show this message and exit.


# Arguments


`DIRECTORY: DIRECTORY`  
Required.

`EXTRA_FILES: FILE`  
Optional.


# Options


`-o, --overwrite`  
Overwrite manifest.json, if it exists.

`-x, --exclude: TEXT`  
Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try to expand this which will not do what you expect. Generally, it's safest to quote the pattern. This option may be repeated.

`-v, --verbose`  
Print detailed messages

`-I, --image: TEXT`  
Target image to be used during content build and execution. This option is only applicable if the Connect server is configured to use off-host execution.
