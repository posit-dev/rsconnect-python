# The rsconnect-admin CLI

While the `rsconnect` CLI is meant for publishers, the `rsconnect-admin` CLI is
a tool meant for administrators of RStudio Connect.  `rsconnect-admin` allows administrators
to search for content and initiate content builds during a server migration.

The `rsconnect-admin` CLI uses the same server "nicknames" as the `rsconnect` CLI.
See [this section](./README.md#managing-server-information) of the main README
for details on adding a new RStudio Connect server.


### Search

The following are some examples of how an administrator might use the
`rsconnect-admin content search` subcommand to search for content on RStudio Connect.
This could be useful for administrators to identify content that needs to be
rebuilt during a server migration. See [this section](#building-content) for details
on when a content build might be necessary.

By default, the `rsconnect-admin content search` command will return metadata for ALL
of the content on a RStudio Connect server, both published and unpublished content.

```bash
# only published content
$ rsconnect-admin content search --published

# only unpublished content
$ rsconnect-admin content search --unpublished

# published content where the python version is at least 3.9.0
$ rsconnect-admin content search --published --py-version ">=3.9.0"

# published content where the R version is exactly 3.6.3
$ rsconnect-admin content search --published --r-version "==3.6.3"

# published content where the content type is a static RMD
$ rsconnect-admin content search --content-type rmd-static

# published content where the content type is either shiny OR fast-api
$ rsconnect-admin content search --content-type shiny --content-type python-fastapi

# any content, published or unpublished, where the title contains the text "Stock Report"
$ rsconnect-admin content search --title-contains "Stock Report"

# published content, results are ordered by when the content was last deployed
$ rsconnect-admin content search --published --order-by last_deployed

# published content, results are ordered by when the content was created
$ rsconnect-admin content search --published --order-by created
```


### Building Content

RStudio Connect caches R and Python packages in the configured
[`Server.DataDir`](https://docs.rstudio.com/connect/admin/appendix/configuration/#Server.DataDir).
Sometimes, these package caches become stale and need to be rebuilt. This refresh
occurs automatically when an RStudio Connect user visits the content via the
RStudio Connect dashboard. Some content, however, is high priority or not accessed
frequently via the dashboard (API content, emailed reports). In these cases, administrators
can preemptively build specific content items using the `rsconnect-admin build` subcommands.
This way the user does not have to pay the build cost when the content is accessed next.

The following are some common scenarios where performing a content build might be necessary:

- OS upgrade
- changes to gcc or libc libraries
- changes to Python or R installations
- switching from source to binary package repositories or vice versa
- migrating from local content execution to remote content execution with Kubernetes

Administrators should use the [`rsconnect-admin content search`](#search) subcommand to help
identify content items for building.

To build a specific content item, first `add` it to the list of content that is
"tracked" for building using its GUID.

```bash
# add a single content item by guid
$ rsconnect-admin build add --guid 4ffc819c-065c-420c-88eb-332db1133317
```

Administrators can view currently "tracked" content items using the
`rsconnect-admin build ls` subcommand.

```bash
# list all tracked content
$ rsconnect-admin build ls

# list tracked content that still needs to be built
$ rsconnect-admin build ls --status NEEDS_BUILD

# list tracked content that has already been built successfully
$ rsconnect-admin build ls --status COMPLETE

# list tracked content that failed to build
$ rsconnect-admin build ls --status=ERROR

# list tracked content that was cancelled while in progress
$ rsconnect-admin build ls --status=ABORTED
```

Once the content items have been "tracked", Administrators can initiate a build
using the `rsconnect-admin build run` subcommand. This command will attempt to
build all "tracked" content that has the status `NEEDS_BUILD`.

```bash
# build content serially
$ rsconnect-admin build run

# build content in parallel, 5 at a time
$ rsconnect-admin build run --parallelism 5
```

Sometimes content builds will fail. Use the `rsconnect-admin build ls` command
to identify content items that failed to build. Then use the `rsconnect-admin build logs`
subcommand to help identify the underlying reason for the failure.

```bash
# print latest build logs as raw text
$ rsconnect-admin build logs --guid 4ffc819c-065c-420c-88eb-332db1133317

# print latest build logs as json lines
$ rsconnect-admin build logs -f json --guid 4ffc819c-065c-420c-88eb-332db1133317
```

The `rsconnect-admin build history` subcommand can be used to list the build
history for a given content item.

```bash
$ rsconnect-admin build history --guid 4ffc819c-065c-420c-88eb-332db1133317
```

By default the `rsconnect-admin build logs` subcommand prints the logs of the
most recent build. To view the build logs for a specific build, provide a
`--task-id` to the `logs` subcommand.

```bash
$ rsconnect-admin build logs --guid 4ffc819c-065c-420c-88eb-332db1133317 --task-id GoTVLYxWkbvCo2bN
```


### Common Usage Examples

Many of the `rsconnect-admin` CLI subcommands are intended to be easily scriptable.
The default output format is `JSON` so that the results can be easily piped into
other command line utilities like [`jq`](https://stedolan.github.io/jq/)
for further post-processing.


#### Add from search results

One common use case might be to `rsconnect-admin build add` content for build
based on the results of a `rsconnect-admin content search`. For example:

```bash
# search for all API type content, then
# for each guid, add it to the "tracked" content items
$ for guid in $(rsconnect-admin \
content search \
--published \
--content-type python-api \
--content-type api | jq -r '.[].guid'); do \
rsconnect-admin build add --guid $guid; done
```

#### Bulk add with xargs

Adding content items one at a time can be a slow operation. This is because `rsconnect-admin` must
fetch metadata for each content item before it is added to the "tracked" content items.
By providing multiple `--guid` arguments to the `build add` subcommand, we can fetch metadata
for multiple content items in a single api call, which speeds up the operation sigificantly.

```bash
# write the guid of every published content item to a file called guids.txt
rsconnect-admin content search --published | jq '.[].guid' > guids.txt

# bulk-add from the guids.txt by executing a single `rsconnect-admin build add` command
xargs printf -- '-g %s\n' < guids.txt | xargs rsconnect-admin build add
```

#### Finding r and python versions

One common use for the `search` command might be to find the versions of
r and python that are currently in use on your RStudio Connect server before a migration.
This information can be used later to help define a set of content images
to be used with remote content execution on Kubernetes.

```bash
# search for all published content, then
# for each content item, print the unique r and python version combinations
$ rsconnect-admin content search --published | jq -c '{py: .[].py_version, r: .[].r_version}' | sort | uniq
{"py":"3.8.2","r":"3.5.3"}
{"py":"3.8.2","r":"3.6.3"}
{"py":"3.8.2","r":null}
{"py":null,"r":"3.5.3"}
{"py":null,"r":"3.6.3"}
{"py":null,"r":null}
```

#### Finding recently accessed content

TODO: Revisit the `search --order-by` flag and provide example of identifying
the 10 most recently deployed pieces of content:

```bash
$ rsconnect-admin content search --published | jq -c 'limit(10; .[]) | { guid: .guid, last_deployed: .last_deployed_time }'
{"guid":"4ffc819c-065c-420c-88eb-332db1133317","last_deployed":"2021-12-02T18:09:11Z"}
{"guid":"aa2603f8-1988-484f-a335-193f2c57e6c4","last_deployed":"2021-12-01T20:56:07Z"}
{"guid":"051252f0-4f70-438f-9be1-d818a3b5f8d9","last_deployed":"2021-12-01T20:37:01Z"}
{"guid":"015143da-b75f-407c-81b1-99c4a724341e","last_deployed":"2021-11-30T16:56:21Z"}
{"guid":"bcc74209-3a81-4b9c-acd5-d24a597c256c","last_deployed":"2021-11-30T15:51:07Z"}
{"guid":"f21d7767-c99e-4dd4-9b00-ff8ec9ae2f53","last_deployed":"2021-11-23T18:46:28Z"}
{"guid":"da4f709c-c383-4fbc-89e2-f032b2d7e91d","last_deployed":"2021-11-23T18:46:28Z"}
{"guid":"9180809d-38fd-4730-a0e0-8568c45d87b7","last_deployed":"2021-11-23T15:16:19Z"}
{"guid":"2b1d2ab8-927d-4956-bbf9-29798d039bc5","last_deployed":"2021-11-22T18:33:17Z"}
{"guid":"c96db3f3-87a1-4df5-9f58-eb109c397718","last_deployed":"2021-11-19T20:25:33Z"}
```
