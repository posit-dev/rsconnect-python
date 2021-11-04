import logging
import re
from os.path import exists

import click
import semver

from rsconnect import VERSION
from . import api
from .metadata import ServerStore
from .actions import (
  open_file_or_stdout,
  download_bundle,
  rebuild_add_content,
  rebuild_start,
  search_content,
  get_content,
)
from rsconnect.main import (
  _validate_deploy_to_args
)


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

    The tool supports the notion of a simple nickname that represents the
    information needed to interact with an RStudio Connect server instance.  Use
    the add, list and remove commands to manage these nicknames.

    The information about an instance of RStudio Connect includes its URL, the
    API key needed to authenticate against that instance, a flag that notes whether
    TLS certificate/host verification should be disabled and a path to a trusted CA
    certificate file to use for TLS.  The last two items are only relevant if the
    URL specifies the "https" protocol.
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
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="-",
    help="Defines the output location for search results. Defaults to stdout.",
)
# todo: Add a --content-type filter flag
def content_search(name, server, api_key, insecure, cacert, published, unpublished, r_version, py_version, title_contains, order_by, output):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    if output != "-":
        if exists(output):
            raise api.RSConnectException("The output file already exists.")

    with open_file_or_stdout(output) as f:
        f.write(search_content(connect_server, published, unpublished, r_version, py_version, title_contains, order_by))


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
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="-",
    help="Defines the output location for query results. Defaults to stdout.",
)
def content_get(name, server, api_key, insecure, cacert, guid, output):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    if output != "-":
        if exists(output):
            raise api.RSConnectException("The output file already exists.")

    with open_file_or_stdout(output) as f:
        f.write(get_content(connect_server, guid))


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
        f.write(download_bundle(connect_server, guid, bundle_id))


@content.group(no_args_is_help=True, help="Rebuild content on RStudio Connect.")
def rebuild():
    pass


# noinspection SpellCheckingInspection,DuplicatedCode
@rebuild.command(
    name="add",
    short_help="Add content items to the next rebuild job for a given Connect server.",
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
def add_content_to_rebuild(name, server, api_key, insecure, cacert, guid, bundle_id):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    rebuild_add_content(connect_server, guid, bundle_id)


# noinspection SpellCheckingInspection,DuplicatedCode
@rebuild.command(
    name="start",
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
# todo: --background flag
def start_content_rebuild(name, server, api_key, insecure, cacert):
    connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
    rebuild_start(connect_server)
