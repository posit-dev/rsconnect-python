import logging
import re
import json
from os.path import exists

import click
import semver

from rsconnect import VERSION
from . import api
from .metadata import ServerStore
from .models import AppModes, RebuildStatus
from .admin_actions import (
  open_file_or_stdout,
  download_bundle,
  rebuild_add_content,
  rebuild_remove_content,
  rebuild_list_content,
  rebuild_start,
  search_content,
  get_content,
  emit_rebuild_log,
)
from rsconnect.main import (
  _validate_deploy_to_args
)

class CustomMultiCommand(click.Group):
    def command(self, *args, **kwargs):
        """Behaves the same as `click.Group.command()` except if passed
        a list of names, all after the first will be aliases for the first.
        """
        def decorator(f):
            if isinstance(args[0], list):
                _args = [args[0][0]] + list(args[1:])
                for alias in args[0][1:]:
                    cmd = super(CustomMultiCommand, self).command(
                        alias, *args[1:], **kwargs)(f)
                    cmd.hidden = True
            else:
                _args = args
            cmd = super(CustomMultiCommand, self).command(
                *_args, **kwargs)(f)
            return cmd
        return decorator

server_store = ServerStore()
future_enabled = False
logging.basicConfig()

_version_search_pattern = r"(^[=><]{1,2})(.*)"

@click.group(no_args_is_help=True)
@click.option("--future", "-u", is_flag=True, hidden=True, help="Enables future functionality.")
def cli(future):
    """
    This command line tool may be used to administer content on RStudio
    Connect including searching and rebuilding content.

    This tool uses the same server nicknames as the `rsconnect` cli.
    Use the `rsconnect list` command to show the available servers.
    """
    global future_enabled
    future_enabled = future


@cli.command(help="Show the version of the rsconnect-admin package.")
def version():
    click.echo(VERSION)


@cli.group(no_args_is_help=True, help="Interact with RStudio Connect's content API.")
def content():
    pass

class VersionSearchFilter(click.ParamType):
    def __init__(self, name:str=None, comp:str=None, vers:str=None):
        self.name = name
        self.comp = comp
        self.vers = vers

    # https://click.palletsprojects.com/en/8.0.x/api/#click.ParamType
    def convert(self, value, param, ctx):
        if isinstance(value, VersionSearchFilter):
            return value

        if isinstance(value, str):
            m = re.match(_version_search_pattern, value)
            if m != None:
                self.comp = m.group(1)
                self.vers = m.group(2)

                if self.comp in ["<<", "<>", "><", ">>", "=<", "=>", "="]:
                    self.fail("Failed to parse verison filter: %s is not a valid comparitor" % self.comp)

                try:
                    semver.parse(self.vers)
                except ValueError:
                    self.fail("Failed to parse version info: %s" % self._vers)
                return self

        self.fail("Failed to parse version filter %s" % value)

# noinspection SpellCheckingInspection,DuplicatedCode
@content.command(
    name="search",
    short_help="Search for content on RStudio Connect.",
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--published",
    is_flag=True,
    help="Search only published content.",
)
@click.option(
    "--unpublished",
    is_flag=True,
    help="Search only unpublished content.",
)
@click.option(
    "--content-type",
    type=click.Choice(list(map(str, AppModes._modes))),
    multiple=True,
    help="Filter content results by content type."
)
@click.option(
    "--r-version",
    type=VersionSearchFilter("r_version"),
    help="Filter content results by R version.",
)
@click.option(
    "--py-version",
    type=VersionSearchFilter("py_version"),
    help="Filter content results by Python version.",
)
@click.option(
    "--title-contains",
    help="Filter content results by title.",
)
@click.option(
    "--order-by",
    type=click.Choice(["created", "last_deployed"]),
    help="Order content results.",
)
# todo: Add a --content-type filter flag
# todo: --format option (json, text)
def content_search(name, server, api_key, insecure, cacert, published, unpublished, content_type, r_version, py_version, title_contains, order_by):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    with open_file_or_stdout("-") as f:
        result = search_content(connect_server, published, unpublished, content_type, r_version, py_version, title_contains, order_by)
        f.write(json.dumps(result, indent=2))


