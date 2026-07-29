"""Facade tying the ``.posit/publish`` config + record files to deploy flows.

Write side: :func:`write_deployment_metadata` is called after a successful
Connect/SPCS deploy to create-or-update the config and the deployment record.

Read side: :func:`resolve_publisher_deploy_target` reconstructs a ready-to-deploy
target from an existing config (+ record) so a bare ``rsconnect redeploy`` can
run with no other arguments. Records are matched by ``server_url`` content, not
filename, so Publisher-authored files interoperate.
"""

from __future__ import annotations

import dataclasses
import os
import random
import re
import typing
from urllib.parse import urlparse

from ..exception import RSConnectException
from ..models import AppMode, AppModes
from . import config as config_mod
from . import files as files_mod
from . import record as record_mod
from . import schema

if typing.TYPE_CHECKING:
    from typing import IO


def normalize_url(url: str) -> str:
    """Normalize a Connect URL for content comparison.

    Strips a trailing ``/__api__`` and any trailing slash, and lowercases the
    scheme+host, so a record's ``server_url`` matches a saved server that may
    differ cosmetically. The path (a Connect instance may live under one) is
    preserved apart from the ``__api__`` suffix.
    """
    if not url:
        return ""
    parsed = urlparse(url if "//" in url else "//" + url)
    netloc = parsed.netloc.lower()
    # Strip trailing slashes first so a trailing slash after ``__api__``
    # (".../__api__/") still lets the suffix be removed.
    path = parsed.path.rstrip("/")
    if path.endswith("/__api__"):
        path = path[: -len("/__api__")]
    path = path.rstrip("/")
    scheme = (parsed.scheme or "https").lower()
    return "{}://{}{}".format(scheme, netloc, path)


# --- write side ------------------------------------------------------------


# File-naming mirrors Posit Publisher's utils/names.ts: a random, uppercase,
# base-32 ending appended to a filesystem-safe title. Publisher relies on its
# UI to reuse a chosen file; a CLI has none, so on redeploy we first look for an
# existing record with the same server_url (and its config) and reuse those
# filenames, only minting a new random name for a genuinely new deployment.
_BASE32_UPPER = "0123456789ABCDEFGHIJKLMNOPQRSTUV"


def _random_name_ending(length: int = 4) -> str:
    """A random uppercase base-32 string, matching Publisher's ``randomNameEnding``."""
    return "".join(random.choice(_BASE32_UPPER) for _ in range(length))


def _filenamify(title: str) -> str:
    """Approximate Publisher's ``filenamify(title, {replacement: '-', maxLength: 30})``."""
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", title).strip(". ").strip()
    return (slug or "content")[:30]


def _basenames(paths: typing.Iterable[str]) -> typing.Set[str]:
    return {os.path.splitext(os.path.basename(p))[0].lower() for p in paths}


def _new_config_name(project_dir: str, title: str) -> str:
    """A fresh ``<title>-<code>`` config name, unique among existing configs.

    Matches Publisher's ``newConfigFileNameFromTitle``."""
    existing = _basenames(config_mod.discover_configs(project_dir))
    base = _filenamify(title)
    while True:
        candidate = "{}-{}".format(base, _random_name_ending())
        if candidate.lower() not in existing:
            return candidate


def _new_record_name(project_dir: str) -> str:
    """A fresh ``deployment-<code>`` record name, matching Publisher's ``newDeploymentName``."""
    existing = _basenames(record_mod.discover_records(project_dir))
    while True:
        candidate = "deployment-{}".format(_random_name_ending())
        if candidate.lower() not in existing:
            return candidate


def _find_record_name_for_server(project_dir: str, server_url: str) -> typing.Optional[str]:
    """Basename of an existing record whose ``server_url`` matches, so a redeploy
    updates in place instead of spawning a new random-named file."""
    target = normalize_url(server_url)
    for path in record_mod.discover_records(project_dir):
        try:
            rec = record_mod.read_record(path)
        except Exception:
            continue
        if normalize_url(rec.server_url) == target:
            return os.path.splitext(os.path.basename(path))[0]
    return None


