# rsconnect-python

The command-line interface for deploying Python content to Posit Connect and related deployment targets.

## Language

### Python interpreters

**CLI Python**:
The interpreter that runs rsconnect-python itself, including environment inspection.
_Avoid_: host Python, rsconnect's Python

**Content Python**:
The interpreter the deployed content targets, whose version and packages are recorded in the manifest.
_Avoid_: app Python, project Python, target Python

**Publishable Python**:
A Python installation on Posit Connect that the server permits for new content. An installed Python is not necessarily
publishable.
