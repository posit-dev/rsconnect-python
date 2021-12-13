import logging
import re
import sys
import json
from os.path import exists

import click

from rsconnect.log import LogOutputFormat, logger
from . import VERSION
from . import api
from .actions import (
    cli_feedback,
    set_verbosity,
)
from .metadata import ServerStore
from .models import (
    AppModes,
    BuildStatus,
    ContentGuidWithBundleParamType,
    StrippedStringParamType,
    VersionSearchFilterParamType
)

# todo: instead of checking these for every command, we could just do this to skip the connection checks:
# real_server, api_key, insecure, ca_data, from_store = server_store.resolve(name, url, api_key, insecure, ca_data)
from .main import _validate_deploy_to_args

from .admin_actions import (
  download_bundle,
  build_add_content,
  build_remove_content,
  build_list_content,
  build_history,
  build_start,
  search_content,
  get_content,
  emit_build_log,
)


server_store = ServerStore()

def _verify_build_rm_args(guid, all, purge):
    if guid and all:
        raise api.RSConnectException("You must specify only one of -g/--guid or --all, not both.")
    if not guid and not all:
        raise api.RSConnectException("You must specify one of -g/--guid or --all.")

@click.group(no_args_is_help=True)
def cli():
    """
    This command line tool may be used to administer content on RStudio
    Connect including searching and building content.

    This tool uses the same server nicknames as the `rsconnect` cli.
    Use the `rsconnect list` command to show the available servers.
    """
    pass


@cli.command(help="Show the version of the rsconnect-admin package.")
def version():
    click.secho(VERSION)


@cli.group(no_args_is_help=True, help="Interact with RStudio Connect's content API.")
def content():
    pass

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
    type=VersionSearchFilterParamType("r_version"),
    help="Filter content results by R version.",
)
@click.option(
    "--py-version",
    type=VersionSearchFilterParamType("py_version"),
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
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
# todo: --format option (json, text)
def content_search(name, server, api_key, insecure, cacert, published, unpublished, content_type, r_version, py_version, title_contains, order_by, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        result = search_content(connect_server, published, unpublished, content_type, r_version, py_version, title_contains, order_by)
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@content.command(
    name="describe",
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
    required=True,
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="The GUID of a content item to describe. This flag can be passed multiple times.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
# todo: --format option (json, text)
def content_describe(name, server, api_key, insecure, cacert, guid, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        result = get_content(connect_server, guid)
        json.dump(result, sys.stdout, indent=2)


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
    type=ContentGuidWithBundleParamType(),
    metavar="GUID[,BUNDLE_ID]",
    help="The GUID of a content item to download.",
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
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def content_bundle_download(name, server, api_key, insecure, cacert, guid, output, overwrite, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        if exists(output) and not overwrite:
            raise api.RSConnectException("The output file already exists: %s" % output)

        result = download_bundle(connect_server, guid)
        with open(output, 'wb') as f:
            f.write(result.response_body)


@cli.group(no_args_is_help=True, help="Build content on RStudio Connect. Requires Connect >= 2021.11.1")
def build():
    pass


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="add",
    short_help="Mark a content item for build. Use `build run` to invoke the build on the Connect server."
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
    type=ContentGuidWithBundleParamType(),
    multiple=True,
    metavar="GUID[,BUNDLE_ID]",
    help="Add a content item by its guid. This flag can be passed multiple times.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def add_content_build(name, server, api_key, insecure, cacert, guid, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        build_add_content(connect_server, guid)
        if len(guid) == 1:
            logger.info("Added \"%s\"." % guid[0])
        else:
            logger.info("Bulk added %d content items." % len(guid))


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="rm",
    short_help="Remove a content item from the list of content that are tracked for build. " +
        "Use `build ls` to view the tracked content."
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
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="Remove a content item by guid.",
)
@click.option(
    "--all",
    is_flag=True,
    # TODO: Ask for confirmation?
    help="Remove all content items from the list of content tracked for build.",
)
@click.option(
    "--purge",
    "-p",
    is_flag=True,
    help="Remove build history and log files from the local filesystem.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def remove_content_build(name, server, api_key, insecure, cacert, guid, all, purge, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        _verify_build_rm_args(guid, all, purge)
        build_remove_content(connect_server, guid, all, purge)
        logger.info("Removed %s" % guid)


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="ls",
    short_help="List the content items that are being tracked for build on a given Connect server."
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
    type=click.Choice(BuildStatus._all),
    help="Filter results by status of the build operation."
)
@click.option(
    "--guid",
    "-g",
    multiple=True,
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="Check the local build state of a specific content item. This flag can be passed multiple times.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
# todo: --format option (json, text)
def list_content_build(name, server, api_key, insecure, cacert, status, guid, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        result = build_list_content(connect_server, guid, status)
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="history",
    short_help="Get the build history for a content item."
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
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="The guid of the content item.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
# todo: --format option (json, text)
def get_build_history(name, server, api_key, insecure, cacert, guid, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        result = build_history(connect_server, guid)
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="logs",
    short_help="Print the logs for a content build.",
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
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="The guid of the content item.",
)
@click.option(
    "--task-id",
    "-t",
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="The task ID of the build.",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(LogOutputFormat._all),
    default=LogOutputFormat.DEFAULT,
    help="The output format of the logs. Defaults to text.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def get_build_logs(name, server, api_key, insecure, cacert, guid, task_id, format, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        for line in emit_build_log(connect_server, guid, format, task_id):
            sys.stdout.write(line)


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="run",
    short_help="Start building content on a given Connect server.",
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
    type=click.IntRange(min=1, clamp=True),
    default=1,
    help="Defines the number of builds that can run concurrently. Defaults to 1."
)
@click.option(
    "--aborted",
    is_flag=True,
    help="Build content that is in the ABORTED state."
)
@click.option(
    "--error",
    is_flag=True,
    help="Build content that is in the ERROR state."
)
@click.option(
    "--all",
    is_flag=True,
    help="Build all content, even if it is already marked as COMPLETE."
)
@click.option(
    "--poll-wait",
    type=click.FloatRange(min=.5, clamp=True),
    default=2,
    help="Defines the number of seconds between polls when polling for build output. Defaults to 2.",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(LogOutputFormat._all),
    default=LogOutputFormat.DEFAULT,
    help="The output format of the logs. Defaults to text.",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Log stacktraces from exceptions during background operations."
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def start_content_build(name, server, api_key, insecure, cacert, parallelism, aborted, error, all, poll_wait, format, debug, verbose):
    set_verbosity(verbose)
    logger.set_log_output_format(format)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        build_start(connect_server, parallelism, aborted, error, all, poll_wait, debug)
