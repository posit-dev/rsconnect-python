`rsconnect-python` 1.4.3
--------------------------------------------------------------------------------
*   Finished being more distinguishing between a server that's not runnint Connect
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