def _find_config_name_for_entrypoint(project_dir: str, entrypoint: str) -> typing.Optional[str]:
    """Basename of an existing config with a matching entrypoint, if any."""
    if not entrypoint:
        return None
    for path in config_mod.discover_configs(project_dir):
        try:
            cfg = config_mod.read_config(path)
        except Exception:
            continue
        if cfg.entrypoint == entrypoint:
            return os.path.splitext(os.path.basename(path))[0]
    return None


def resolve_bundle_files(
    directory: str,
    entrypoint: typing.Optional[str] = None,
    config_name: typing.Optional[str] = None,
) -> typing.List[str]:
    """Resolve the concrete project-relative files to bundle for ``directory``.

    If a ``.posit/publish`` config applies -- the one named ``config_name``, else
    the sole config, else the config whose entrypoint matches ``entrypoint`` -- and
    it declares ``files``, return those selected as an allowlist. Otherwise return
    the ``.gitignore``-aware default (everything not ignored). Never raises for an
    ambiguous or missing config; it falls back to the default selection so a plain
    ``deploy`` still works.
    """
    cfg: typing.Optional[config_mod.PublisherConfig] = None
    try:
        configs = _load_configs(directory)
    except Exception:
        configs = {}
    if config_name and config_name in configs:
        cfg = configs[config_name]
    elif len(configs) == 1:
        cfg = next(iter(configs.values()))
    elif entrypoint:
        for candidate in configs.values():
            if candidate.entrypoint == entrypoint:
                cfg = candidate
                break

    if cfg is not None and cfg.files:
        selected = files_mod.select_config_files(directory, cfg.files)
        # The entrypoint must ship even if the config's patterns don't cover it
        # (the bundle builders reference it from this list, not separately).
        if cfg.entrypoint:
            entry = cfg.entrypoint.replace(os.sep, "/")
            if entry not in selected and os.path.isfile(os.path.join(directory, cfg.entrypoint)):
                selected = sorted([*selected, entry])
        return selected
    return files_mod.select_default_files(directory)


def _root_anchor(path: str) -> str:
    """Root-anchor a project-relative path (``app.py`` -> ``/app.py``).

    Anchoring prevents an entry from also matching a same-named file deeper in the
    tree, matching how Publisher records concrete, root-relative include paths.
    """
    return "/" + path.replace(os.sep, "/").lstrip("/")


def _config_file_patterns(details: "record_mod.BundleContentDetails") -> typing.List[str]:
    """The config ``files`` include-list: the concrete deployed file set.

    Uses the exact file list from the built bundle's manifest so the config's
    ``files``, the manifest's ``files``, and the record's ``files`` all denote the
    same set (root-anchored, as Publisher writes them). The entrypoint and the
    declared package file are guaranteed present (the schema requires
    ``package_file`` to be listed under ``files``).
    """
    patterns: typing.List[str] = []
    for name in details.files:
        anchored = _root_anchor(name)
        if anchored not in patterns:
            patterns.append(anchored)
    if details.entrypoint:
        entry = _root_anchor(details.entrypoint)
        if entry not in patterns:
            patterns.insert(0, entry)
    if details.python and details.python.get("package_file"):
        pkg = _root_anchor(typing.cast(str, details.python["package_file"]))
        if pkg not in patterns:
            patterns.append(pkg)
    return patterns


def _posit_bundle_paths(project_dir: str, config_name: str, record_name: typing.Optional[str]) -> typing.List[str]:
    """Root-anchored ``.posit`` paths to include in ``files``, mirroring Publisher.

    Publisher adds the driving config (and its deployment record) to the deployment
    file list so they ship in the bundle. Returns the config path always and the
    record path when ``record_name`` is known.
    """
    paths = [_root_anchor(os.path.relpath(schema.config_path(project_dir, config_name), project_dir))]
    if record_name:
        paths.append(_root_anchor(os.path.relpath(schema.record_path(project_dir, record_name), project_dir)))
    return paths


