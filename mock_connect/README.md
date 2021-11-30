## Mock RStudio Connect

This directory holds a mocked version of RStudio Connect to support testing.  This
works by providing a Docker container equipped with Python (and necessary support
libraries).  The container looks to the outside world like an installation of RStudio
Connect.

### Restrictions

- The mock RStudio Connect does not support HTTPS connections; only HTTP.
- Not all Connect endpoints are implemented; only those needed to verify `rsconnect-python`
  functionality.

## Data Handling

The mock server does everything in memory, rather than use an external database.  If you
want to see what's currently there, visit the root index page of the mock server
(`http://localhost:3939/` by default) and you'll see a dump of them.  This is useful in
seeing the results of updating APIs.

The server comes with only one predefined object defined, the "admin" user.  It does allow
you to preload data if you wish.  This is intended to provide support for specific testing
scenarios.  To preload data, create a JSON file containing the data you want loaded.  See
the provided [data file](data.json) for the basic structure.  Look at the
[data code file](mock_connect/data.py) file for supported attributes for each object.

If the JSON data for an object does not contain an `id` attribute, a unique one will be
automatically assigned.  As new objects are created, each ID is guaranteed to be unique.
For objects that have a `guid` attribute, these also are automatically filled in if not
provided.  All other attribute values (even creation dates) are the responsibility of
the data file.

The definition of a user in the preload data file may contain an extra attribute called
`api_key` to specify an API key for the user.

Once you have the JSON file with the data you want to preload, specify its name as the value
of the `PRE_FETCH_FILE` environment variable when invoking `make up` to start the server.

## The `Makefile`

The `Makefile` contains several useful targets.

- `image` -- This target builds the Docker image in which the mock Connect server will be run.
- `up` -- This target starts the Docker container, exposing the mock server on port `3939`.
  The container is started as a daemon.  The output of the server is directed to a file
  called `mock_connect.log` (use the `LOG_FILE` environment variable to change this).
- `down` -- This target stops the Docker container running the mock server.
- `clean` -- This target cleans up work files, like the log file.
- `sh` -- This target brings up the Docker container but dumps you into a `sh` shell rather
  than starting the mock server.

> **Note:**
> - There is no `all` target.
> - `make` without a target will run the `image` target.
> - There are no dependencies between targets.

## Future

In the future, the pre-fetch data file will also allow for tailoring server responses based
on request input.  This makes it significantly easier to simulate a variety of errors so
that non-happy paths may also be fully tested.
