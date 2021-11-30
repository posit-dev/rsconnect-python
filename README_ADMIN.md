# The rsconnect-admin CLI

While the `rsconnect` CLI is meant for publishers, the `rsconnect-admin` CLI is
a tool meant for administrators of RStudio Connect.  `rsconnect-admin` allows administrators
to search for content and initiate content rebuilds during a server migration.

The `rsconnect-admin` CLI uses the same server "nicknames" as the `rsconnect` CLI.
See [this section](./README.md#managing-server-information) of the main README
for details on adding a new RStudio Connect server.


### Search

The following are some examples of how an administrator might use the
`rsconnect-admin content search` subcommand to search for content on RStudio Connect.
This could be useful for administrators to identify content that needs to be
rebuilt during a server migration. See the [rebuild section](#rebuild) for details
on when a content rebuild might be necessary.

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
```


### Rebuild

RStudio Connect caches R and Python packages in the configured
[`Server.DataDir`](https://docs.rstudio.com/connect/admin/appendix/configuration/#Server.DataDir).
Sometimes, these package caches become stale and need to be rebuilt. This refresh
occurs automatically when an RStudio Connect user visits the content via the
RStudio Connect dashboard. Some content, however, is high priority or not accessed
frequently via the dashboard (API content, emailed reports). In these cases, administrators
can preemptively rebuild specific content items using the `rsconnect-admin rebuild` subcommands.
This way the user does not have to pay the rebuild cost when the content is accessed next.

The following are some common scenarios where performing a content rebuild might be necessary:

- OS upgrade
- changes to gcc or libc libraries
- changes to Python or R installations
- switching from source to binary package repositories or vice versa
- migrating from local content execution to remote content execution with Kubernetes

Administrators should use the [`rsconnect-admin content search`](#search) subcommand to help
identify content items for rebuild.

To rebuild a specific content item, first `add` it to the list of content that is
"tracked" for rebuild using its GUID.

```bash
# add a single content item by guid
$ rsconnect-admin rebuild add --guid 4ffc819c-065c-420c-88eb-332db1133317
```

Administrators can view currently "tracked" content items using the
`rsconnect-admin rebuild ls` subcommand.

```bash
# list all tracked content
$ rsconnect-admin rebuild ls

# list tracked content that still needs to be rebuilt
$ rsconnect-admin rebuild ls --status NEEDS_REBUILD

# list tracked content that has already been rebuilt successfully
$ rsconnect-admin rebuild ls --status COMPLETE

# list tracked content that failed to rebuild
$ rsconnect-admin rebuild ls --status=ERROR

# list tracked content that was cancelled while in progress
$ rsconnect-admin rebuild ls --status=ABORTED
```

Once the content items have been "tracked", Administrators can initiate a rebuild
using the `rsconnect-admin rebuild run` subcommand. This command will attempt to
rebuild all "tracked" content that has the status `NEEDS_REBUILD`.

```bash
# rebuild content serially
$ rsconnect-admin rebuild run

# rebuild content in parallel, 5 at a time
$ rsconnect-admin rebuild run --parallelism 5
```

Sometimes content rebuilds will fail. Use the `rsconnect-admin rebuild ls` command
to identify content items that failed to rebuild. Then use the `rsconnect-admin rebuild logs`
subcommand to help identify the underlying reason for the failure.

```bash
# print latest rebuild logs as raw text
$ rsconnect-admin rebuild logs --guid 4ffc819c-065c-420c-88eb-332db1133317

# print latest rebuild logs as json lines
$ rsconnect-admin rebuild logs -f json --guid 4ffc819c-065c-420c-88eb-332db1133317
```

The `rsconnect-admin rebuild history` subcommand can be used to list the rebuild
history for a given content item.

```bash
$ rsconnect-admin rebuild history --guid 4ffc819c-065c-420c-88eb-332db1133317
```

By default the `rsconnect-admin rebuild logs` subcommand prints the logs of the
most recent rebuild. To view the rebuild logs for a specific rebuild, provide a
`--task-id` to the `logs` subcommand.

```bash
$ rsconnect-admin rebuild logs --guid 4ffc819c-065c-420c-88eb-332db1133317 --task-id GoTVLYxWkbvCo2bN
```


### Common Usage Examples

Many of the `rsconnect-admin` CLI subcommands are intended to be easily scriptable.
The default output format is `JSON` so that the results can be easily piped into
other command line utilities like [`jq`](https://stedolan.github.io/jq/)
for further post-processing.

One common use case might be to `rsconnect-admin rebuild add` content for rebuild
based on the results of a `rsconnect-admin content search`. For example:

```bash
# search for all API type content, then
# for each guid, add it to the "tracked" content items
$ for guid in $(rsconnect-admin \
content search \
--published \
--content-type python-api \
--content-type api | jq -r '.[].guid'); do \
rsconnect-admin rebuild add --guid $guid; done
```
