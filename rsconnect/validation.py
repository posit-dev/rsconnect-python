import typing

import click

from rsconnect.exception import RSConnectException


def get_parameter_source_name_from_ctx(
    var_or_param_name: str,
    ctx: click.Context,
) -> str:
    if ctx:
        varName = var_or_param_name.replace("-", "_")
        source = ctx.get_parameter_source(varName)  # type: ignore
        if source and source.name:
            return source.name
    return "<source unknown>"


def _get_present_options(
    options: typing.Dict[str, typing.Optional[typing.Any]],
    ctx: click.Context,
) -> typing.List[str]:
    result: typing.List[str] = []
    for k, v in options.items():
        if v:
            parts = k.split("--")
            if ctx and len(parts) == 2:
                sourceName = get_parameter_source_name_from_ctx(parts[1], ctx)
                result.append(f"{k} (from {sourceName})")
            else:
                result.append(f"{k}")
    return result


def validate_connection_options(
    ctx: click.Context,
    url: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    account_name: str,
    token: str,
    secret: str,
    name: str = None,
):
    """
    Validates provided Connect or shinyapps.io connection options and returns which target to use given the provided
    options.

    rsconnect deploy api --name localhost ./python-bottle-py3
    should fail w/
    -s/--server or CONNECT_SERVER
    -T/--token or SHINYAPPS_TOKEN or RSCLOUD_TOKEN
    -S/--secret or SHINYAPPS_SECRET or RSCLOUD_SECRET
    -A/--account or SHINYAPPS_ACCOUNT

    FAILURE if not any of:
    -n/--name
    -s/--server or CONNECT_SERVER
    -T/--token or SHINYAPPS_TOKEN or RSCLOUD_TOKEN
    -S/--secret or SHINYAPPS_SECRET or RSCLOUD_SECRET
    -A/--account or SHINYAPPS_ACCOUNT

    FAILURE if any of:
    -k/--api-key or CONNECT_API_KEY
    -i/--insecure or CONNECT_INSECURE
    -c/--cacert or CONNECT_CA_CERTIFICATE
    AND any of:
    -T/--token or SHINYAPPS_TOKEN or RSCLOUD_TOKEN
    -S/--secret or SHINYAPPS_SECRET or RSCLOUD_SECRET
    -A/--account or SHINYAPPS_ACCOUNT

    FAILURE if specify -s/--server or CONNECT_SERVER and it includes "posit.cloud" or "rstudio.cloud"
    and not specified all of following:
    -T/--token or SHINYAPPS_TOKEN or RSCLOUD_TOKEN
    -S/--secret or SHINYAPPS_SECRET or RSCLOUD_SECRET

    FAILURE if any of following are specified, without the rest:
    -T/--token or SHINYAPPS_TOKEN or RSCLOUD_TOKEN
    -S/--secret or SHINYAPPS_SECRET or RSCLOUD_SECRET
    -A/--account or SHINYAPPS_ACCOUNT
    """
    connect_options = {"-k/--api-key": api_key, "-i/--insecure": insecure, "-c/--cacert": cacert}
    shinyapps_options = {"-T/--token": token, "-S/--secret": secret, "-A/--account": account_name}
    cloud_options = {"-T/--token": token, "-S/--secret": secret}
    options_mutually_exclusive_with_name = {"-s/--server": url, **shinyapps_options}
    present_options_mutually_exclusive_with_name = _get_present_options(options_mutually_exclusive_with_name, ctx)

    if name and present_options_mutually_exclusive_with_name:
        name_source = get_parameter_source_name_from_ctx("name", ctx)
        raise RSConnectException(
            f"-n/--name (from {name_source}) cannot be specified in conjunction with options \
{', '.join(present_options_mutually_exclusive_with_name)}. See command help for further details."
        )

    if not name and not url and not shinyapps_options:
        raise RSConnectException(
            "You must specify one of -n/--name OR -s/--server OR  T/--token, -S/--secret, \
either via command options or environment variables. See command help for further details."
        )

    present_connect_options = _get_present_options(connect_options, ctx)
    present_shinyapps_options = _get_present_options(shinyapps_options, ctx)
    present_cloud_options = _get_present_options(cloud_options, ctx)

    if present_connect_options and present_shinyapps_options:
        raise RSConnectException(
            f"Connect options ({', '.join(present_connect_options)}) may not be passed \
alongside shinyapps.io or Posit Cloud options ({', '.join(present_shinyapps_options)}). \
See command help for further details."
        )

    if url and ("posit.cloud" in url or "rstudio.cloud" in url):
        if len(present_cloud_options) != len(cloud_options):
            raise RSConnectException(
                "-T/--token and -S/--secret must be provided for Posit Cloud. \
See command help for further details."
            )
    elif present_shinyapps_options:
        if len(present_shinyapps_options) != len(shinyapps_options):
            raise RSConnectException(
                "-A/--account, -T/--token, and -S/--secret must all be provided \
for shinyapps.io. See command help for further details."
            )