# noinspection SpellCheckingInspection,DuplicatedCode
@content.command(
    name="get",
    short_help="Describe a content item on RStudio Connect.",
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--guid",
    "-g",
    multiple=True,
    help="The GUID of a content item to describe. This flag can be passed multiple times.",
)
# todo: --format option (json, text)
def content_get(name, server, api_key, insecure, cacert, guid):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    with open_file_or_stdout("-") as f:
        result = get_content(connect_server, guid)
        f.write(json.dumps(result, indent=2))


# noinspection SpellCheckingInspection,DuplicatedCode
@content.command(
    name="download-bundle",
    short_help="Download a content item's source bundle.",
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--guid",
    "-g",
    required=True,
    help="The GUID of a content item to download.",
)
@click.option(
    "--bundle-id",
    help="The bundle ID of the content item to download. By default, the latest bundle is downloaded.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    required=True,
    help="Defines the output location for the download.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    help="Overwrite the output file if it already exists.",
)
def content_bundle_download(name, server, api_key, insecure, cacert, guid, bundle_id, output, overwrite):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    if exists(output) and not overwrite:
        raise api.RSConnectException("The output file already exists: %s" % output)

    with open(output, 'wb') as f:
        result = download_bundle(connect_server, guid, bundle_id)
        f.write(result.response_body)


@cli.group(cls=CustomMultiCommand, no_args_is_help=True, help="Rebuild content on RStudio Connect.")
def rebuild():
    pass


# noinspection SpellCheckingInspection,DuplicatedCode
@rebuild.command(
    "add",
    short_help="Mark a content item for rebuild. Use `rebuild start` to invoke the rebuild on the Connect server."
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--guid",
    "-g",
    required=True,
    help="Add a content item by guid.",
)
@click.option(
    "--bundle-id",
    help="The bundle ID of the content item to rebuild. By default, the latest bundle is used.",
)
# todo: add a --timeout flag with sane default
def add_content_rebuild(name, server, api_key, insecure, cacert, guid, bundle_id):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    rebuild_add_content(connect_server, guid, bundle_id)


# noinspection SpellCheckingInspection,DuplicatedCode
@rebuild.command(
    ["remove", "rm"],
    short_help="Remove a content item from the list of content that are tracked for rebuild. Use `rebuild list` to view the tracked content."
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--guid",
    "-g",
    required=True,
    help="Remove a content item by guid.",
)
@click.option(
    "--purge",
    "-p",
    is_flag=True,
    help="Cleanup all associated rebuild log files on the local filesystem.",
)
def remove_content_rebuild(name, server, api_key, insecure, cacert, guid, purge):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    rebuild_remove_content(connect_server, guid, purge)


# noinspection SpellCheckingInspection,DuplicatedCode
@rebuild.command(
    ["list", "ls"],
    short_help="List the content items that are being tracked for rebuild on a given Connect server."
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--status",
    type=click.Choice(RebuildStatus._all),
    help="Filter results by status of the rebuild operation."
)
# todo: --format option (json, text)
def list_content_rebuild(name, server, api_key, insecure, cacert, status):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    with open_file_or_stdout("-") as f:
        result = rebuild_list_content(connect_server, status)
        f.write(json.dumps(result, indent=2))


# noinspection SpellCheckingInspection,DuplicatedCode
@rebuild.command(
    "logs",
    short_help="Print the logs for a content rebuild.",
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--guid",
    "-g",
    required=True,
    help="The guid of the content item.",
)
@click.option(
    "--task-id",
    "-t",
    help="The task ID of the rebuild.",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "text"]),
    default="text",
    help="The output format of the logs. Defaults to text.",
)
def get_rebuild_logs(name, server, api_key, insecure, cacert, guid, task_id, format):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    with open_file_or_stdout("-") as f:
        for line in emit_rebuild_log(connect_server, guid, format, task_id):
            f.write(line)


# noinspection SpellCheckingInspection,DuplicatedCode
@rebuild.command(
    "start",
    short_help="Start rebuilding content on a given Connect server.",
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--parallelism",
    type=click.IntRange(min=1, max=10, clamp=True),
    default=1,
    help="Defines the number of rebuilds that can run concurrently. Defaults to 1. Capped at 10."
)
@click.option(
    "--debug",
    is_flag=True,
    help="Print exceptions from background operations."
)
# todo: --background flag
def start_content_rebuild(name, server, api_key, insecure, cacert, parallelism, debug):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    rebuild_start(connect_server, parallelism, debug)
