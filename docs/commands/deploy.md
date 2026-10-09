Generated bundles exclude `.rsconnect-python` directories and the configured
CLI credential directory, including symlink aliases and files supplied as
explicit extras. Keep application files outside that directory; publishing
from inside it is rejected.

Deploying an already prepared bundle uploads the archive as supplied. Check its
contents before deployment.

::: mkdocs-click
    :module: rsconnect.main
    :command: deploy
