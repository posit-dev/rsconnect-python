"""The ``.posit/publish/<name>.toml`` configuration file (the "what").

A config describes a piece of content independently of where it is deployed:
its content ``type``, ``entrypoint``, ``title``, the ``files`` include-patterns,
and language settings. rsconnect owns a handful of identity fields; everything
else it finds on disk (``connect.*`` runtime settings, ``secrets``, unknown
keys) is preserved on update via read-merge-write.
"""

from __future__ import annotations

import dataclasses
import os
import typing

from ..models import AppMode
from . import schema, serialize

# Keys rsconnect manages directly. Anything else found on disk is round-tripped
# untouched through ``PublisherConfig.extra``.
_MANAGED_KEYS = frozenset(
    {
        "$schema",
        "product_type",
        "type",
        "entrypoint",
        "source",
        "title",
        "description",
        "validate",
        "files",
        "has_parameters",
        "python",
        "quarto",
        "r",
        "jupyter",
        "environment",
        "secrets",
        "integration_requests",
        "connect",
        "connect_cloud",
    }
)


@dataclasses.dataclass
class PublisherConfig:
    """A parsed / to-be-written publishing config."""

    type: str = "unknown"
    entrypoint: str = ""
    source: typing.Optional[str] = None
    title: typing.Optional[str] = None
    description: typing.Optional[str] = None
    validate: bool = True
    files: typing.List[str] = dataclasses.field(default_factory=lambda: [])
    has_parameters: bool = False
    product_type: str = schema.PRODUCT_TYPE_CONNECT
    python: typing.Optional[typing.Dict[str, typing.Any]] = None
    quarto: typing.Optional[typing.Dict[str, typing.Any]] = None
    r: typing.Optional[typing.Dict[str, typing.Any]] = None
    jupyter: typing.Optional[typing.Dict[str, typing.Any]] = None
    environment: typing.Dict[str, str] = dataclasses.field(default_factory=lambda: {})
    secrets: typing.List[str] = dataclasses.field(default_factory=lambda: [])
    integration_requests: typing.List[typing.Dict[str, typing.Any]] = dataclasses.field(default_factory=lambda: [])
    connect: typing.Optional[typing.Dict[str, typing.Any]] = None
    # Connect Cloud settings ({vanity_name, access_control}), preserved for
    # interop with Publisher-authored configs.
    connect_cloud: typing.Optional[typing.Dict[str, typing.Any]] = None
    schema_url: str = schema.CONFIG_SCHEMA_URL
    # Fields rsconnect does not manage, preserved verbatim on rewrite.
    extra: typing.Dict[str, typing.Any] = dataclasses.field(default_factory=lambda: {})

    @property
    def app_mode(self) -> AppMode:
        """The Connect ``AppMode`` implied by this config's ``type``."""
        return schema.app_mode_from_type(self.type)

    @property
    def requirements_file(self) -> typing.Optional[str]:
        """The declared Python package file, if any (e.g. ``requirements.txt``)."""
        if self.python:
            pkg = self.python.get("package_file")
            if pkg:
                return typing.cast(str, pkg)
        return None

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """Render to an ordered dict ready for TOML serialization.

        Managed keys are emitted first (identity, then language tables); any
        preserved ``extra`` keys are merged in without clobbering managed ones.
        """
        data: typing.Dict[str, typing.Any] = {}
        data["$schema"] = self.schema_url or schema.CONFIG_SCHEMA_URL
        data["product_type"] = self.product_type or schema.PRODUCT_TYPE_CONNECT
        data["type"] = self.type
        data["entrypoint"] = self.entrypoint
        if self.source:
            data["source"] = self.source
        if self.title:
            data["title"] = self.title
        if self.description:
            data["description"] = self.description
        # ``validate`` has no omitempty in Publisher; always written.
        data["validate"] = self.validate
        data["files"] = list(self.files)
        if self.has_parameters:
            data["has_parameters"] = self.has_parameters
        if self.python:
            data["python"] = self.python
        if self.quarto:
            data["quarto"] = self.quarto
        if self.r:
            data["r"] = self.r
        if self.jupyter:
            data["jupyter"] = self.jupyter
        if self.environment:
            data["environment"] = self.environment
        if self.secrets:
            data["secrets"] = list(self.secrets)
        if self.integration_requests:
            data["integration_requests"] = list(self.integration_requests)
        if self.connect:
            data["connect"] = self.connect
        if self.connect_cloud:
            data["connect_cloud"] = self.connect_cloud
        for key, value in self.extra.items():
            data.setdefault(key, value)
        return data


