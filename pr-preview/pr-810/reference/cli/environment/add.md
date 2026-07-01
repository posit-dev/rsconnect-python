# rsconnect environment add


``` bash
rsconnect environment add [OPTIONS] IMAGE
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect environment add [OPTIONS] IMAGE

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
      -T, --title TEXT                A human-readable title for the environment.
      -d, --description TEXT          A description for the environment.
      -m, --matching [any|exact|none]
                                      The image selection strategy.
      --supervisor TEXT               Path to the per-image supervisor script.
      --python TEXT                   A Python installation as VERSION=PATH.
                                      Example:
                                      3.11.6=/opt/python/3.11.6/bin/python
      --quarto TEXT                   A Quarto installation as VERSION=PATH.
                                      Example:
                                      1.4.555=/opt/quarto/1.4.555/bin/quarto
      --r TEXT                        An R installation as VERSION=PATH. Example:
                                      4.3.2=/opt/R/4.3.2/bin/R
      --tensorflow TEXT               A TensorFlow installation as VERSION=PATH.
                                      Example: 2.14.0=/opt/tensorflow/2.14.0
      --mount TEXT                    A volume mount as comma-separated key=value
                                      pairs. Required keys: type (nfs or pvc),
                                      target. NFS example: type=nfs,nfs_host=nas.e
                                      xample.com,nfs_export_path=/shared/data,targ
                                      et=/mnt/data. PVC example:
                                      type=pvc,pvc_name=my-
                                      claim,target=/mnt/storage,read_only=true
      --allow-user STRIPPEDSTRING     A user GUID to grant access.
      --allow-group STRIPPEDSTRING    A group GUID to grant access.
      --clear-permissions             Remove all existing permissions.
      --help                          Show this message and exit.


# Arguments


`IMAGE: TEXT`  
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

`-T, --title: TEXT`  
A human-readable title for the environment.

`-d, --description: TEXT`  
A description for the environment.

`-m, --matching: CHOICE`  
The image selection strategy.

`--supervisor: TEXT`  
Path to the per`-i`mage supervisor script.

`--python: TEXT`  
A Python installation as VERSION=PATH. Example: 3.11.6=/opt/python/3.11.6/bin/python

`--quarto: TEXT`  
A Quarto installation as VERSION=PATH. Example: 1.4.555=/opt/quarto/1.4.555/bin/quarto

`--r: TEXT`  
An R installation as VERSION=PATH. Example: 4.3.2=/opt/R/4.3.2/bin/R

`--tensorflow: TEXT`  
A TensorFlow installation as VERSION=PATH. Example: 2.14.0=/opt/tensorflow/2.14.0

`--mount: TEXT`  
A volume mount as comma`-s`eparated key=value pairs. Required keys: type (nfs or pvc), target. NFS example: type=nfs,nfs_host=nas.example.com,nfs_export_path=/shared/data,target=/mnt/data. PVC example: type=pvc,pvc_name=my`-c`laim,target=/mnt/storage,read_only=true

`--allow-user: STRIPPEDSTRING`  
A user GUID to grant access.

`--allow-group: STRIPPEDSTRING`  
A group GUID to grant access.

`--clear-permissions`  
Remove all existing permissions.
