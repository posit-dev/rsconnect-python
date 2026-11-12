# Architecture

A map of the `rsconnect/` package for agents working on deployment, bundling, or server code. Read the code for details; this file only tells you where to look.

## Deployment targets

Server classes subclass `AbstractRemoteServer` in `api.py`:

| Target                            | Server class         | Client / service                            |
| --------------------------------- | -------------------- | ------------------------------------------- |
| Posit Connect                     | `RSConnectServer`    | `RSConnectClient`                           |
| Posit Connect on Snowflake (SPCS) | `SPCSConnectServer`  | `RSConnectClient`                           |
| shinyapps.io                      | `ShinyappsServer`    | `PositClient`, `ShinyappsService`           |
| Posit Connect Cloud               | `ConnectCloudServer` | `ConnectCloudClient`, `ConnectCloudService` |

`S3Server` / `S3Client` handle bundle storage uploads; they are not a deployment target you can name on the command line.

`RSConnectExecutor` (in `api.py`) drives a deployment end to end and dispatches on the target.

## Modules

- **`main.py`**: Click CLI. Commands parse options and delegate to `actions*.py`, `bundle.py`, and `api.py`. The `deploy` and `write-manifest` groups have one subcommand per content type.
- **`api.py`**: server classes, HTTP clients, and `RSConnectExecutor`.
- **`actions.py`**: deployment helpers, `cli_feedback()`, and `quarto_inspect()`.
- **`actions_content.py`**: content management (search, build history, bundle download).
- **`actions_environment.py`**, **`actions_integration.py`**: public API for Connect execution environments and OAuth integrations.
- **`bundle.py`**: `Manifest` and `Bundle`, plus `make_*_bundle()` builders per content type (notebook, Quarto, HTML, TensorFlow, Voila, API, Node.js, from an existing manifest).
- **`models.py`**: `AppModes` (canonical content types) and `TypedDict` models for API payloads.
- **`metadata.py`**: on-disk stores. `ServerStore` holds saved server credentials in the platform config directory (see `config_dirname()`). `AppStore` records deployments, next to the content in an `rsconnect-python/` directory, falling back to the config directory.
- **`environment.py`**: Python environment detection. Runs `subprocesses/inspect_environment.py` under the CLI interpreter; the inspector queries the content interpreter for its version and installed packages.
- **`environment_node.py`**: Node.js/npm environment detection.
- **`preflight.py`**, **`preflight_node.py`**: checks that a Python or Node.js project is deployable before uploading.
- **`pyproject.py`**: reads Python version requirements from static project metadata.
- **`oauth.py`**, **`device_login.py`**: OAuth login (Connect and Connect Cloud). **`connect_cloud.py`**: Connect Cloud URLs and auth configuration.
- **`snowflake.py`**: wraps the `snow` CLI to list connections and generate JWTs for SPCS.
- **`json_web_token.py`**: JWT handling for `rsconnect bootstrap`.
- **`git_metadata.py`**: attaches git commit, branch, and remote URL metadata to bundle uploads.
- **`quickstart/`**: `rsconnect quickstart` project scaffolding.
- **`log.py`**: logger with a custom `VERBOSE` level between INFO and DEBUG.

## Posit Connect deployment flow

1. **Validate**: check the server connection and content files.
2. **Bundle**: write `manifest.json`, snapshot dependencies, tar the content.
3. **Create**: `POST v1/content` for new content, or reuse an existing content GUID.
4. **Upload**: `POST v1/content/{guid}/bundles`.
5. **Deploy**: `POST v1/content/{guid}/deploy` starts a server-side task.
6. **Wait**: `RSConnectClient.wait_for_task()` polls until the task finishes.
7. **Store**: record the deployment in `AppStore`.

Other targets follow the same shape through their own clients.

## Integrations

- **Quarto**: requires the `quarto` CLI. `quarto_inspect()` introspects Quarto documents and projects (`quarto-static` and `quarto-shiny` app modes).
- **Snowflake**: requires the `snow` CLI; see `snowflake.py`.