def read_config(path: str) -> PublisherConfig:
    """Parse a config file into a :class:`PublisherConfig`."""
    data = serialize.load(path)
    return from_dict(data)


def from_dict(data: typing.Mapping[str, typing.Any]) -> PublisherConfig:
    """Build a :class:`PublisherConfig` from an already-parsed mapping.

    Used both for reading files and for hydrating the config embedded in a
    deployment record's ``[configuration]`` table.
    """
    return PublisherConfig(
        type=data.get("type", "unknown"),
        entrypoint=data.get("entrypoint", ""),
        source=data.get("source"),
        title=data.get("title"),
        description=data.get("description"),
        validate=data.get("validate", True),
        files=list(data.get("files", []) or []),
        has_parameters=data.get("has_parameters", False),
        product_type=data.get("product_type", schema.PRODUCT_TYPE_CONNECT),
        python=data.get("python"),
        quarto=data.get("quarto"),
        r=data.get("r"),
        jupyter=data.get("jupyter"),
        environment=dict(data.get("environment", {}) or {}),
        secrets=list(data.get("secrets", []) or []),
        integration_requests=list(data.get("integration_requests", []) or []),
        connect=data.get("connect"),
        connect_cloud=data.get("connect_cloud"),
        schema_url=data.get("$schema", schema.CONFIG_SCHEMA_URL),
        extra={k: v for k, v in data.items() if k not in _MANAGED_KEYS},
    )


def write_config(
    project_dir: str,
    name: str,
    cfg: PublisherConfig,
    *,
    merge_existing: bool = True,
) -> typing.Tuple[str, typing.Dict[str, typing.Any]]:
    """Write ``cfg`` to ``<project_dir>/.posit/publish/<name>.toml``.

    If a config already exists, its unmanaged fields, its ``files`` include-list,
    and any user-set ``title``/``python`` are preserved (rsconnect refreshes the
    identity fields ``type`` and ``entrypoint`` but does not clobber curation).

    Returns the written path and the final serialized dict (so a record can
    embed the identical ``[configuration]`` snapshot).
    """
    path = schema.config_path(project_dir, name)
    comments: typing.List[str] = []
    if merge_existing and os.path.exists(path):
        existing = read_config(path)
        # Preserve unmanaged fields and user curation from the existing file.
        cfg.extra = {**existing.extra, **cfg.extra}
        if existing.files:
            cfg.files = existing.files
        if existing.title and not cfg.title:
            cfg.title = existing.title
        if existing.source and not cfg.source:
            cfg.source = existing.source
        if existing.description and not cfg.description:
            cfg.description = existing.description
        if existing.has_parameters and not cfg.has_parameters:
            cfg.has_parameters = existing.has_parameters
        if existing.python and not cfg.python:
            cfg.python = existing.python
        if existing.quarto and not cfg.quarto:
            cfg.quarto = existing.quarto
        if existing.r and not cfg.r:
            cfg.r = existing.r
        if existing.jupyter and not cfg.jupyter:
            cfg.jupyter = existing.jupyter
        if existing.environment and not cfg.environment:
            cfg.environment = existing.environment
        if existing.secrets and not cfg.secrets:
            cfg.secrets = existing.secrets
        if existing.integration_requests and not cfg.integration_requests:
            cfg.integration_requests = existing.integration_requests
        if existing.connect and not cfg.connect:
            cfg.connect = existing.connect
        if existing.connect_cloud and not cfg.connect_cloud:
            cfg.connect_cloud = existing.connect_cloud
        if existing.product_type and cfg.product_type == schema.PRODUCT_TYPE_CONNECT:
            # Never silently downgrade a Publisher-authored connect_cloud config
            # to connect just because rsconnect defaults to connect.
            cfg.product_type = existing.product_type
    data = cfg.to_dict()
    serialize.write(path, serialize.dumps(data, comments))
    return path, data


def discover_configs(project_dir: str) -> typing.List[str]:
    """Return the paths of all config files under ``.posit/publish`` (sorted)."""
    directory = schema.publish_dir(project_dir)
    if not os.path.isdir(directory):
        return []
    return sorted(
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.endswith(".toml") and os.path.isfile(os.path.join(directory, f))
    )
