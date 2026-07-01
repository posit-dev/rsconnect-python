# rsconnect content build


Build content on Posit Connect.


``` bash
rsconnect content build COMMAND [ARGS]...
```


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect content build [OPTIONS] COMMAND [ARGS]...

      Build content on Posit Connect.

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


# Commands


`add`  
[Mark a content item for build. Use `build run` to invoke the build on the Connect server.](../../../reference/cli/content/build/add.md)

`rm`  
[Remove a content item from the list of content that are tracked for build. Use `build ls` to view the tracked content.](../../../reference/cli/content/build/rm.md)

`ls`  
[List the content items that are being tracked for build on a given Connect server.](../../../reference/cli/content/build/ls.md)

`history`  
[Get the build history for a content item.](../../../reference/cli/content/build/history.md)

`logs`  
[Print the logs for a content build.](../../../reference/cli/content/build/logs.md)

`run`  
[Start building content on a given Connect server.](../../../reference/cli/content/build/run.md)
