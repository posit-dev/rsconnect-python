# rsconnect


This command line tool may be used to deploy various types of content to Posit Connect and shinyapps.io.


``` bash
rsconnect [OPTIONS] COMMAND [ARGS]...
```


The tool supports the notion of a simple nickname that represents the information needed to interact with a deployment target. Use the add, list and remove commands to manage these nicknames.

The information about an instance of Posit Connect includes its URL, the API key needed to authenticate against that instance, a flag that notes whether TLS certificate/host verification should be disabled and a path to a trusted CA certificate file to use for TLS. The last two items are only relevant if the URL specifies the "https" protocol.

For shinyapps.io, the auth token, auth secret, server ('shinyapps.io'), and account are needed.


<span class="gd-details-chevron" aria-hidden="true"></span>Full --help output


    Usage: rsconnect [OPTIONS] COMMAND [ARGS]...

      This command line tool may be used to deploy various types of content to
      Posit Connect and shinyapps.io.

      The tool supports the notion of a simple nickname that represents the
      information needed to interact with a deployment target.  Use the add, list
      and remove commands to manage these nicknames.

      The information about an instance of Posit Connect includes its URL, the API
      key needed to authenticate against that instance, a flag that notes whether
      TLS certificate/host verification should be disabled and a path to a trusted
      CA certificate file to use for TLS.  The last two items are only relevant if
      the URL specifies the "https" protocol.

      For shinyapps.io, the auth token, auth secret, server ('shinyapps.io'), and
      account are needed.

    Options:
      --help  Show this message and exit.

    Commands:
      add             Define a nickname for a Posit Connect or shinyapps.io server
                      and credential.
      bootstrap       Create an initial admin user to bootstrap a Connect
                      instance.
      content         Interact with Posit Connect's content API.
      deploy          Deploy content to Posit Connect or shinyapps.io.
      details         Show details about a Posit Connect server.
      environment     Manage execution environments on Posit Connect.
      info            Show saved information about the specified deployment.
      integration     Manage OAuth integrations on Posit Connect.
      list            List the known Posit Connect servers.
      login           Authenticate with a Posit Connect server using OAuth.
      logout          Remove stored OAuth credentials for a Posit Connect server.
      quickstart      Scaffold a deployable Posit Connect project.
      remove          Remove the information about a Posit Connect server.
      system          Interact with Posit Connect's system API.
      version         Show the version of the rsconnect-python package.
      write-manifest  Create a manifest.json file for later deployment.


# Options


# Commands


`version`  
[Show the version of the rsconnect-python package.](../../reference/cli/version.md)

`bootstrap`  
[Create an initial admin user to bootstrap a Connect instance.](../../reference/cli/bootstrap.md)

`add`  
[Define a nickname for a Posit Connect or shinyapps.io server and credential.](../../reference/cli/add.md)

`list`  
[List the known Posit Connect servers.](../../reference/cli/list.md)

`details`  
[Show details about a Posit Connect server.](../../reference/cli/details.md)

`remove`  
[Remove the information about a Posit Connect server.](../../reference/cli/remove.md)

`login`  
[Authenticate with a Posit Connect server using OAuth.](../../reference/cli/login.md)

`logout`  
[Remove stored OAuth credentials for a Posit Connect server.](../../reference/cli/logout.md)

`info`  
[Show saved information about the specified deployment.](../../reference/cli/info.md)

`quickstart`  
[Scaffold a deployable Posit Connect project.](../../reference/cli/quickstart.md)

`deploy`  
[Deploy content to Posit Connect or shinyapps.io.](../../reference/cli/deploy.md)

`write-manifest`  
[Create a manifest.json file for later deployment.](../../reference/cli/write_manifest.md)

`content`  
[Interact with Posit Connect's content API.](../../reference/cli/content.md)

`system`  
[Interact with Posit Connect's system API.](../../reference/cli/system.md)

`environment`  
[Manage execution environments on Posit Connect.](../../reference/cli/environment.md)

`integration`  
[Manage OAuth integrations on Posit Connect.](../../reference/cli/integration.md)
