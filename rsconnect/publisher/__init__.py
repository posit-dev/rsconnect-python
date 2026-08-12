"""Interoperability with Posit Publisher's ``.posit/publish`` TOML files.

This package lets rsconnect-python read and write the same on-disk configuration
(``.posit/publish/<name>.toml``) and deployment-record
(``.posit/publish/deployments/<name>.toml``) files that the Posit Publisher
VS Code extension uses, so the two tools interoperate on the same project.

The format (schema URLs, field names, content-type map, serialization details)
is ported from the ``posit-dev/publisher`` project.
"""

from .service import (
    CONTENT_TYPES,
    ContentTypeSpec,
    InitRequest,
    InitResult,
    PublishRequest,
    PublishResult,
    initialize_project,
    publish_project,
)

__all__ = [
    "CONTENT_TYPES",
    "ContentTypeSpec",
    "InitRequest",
    "InitResult",
    "PublishRequest",
    "PublishResult",
    "initialize_project",
    "publish_project",
]
