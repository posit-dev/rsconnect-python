# Server Administration

Starting with the 2023.05 edition of Posit Connect, `rsconnect-python` can be
used to perform certain server administration tasks, such as instance managing
runtime caches. For more information on runtime caches in Posit Connect, see the
Connect Admin Guide's section on [runtime
caches](https://docs.posit.co/connect/admin/server-management/runtime-caches/).

Examples in this section will use `--name myserver` to stand in for your Connect
server information. See [Managing Server
Information](#managing-server-information) above for more details.

## Runtime Caches

### Enumerate Runtime Caches

*New in Connect 2023.05*

Use the command below to enumerate runtime caches on a Connect server. The
command will output a JSON object containing a list of runtime caches . Each
cache entry will contain the following information:

- `language`: The language of content that uses the cache, either R or Python.
- `version`: The language version of the content that uses the cache.
- `image_name`: The execution environment of the cache. The string `Local`
  denotes native execution. For Connect instances that use off-host execution,
  the name of the image that uses the cache will be displayed.

```bash
rsconnect system caches list --name myserver
# {
#   "caches": [
#     {
#       "language": "R",
#       "version": "3.6.3",
#       "image_name": "Local"
#     },
#     {
#       "language": "Python",
#       "version": "3.9.5",
#       "image_name": "Local"
#     },
#         {
#       "language": "R",
#       "version": "3.6.3",
#       "image_name": "rstudio/content-base:r3.6.3-py3.9.5-bionic"
#     },
#     {
#       "language": "Python",
#       "version": "3.9.5",
#       "image_name": "rstudio/content-base:r3.6.3-py3.9.5-bionic"
#     }
#   ]
# }
```

> **Note**
> The `image_name` field returned by the server will use sanitized versions
> of names.

### Delete Runtime Caches

*New in Connect 2023.05*

When Connect's execution environment changes, runtime caches may be invalidated.
In these cases, you will need to delete the affected runtime caches using the
`system caches delete` command.

> **Warning**
> After deleting a cache, the first time affected content is visited, Connect
> will need to reconstruct its environment. This can take a long time. To
> mitigate this, you can use the [`content build`](#content-build) command to
> rebuild affected content ahead of time. You may want to do this just for
> high-priority content, or for all content.

To delete a runtime cache, call the `system caches delete` command, specifying a
Connect server, as well as the language (`-l, --language`), version (`-V,
--version`), and image name (`-I, --image-name`) for the cache you wish to
delete. Deleting a large cache might take a while. The command will wait for
Connect to finish the task.

Use the following parameters specify the target cache:

- `language` (required) must name `R` or `Python`. It is case-insensitive.
- `version` (required) must be a three-part version number, e.g. `3.8.12`.
- `image-name` (optional) defaults to `Local`, which targets caches used for
  natively-executed content. Off-host images can be specified using either the
  literal image name or the sanitized name returned by the `list` command.

Use the dry run flag (`-d, --dry-run`) to surface any errors ahead of
deletion.

```bash
rsconnect system caches delete \
    --name myserver \
    --language Python \
    --version 3.9.5 \
    --image-name rstudio/content-base:r3.6.3-py3.9.5-bionic \
    --dry-run
# Dry run finished

rsconnect system caches delete \
    --name myserver \
    --language Python \
    --version 3.9.5 \
    --image-name rstudio/content-base:r3.6.3-py3.9.5-bionic
# Deleting runtime cache...
# Successfully deleted runtime cache
```

You should run these commands for each cache you wish to delete.

## Content subcommands

rsconnect-python supports multiple options for interacting with Posit Connect's
`/v1/content` API. Both administrators and publishers can use the content subcommands
to search, download, and rebuild content on Posit Connect without needing to access the
dashboard from a browser.

> **Note**
> The `rsconnect content` CLI subcommands are intended to be easily scriptable.
> The default output format is `JSON` so that the results can be easily piped into
> other command line utilities like [`jq`](https://stedolan.github.io/jq/) for further post-processing.

```bash
rsconnect content --help
# Usage: rsconnect content [OPTIONS] COMMAND [ARGS]...

#   Interact with Posit Connect's content API.

# Options:
#   --help  Show this message and exit.

# Commands:
#   build            Build content on Posit Connect.
#   describe         Describe a content item on Posit Connect.
#   download-bundle  Download a content item's source bundle.
#   search           Search for content on Posit Connect.
```

### Content Search

The `rsconnect content search` subcommands can be used by administrators and publishers
to find specific content on a given Posit Connect server. The search returns
metadata for each content item that meets the search criteria.

```bash
rsconnect content search --help
# Usage: rsconnect content search [OPTIONS]

# Options:
#   -n, --name TEXT                 The nickname of the Posit Connect server.
#   -s, --server TEXT               The URL for the Posit Connect server.
#   -k, --api-key TEXT              The API key to use to authenticate with
#                                   Posit Connect.

#   -i, --insecure                  Disable TLS certification/host validation.
#   -c, --cacert FILENAME           The path to trusted TLS CA certificates.
#   --published                     Search only published content.
#   --unpublished                   Search only unpublished content.
#   --content-type [unknown|shiny|rmd-static|rmd-shiny|static|api|tensorflow-saved-model|jupyter-static|python-api|python-dash|python-streamlit|python-bokeh|python-fastapi|python-gradio|quarto-shiny|quarto-static]
#                                   Filter content results by content type.
#   --r-version VERSIONSEARCHFILTER
#                                   Filter content results by R version.
#   --py-version VERSIONSEARCHFILTER
#                                   Filter content results by Python version.
#   --title-contains TEXT           Filter content results by title.
#   --order-by [created|last_deployed]
#                                   Order content results.
#   -v, --verbose                   Print detailed messages.
#   --help                          Show this message and exit.

rsconnect content search
# [
#   {
#     "max_conns_per_process": null,
#     "content_category": "",
#     "load_factor": null,
#     "cluster_name": "Local",
#     "description": "",
#     "bundle_id": "142",
#     "image_name": null,
#     "r_version": null,
#     "content_url": "https://connect.example.org:3939/content/4ffc819c-065c-420c-88eb-332db1133317/",
#     "connection_timeout": null,
#     "min_processes": null,
#     "last_deployed_time": "2021-12-02T18:09:11Z",
#     "name": "logs-api-python",
#     "title": "logs-api-python",
#     "created_time": "2021-07-19T19:17:32Z",
#     "read_timeout": null,
#     "guid": "4ffc819c-065c-420c-88eb-332db1133317",
#     "parameterized": false,
#     "run_as": null,
#     "py_version": "3.8.2",
#     "idle_timeout": null,
#     "app_role": "owner",
#     "access_type": "acl",
#     "app_mode": "python-api",
#     "init_timeout": null,
#     "id": "18",
#     "quarto_version": null,
#     "dashboard_url": "https://connect.example.org:3939/connect/#/apps/4ffc819c-065c-420c-88eb-332db1133317",
#     "run_as_current_user": false,
#     "owner_guid": "edf26318-0027-4d9d-bbbb-54703ebb1855",
#     "max_processes": null
#   },
#   ...
# ]
```

See [this section](#searching-for-content) for more comprehensive usage examples
of the available search flags.


### Content Build

> **Note**
> The `rsconnect content build` subcommand requires Posit Connect >= 2021.11.1

Posit Connect caches R and Python packages in the configured
[`Server.DataDir`](https://docs.posit.co/connect/admin/appendix/configuration/#Server.DataDir).
Under certain circumstances (examples below), these package caches can become stale
and need to be rebuilt. This refresh automatically occurs when a Posit Connect
user visits the content. You may wish to refresh some content before it is visited
because it is high priority or is not visited frequently (API content, emailed reports).
In these cases, it is possible to preemptively build specific content items using
the `rsconnect content build` subcommands. This way the user does not have to pay
the build cost when the content is accessed next.

The following are some common scenarios where performing a content build might be necessary:

- OS upgrade
- changes to gcc or libc libraries
- changes to Python or R installations
- switching from source to binary package repositories or vice versa

> **Note**
> The `content build` command is non-destructive, meaning that it does nothing to purge
> existing packrat/python package caches before a build. If you have an
> existing cache, it should be cleared prior to starting a content build.
> See the [migration documentation](https://docs.posit.co/connect/admin/appendix/cli/#migration) for details.

> **Note**
> You may use the [`rsconnect content search`](#content-search) subcommand to help
> identify high priority content items to build.

```bash
rsconnect content build --help
Usage: rsconnect content build [OPTIONS] COMMAND [ARGS]...

  Build content on Posit Connect. Requires Connect >= 2021.11.1

Options:
  --help  Show this message and exit.

Commands:
  add      Mark a content item for build. Use `build run` to invoke the build
           on the Connect server.

  history  Get the build history for a content item.
  logs     Print the logs for a content build.
  ls       List the content items that are being tracked for build on a given
           Connect server.

  rm       Remove a content item from the list of content that are tracked for
           build. Use `build ls` to view the tracked content.

  run      Start building content on a given Connect server.
```

To build a specific content item, first `add` it to the list of content that is
"tracked" for building using its GUID. Content that is "tracked" in the local state
may become out-of-sync with what exists remotely on the Connect server (the result of
`rsconnect content search`). When this happens, it is safe to remove the locally tracked
entries with `rsconnect content build rm`.

> **Note**
> Metadata for "tracked" content items is stored in a local directory called
> `rsconnect-build` which will be automatically created in your current working directory.
> You may set the environment variable `CONNECT_CONTENT_BUILD_DIR` to override this directory location.

```bash
# `add` the content to mark it as "tracked"
rsconnect content build add --guid 4ffc819c-065c-420c-88eb-332db1133317

# run the build which kicks off a cache rebuild on the server
rsconnect content build run

# once the build is complete, the content can be "untracked"
# this does not remove the content from the Connect server
# the entry is only removed from the local state file
rsconnect content build rm --guid 4ffc819c-065c-420c-88eb-332db1133317
```

> **Note**
> See [this section](#add-to-build-from-search-results) for
> an example of how to add multiple content items in bulk, from the results
> of a `rsconnect content search` command.

To view all currently "tracked" content items, use the `rsconnect content build ls` subcommand.

```bash
rsconnect content build ls
```

To view only the "tracked" content items that have not yet been built, use the `--status NEEDS_BUILD` flag.

```bash
rsconnect content build ls --status NEEDS_BUILD
```

Once the content items have been added, you may initiate a build
using the `rsconnect content build run` subcommand. This command will attempt to
build all "tracked" content that has the status `NEEDS_BUILD`.

> To re-run failed builds, use `rsconnect content build run --retry`. This will build
all tracked content in any of the following states: `[NEEDS_BUILD, ABORTED, ERROR, RUNNING]`.
>
> If you encounter an error indicating that a build operation is already in progress,
you can use `rsconnect content build run --force` to bypass the check and proceed with building content marked as `NEEDS_BUILD`.
Ensure no other build operation is actively running before using the `--force` option.

```bash
rsconnect content build run
# [INFO] 2021-12-14T13:02:45-0500 Initializing ContentBuildStore for https://connect.example.org:3939
# [INFO] 2021-12-14T13:02:45-0500 Starting content build (https://connect.example.org:3939)...
# [INFO] 2021-12-14T13:02:45-0500 Starting build: 4ffc819c-065c-420c-88eb-332db1133317
# [INFO] 2021-12-14T13:02:50-0500 Running = 1, Pending = 0, Success = 0, Error = 0
# [INFO] 2021-12-14T13:02:50-0500 Build succeeded: 4ffc819c-065c-420c-88eb-332db1133317
# [INFO] 2021-12-14T13:02:55-0500 Running = 0, Pending = 0, Success = 1, Error = 0
# [INFO] 2021-12-14T13:02:55-0500 1/1 content builds completed in 0:00:10
# [INFO] 2021-12-14T13:02:55-0500 Success = 1, Error = 0
# [INFO] 2021-12-14T13:02:55-0500 Content build complete.
```

Sometimes content builds will fail and require debugging by the publisher or administrator.
Use the `rsconnect content build ls` to identify content builds that resulted in errors
and inspect the build logs with the `rsconnect content build logs` subcommand.

```bash
rsconnect content build ls --status ERROR
# [INFO] 2021-12-14T13:07:32-0500 Initializing ContentBuildStore for https://connect.example.org:3939
# [
#   {
#     "rsconnect_build_status": "ERROR",
#     "last_deployed_time": "2021-12-02T18:09:11Z",
#     "owner_guid": "edf26318-0027-4d9d-bbbb-54703ebb1855",
#     "rsconnect_last_build_log": "/Users/david/code/posit/rsconnect-python/rsconnect-build/logs/connect_example_org_3939/4ffc819c-065c-420c-88eb-332db1133317/pZoqfBoi6BgpKde5.log",
#     "guid": "4ffc819c-065c-420c-88eb-332db1133317",
#     "rsconnect_build_task_result": {
#       "user_id": 1,
#       "error": "Cannot find compatible environment: no compatible Local environment with Python version 3.9.5",
#       "code": 1,
#       "finished": true,
#       "result": {
#         "data": "An error occurred while building the content",
#         "type": "build-failed-error"
#       },
#       "id": "pZoqfBoi6BgpKde5"
#     },
#     "dashboard_url": "https://connect.example.org:3939/connect/#/apps/4ffc819c-065c-420c-88eb-332db1133317",
#     "name": "logs-api-python",
#     "title": "logs-api-python",
#     "content_url": "https://connect.example.org:3939/content/4ffc819c-065c-420c-88eb-332db1133317/",
#     "bundle_id": "141",
#     "rsconnect_last_build_time": "2021-12-14T18:07:16Z",
#     "created_time": "2021-07-19T19:17:32Z",
#     "app_mode": "python-api"
#   }
# ]

rsconnect content build logs --guid 4ffc819c-065c-420c-88eb-332db1133317
# [INFO] 2021-12-14T13:09:27-0500 Initializing ContentBuildStore for https://connect.example.org:3939
# Building Python API...
# Cannot find compatible environment: no compatible Local environment with Python version 3.9.5
# Task failed. Task exited with status 1.
```

Once a build for a piece of tracked content is complete, it can be safely removed from the list of "tracked"
content by using `rsconnect content build rm` command. This command accepts a `--guid` argument to specify
which piece of content to remove. Removing the content from the list of tracked content simply removes the item
from the local state file, the content deployed to the server remains unchanged.

```bash
rsconnect content build rm --guid 4ffc819c-065c-420c-88eb-332db1133317
```

### Rebuilding lots of content

When attempting to rebuild a long list of content, it is recommended to first build a sub-set of the content list.
First choose 1 or 2 Python and R content items for each version of Python and R on the server. Try to choose content
items that have the most dependencies in common with other content items on the server. Build these content items
first with the `rsconnect content build run` command. This will "warm" the Python and R environment cache for subsequent
content builds. Once these initial builds are complete, add the remaining content items to the list of "tracked" content
and execute another `rsconnect content build run` command.

To execute multiple content builds simultaniously, use the `rsconnect content build run --parallelism` flag to increase the
number of concurrent builds. By default, each content item is built serially. Increasing the build parallelism can reduce the total
time needed to rebuild a long list of content items. We recommend starting with a low parallelism setting (2-3) and increasing
from there to avoid overloading the Connect server with concurrent build operations. Remember that these builds are executing on the
Connect server which consumes CPU, RAM, and i/o bandwidth that would otherwise we allocated for Python and R applications
running on the server.

### Usage Examples

#### Searching for content

The following are some examples of how publishers might use the
`rsconnect content search` subcommand to find content on Posit Connect.
By default, the `rsconnect content search` command will return metadata for ALL
of the content on a Posit Connect server, both published and unpublished content.

> **Note**
> When using the `--r-version` and `--py-version` flags, users should
> make sure to quote the arguments to avoid conflicting with your shell. For
> example, bash would interpret `--py-version >3.0.0` as a shell redirect because of the
> unquoted `>` character.

```bash
# return only published content
rsconnect content search --published

# return only unpublished content
rsconnect content search --unpublished

# return published content where the python version is at least 3.9.0
rsconnect content search --published --py-version ">=3.9.0"

# return published content where the R version is exactly 3.6.3
rsconnect content search --published --r-version "==3.6.3"

# return published content where the content type is a static RMD
rsconnect content search --content-type rmd-static

# return published content where the content type is either shiny OR fast-api
rsconnect content search --content-type shiny --content-type python-fastapi

# return all content, published or unpublished, where the title contains the
# text "Stock Report"
rsconnect content search --title-contains "Stock Report"

# return published content, results are ordered by when the content was last
# deployed
rsconnect content search --published --order-by last_deployed

# return published content, results are ordered by when the content was
# created
rsconnect content search --published --order-by created
```

#### Finding R and Python versions

One common use for the `search` command might be to find the versions of
R and python that are currently in use on your Posit Connect server before a migration.

```bash
# search for all published content and print the unique r and python version
# combinations
rsconnect content search --published | jq -c '.[] | {py_version,r_version}' | sort |
uniq
# {"py_version":"3.8.2","r_version":"3.5.3"}
# {"py_version":"3.8.2","r_version":"3.6.3"}
# {"py_version":"3.8.2","r_version":null}
# {"py_version":null,"r_version":"3.5.3"}
# {"py_version":null,"r_version":"3.6.3"}
# {"py_version":null,"r_version":null}
```

#### Finding recently deployed content

```bash
# return only the 10 most recently deployed content items
rsconnect content search \
    --order-by last_deployed \
    --published | jq -c 'limit(10; .[]) | { guid, last_deployed_time }'
# {"guid":"4ffc819c-065c-420c-88eb-332db1133317","last_deployed_time":"2021-12-02T18:09:11Z"}
# {"guid":"aa2603f8-1988-484f-a335-193f2c57e6c4","last_deployed_time":"2021-12-01T20:56:07Z"}
# {"guid":"051252f0-4f70-438f-9be1-d818a3b5f8d9","last_deployed_time":"2021-12-01T20:37:01Z"}
# {"guid":"015143da-b75f-407c-81b1-99c4a724341e","last_deployed_time":"2021-11-30T16:56:21Z"}
# {"guid":"bcc74209-3a81-4b9c-acd5-d24a597c256c","last_deployed_time":"2021-11-30T15:51:07Z"}
# {"guid":"f21d7767-c99e-4dd4-9b00-ff8ec9ae2f53","last_deployed_time":"2021-11-23T18:46:28Z"}
# {"guid":"da4f709c-c383-4fbc-89e2-f032b2d7e91d","last_deployed_time":"2021-11-23T18:46:28Z"}
# {"guid":"9180809d-38fd-4730-a0e0-8568c45d87b7","last_deployed_time":"2021-11-23T15:16:19Z"}
# {"guid":"2b1d2ab8-927d-4956-bbf9-29798d039bc5","last_deployed_time":"2021-11-22T18:33:17Z"}
# {"guid":"c96db3f3-87a1-4df5-9f58-eb109c397718","last_deployed_time":"2021-11-19T20:25:33Z"}
```

#### Add to build from search results

One common use case might be to `rsconnect content build add` content for build
based on the results of a `rsconnect content search`. For example:

```bash
# search for all API type content, then
# for each guid, add it to the "tracked" content items
for guid in $(rsconnect content search \
        --published \
        --content-type python-api \
        --content-type api | jq -r '.[].guid'); do
    rsconnect content build add --guid $guid
done
```

Adding content items one at a time can be a slow operation. This is because
`rsconnect content build add` must fetch metadata for each content item before it
is added to the "tracked" content items. By providing multiple `--guid` arguments
to the `rsconnect content build add` subcommand, we can fetch metadata for multiple content items
in a single api call, which speeds up the operation significantly.

```bash
# write the guid of every published content item to a file called guids.txt
rsconnect content search --published | jq '.[].guid' > guids.txt

# bulk-add from the guids.txt with a single `rsconnect content build add` command
xargs printf -- '-g %s\n' < guids.txt | xargs rsconnect content build add
```
