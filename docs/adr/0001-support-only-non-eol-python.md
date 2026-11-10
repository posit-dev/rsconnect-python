# Support only non-EOL Python versions for the CLI

Since #920, the **CLI Python** is independent of the **content Python**: the CLI can be installed with `uv tool install` and only shells out to the content Python for its version and installed packages. So the CLI supports only Python versions that have not reached end-of-life. Each version is dropped in the next minor release after its EOL date, with a "Removed" CHANGELOG entry. Content can still target any Python version Connect supports. Support for old content Python versions is best-effort: we test the versions our tooling can readily provide and don't build special infrastructure for very old ones.

## Consequences

- Users on an EOL interpreter keep resolving to the last compatible release through `requires-python`. The upgrade check must therefore never tell them to install a release that excludes their interpreter.
- Packages that import rsconnect-python as a library (such as posit-cli and vetiver) silently stay on older releases until they raise their own floor.