def write_deployment_metadata(
    *,
    project_dir: str,
    server_url: str,
    product_type: str,
    app_mode: "AppMode | str",
    title: typing.Optional[str],
    deployed_info: typing.Mapping[str, typing.Any],
    bundle: "IO[bytes]",
    config_name: typing.Optional[str] = None,
    record_name: typing.Optional[str] = None,
) -> typing.Tuple[str, str]:
    """Create/update the ``.posit`` config and deployment record for a deploy.

    ``config_name``/``record_name`` pin the exact files to update -- ``redeploy``
    passes the names it resolved so the write updates those files instead of
    re-deriving (and possibly duplicating) them. When omitted, an existing record
    for this server (and its config) is reused, otherwise new names are minted.

    Returns ``(config_path, record_path)``. Raises on failure; callers treat
    ``.posit`` write failures as non-fatal (the deploy has already succeeded).
    """
    details = record_mod.read_bundle_details(bundle)
    content_type = schema.type_from_app_mode(app_mode)

    cfg = config_mod.PublisherConfig(
        type=content_type,
        entrypoint=details.entrypoint,
        title=title,
        product_type=product_type,
        python=details.python,
        quarto=details.quarto,
    )
    # Reuse an existing deployment's filenames on redeploy; only mint new random
    # names for a genuinely new deployment. A caller-supplied record_name (from
    # redeploy) pins the record file; otherwise match one by server_url.
    existing_record_name = record_name or _find_record_name_for_server(project_dir, server_url)
    existing_config_name = None
    if existing_record_name and not config_name:
        record_file = schema.record_path(project_dir, existing_record_name)
        if os.path.exists(record_file):
            existing_config_name = record_mod.read_record(record_file).configuration_name

    cname = (
        config_name
        or existing_config_name
        or _find_config_name_for_entrypoint(project_dir, details.entrypoint)
        or _new_config_name(project_dir, title or details.entrypoint or "content")
    )
    rname = existing_record_name or _new_record_name(project_dir)
    # For a new config, seed ``files`` with the concrete deployed set plus the
    # ``.posit`` files (mirroring Publisher). ``write_config`` preserves an existing
    # config's curated ``files``, so this only takes effect when minting one.
    cfg.files = _config_file_patterns(details) + _posit_bundle_paths(project_dir, cname, rname)
    config_path, config_dict = config_mod.write_config(project_dir, cname, cfg)

    dashboard_url = deployed_info.get("dashboard_url")
    rec = record_mod.PublisherRecord(
        server_url=server_url,
        server_type=product_type,
        id=deployed_info.get("app_guid"),
        type=content_type,
        configuration_name=cname,
        deployed_at=record_mod.now(),
        dashboard_url=dashboard_url,
        direct_url=deployed_info.get("app_url"),
        logs_url=(dashboard_url + "/logs") if dashboard_url else None,
        bundle_id=deployed_info.get("bundle_id"),
        files=details.files,
        requirements=details.requirements,
        configuration=config_dict,
    )
    rname = existing_record_name or _new_record_name(project_dir)
    record_path = record_mod.write_record(project_dir, rname, rec)
    return config_path, record_path


def write_config_from_manifest(
    project_dir: str,
    manifest: typing.Mapping[str, typing.Any],
    app_mode: "AppMode | str | None" = None,
    title: typing.Optional[str] = None,
    config_name: typing.Optional[str] = None,
) -> str:
    """Write a ``.posit/publish`` config from a ``manifest.json`` dict.

    Used by ``write-manifest`` (which prepares content but does not deploy) so a
    Publisher config accompanies the generated manifest. No record is written,
    since there is no deployment. ``app_mode`` defaults to the manifest's
    ``metadata.appmode``. Returns the config path.
    """
    details = record_mod.details_from_manifest(manifest)
    if app_mode is None:
        app_mode = AppModes.get_by_name((manifest.get("metadata") or {}).get("appmode", ""), return_unknown=True)
    cfg = config_mod.PublisherConfig(
        type=schema.type_from_app_mode(app_mode),
        entrypoint=details.entrypoint,
        title=title,
        python=details.python,
        quarto=details.quarto,
    )
    cname = (
        config_name
        or _find_config_name_for_entrypoint(project_dir, details.entrypoint)
        or _new_config_name(project_dir, title or details.entrypoint or "content")
    )
    # No deployment record here (write-manifest does not deploy); include the
    # config itself but no record path.
    cfg.files = _config_file_patterns(details) + _posit_bundle_paths(project_dir, cname, None)
    path, _ = config_mod.write_config(project_dir, cname, cfg)
    return path


