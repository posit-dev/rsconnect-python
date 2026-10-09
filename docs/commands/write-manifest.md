Generated manifests exclude `.rsconnect-python` directories and the configured
CLI credential directory, including symlink aliases and files supplied as
explicit extras. Keep application files outside that directory; generating
a manifest from inside it is rejected.

::: mkdocs-click
    :module: rsconnect.main
    :command: write_manifest
