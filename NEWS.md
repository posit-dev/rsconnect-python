Development version
--------------------------------------------------------------------------------
*   Added support for deploying Streamlit and Bokeh applications.

*   Expanded the default exclusion list to include common virtual environment
    directory names (`env`, `venv`, `.env`, and `.venv`).

*   Improved handling of HTTP timeouts.

*   Added the `--to-html` option to `nbconvert` when publishing a static notebook.
    This is required by the latest version of `nbconvert`.


`rsconnect-python` 1.4.5
--------------------------------------------------------------------------------
*   Provide clearer feedback when errors happen while building bundles from a
    manifest.

*   Fix output alignment under Python 2.

*   Pin required versions of the `click` and `six` libraries that we use.

*   Help text touch up.


`rsconnect-python` 1.4.4
--------------------------------------------------------------------------------
*   Converted a traceback to a more appropriate message.

*   Updated our `CookieJar` class to support marshalling/un-marshalling to/from
    a dictionary.

*   Corrected an issue with cookie jar continuity across connections.


`rsconnect-python` 1.4.3
--------------------------------------------------------------------------------
*   Finished being more distinguishing between a server that's not running Connect
    and a credentials problem.


`rsconnect-python` 1.4.2
--------------------------------------------------------------------------------
*   Added more helpful feedback when a "requested object does not exist" error is
    returned by Connect.

*   Fixed an issue where cookie header size could grow inappropriately (#107).

*   Be more distinguishing between a server that's not running Connect and a
    credentials problem.

*   Corrected the instructions to enable auto-completion.


`rsconnect-python` 1.4.1
--------------------------------------------------------------------------------
*   Fixed sticky sessions so we will track deploys correctly when RStudio Connect
    is in an HA/clustered environment.


`rsconnect-python` 1.4.0
--------------------------------------------------------------------------------
*   Command line handling of options is more consistent across all commands.

*   The `test` command has been replaced with a more broadly functional `details`
    command.

*   There are now functions in `actions` that provide the same functionality as the
    CLI.

*   Errors are now handled much more consistently and are more informative.

*   CLI output is more clean.

*   The overall code has been refactored and improved for clarity, testability and
    stability.

*   All CLI help has been improved for consistency, correctness and completeness.

*   Many documentation improvements in content and appearance.


`rsconnect-python` 1.3.0
--------------------------------------------------------------------------------
*   First release