# --- read side -------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PublisherDeployTarget:
    """A ready-to-deploy target reconstructed from ``.posit`` files.

    Mirrors :class:`rsconnect.pyproject.PyprojectDeployTarget` (the "what") and
    adds the record-sourced "where" (``server_url``/``app_id``). ``record`` is
    ``None`` on a first deployment (config exists but nothing deployed yet).
    """

    project_dir: str
    config_name: str
    config: config_mod.PublisherConfig
    app_mode: AppMode
    entrypoint: str
    title: typing.Optional[str]
    requirements_file: typing.Optional[str]
    server_url: typing.Optional[str]
    app_id: typing.Optional[str]
    record: typing.Optional[record_mod.PublisherRecord]
    # Basename (no .toml) of the matched record file, so a redeploy updates that
    # exact file rather than re-deriving it.
    record_name: typing.Optional[str] = None


def _load_configs(project_dir: str) -> typing.Dict[str, config_mod.PublisherConfig]:
    """Map config basename (without .toml) -> parsed config."""
    result: typing.Dict[str, config_mod.PublisherConfig] = {}
    for path in config_mod.discover_configs(project_dir):
        name = os.path.splitext(os.path.basename(path))[0]
        result[name] = config_mod.read_config(path)
    return result


def _select_config(
    configs: typing.Dict[str, config_mod.PublisherConfig], config_name: typing.Optional[str]
) -> typing.Tuple[str, config_mod.PublisherConfig]:
    if config_name:
        if config_name not in configs:
            raise RSConnectException(
                "No .posit config named '{}'. Found: {}".format(config_name, ", ".join(sorted(configs)) or "none")
            )
        return config_name, configs[config_name]
    if len(configs) == 1:
        name = next(iter(configs))
        return name, configs[name]
    raise RSConnectException(
        "Multiple .posit configs found ({}); specify one with --config-name.".format(", ".join(sorted(configs)))
    )


def _matching_records(
    project_dir: str, config_name: str, server: typing.Optional[str]
) -> typing.List[typing.Tuple[str, record_mod.PublisherRecord]]:
    """``(record_name, record)`` pairs for ``config_name``, optionally filtered to a server URL."""
    records: typing.List[typing.Tuple[str, record_mod.PublisherRecord]] = []
    normalized_server = normalize_url(server) if server else None
    for path in record_mod.discover_records(project_dir):
        rec = record_mod.read_record(path)
        # Match by content: the record's configuration_name links it to a config;
        # records without one are accepted only when there is a single config.
        if rec.configuration_name and rec.configuration_name != config_name:
            continue
        if normalized_server and normalize_url(rec.server_url) != normalized_server:
            continue
        records.append((os.path.splitext(os.path.basename(path))[0], rec))
    return records


def resolve_publisher_deploy_target(
    project_dir: str,
    config_name: typing.Optional[str] = None,
    server: typing.Optional[str] = None,
) -> PublisherDeployTarget:
    """Resolve a deploy target from ``.posit`` files under ``project_dir``.

    Raises :class:`RSConnectException` when no config exists, when the config or
    record choice is ambiguous, or (for a redeploy) when there is no prior
    deployment and no server was supplied to seed a first deploy.
    """
    configs = _load_configs(project_dir)
    if not configs:
        raise RSConnectException(
            "No .posit/publish configuration found in {}. This directory has no Publisher project.".format(project_dir)
        )
    name, cfg = _select_config(configs, config_name)

    matches = _matching_records(project_dir, name, server)
    if len(matches) > 1:
        servers = ", ".join(sorted(rec.server_url for _, rec in matches))
        raise RSConnectException(
            "Multiple deployments found for config '{}' ({}); specify one with --server.".format(name, servers)
        )
    record_name: typing.Optional[str]
    record: typing.Optional[record_mod.PublisherRecord]
    record_name, record = matches[0] if matches else (None, None)

    # Fall back to the record's embedded config snapshot if no standalone config
    # file carried the fields we need (e.g. a Publisher-authored record).
    effective = cfg
    if record is not None and record.config() is not None:
        embedded = typing.cast(config_mod.PublisherConfig, record.config())
        if not effective.entrypoint and embedded.entrypoint:
            effective = embedded

    return PublisherDeployTarget(
        project_dir=project_dir,
        config_name=name,
        config=effective,
        app_mode=effective.app_mode,
        entrypoint=effective.entrypoint,
        title=effective.title,
        requirements_file=effective.requirements_file,
        server_url=record.server_url if record else None,
        app_id=record.id if record else None,
        record=record,
        record_name=record_name,
    )
