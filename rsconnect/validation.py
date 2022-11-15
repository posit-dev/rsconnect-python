import typing

from rsconnect.exception import RSConnectException


def _get_present_options(options: typing.Dict[str, typing.Optional[str]]) -> typing.List[str]:
    return [k for k, v in options.items() if v]


def validate_connection_options(url, api_key, insecure, cacert, account_name, token, secret, name=None):
    """
    Validates provided Connect or shinyapps.io connection options and returns which target to use given the provided
    options.
    """
    connect_options = {"-k/--api-key": api_key, "-i/--insecure": insecure, "-c/--cacert": cacert}
    shinyapps_options = {"-T/--token": token, "-S/--secret": secret, "-A/--account": account_name}
    cloud_options = {"-T/--token": token, "-S/--secret": secret}
    options_mutually_exclusive_with_name = {"-s/--server": url, **shinyapps_options}
    present_options_mutually_exclusive_with_name = _get_present_options(options_mutually_exclusive_with_name)

    if name and present_options_mutually_exclusive_with_name:
        raise RSConnectException(
            "-n/--name cannot be specified in conjunction with options {}".format(
                ", ".join(present_options_mutually_exclusive_with_name)
            )
        )
    if not name and not url and not shinyapps_options:
        raise RSConnectException(
            "You must specify one of -n/--name OR -s/--server OR  T/--token, -S/--secret."
        )

    present_connect_options = _get_present_options(connect_options)
    present_shinyapps_options = _get_present_options(shinyapps_options)
    present_cloud_options = _get_present_options(cloud_options)

    if present_connect_options and present_shinyapps_options:
        raise RSConnectException(
            "Connect options ({}) may not be passed alongside shinyapps.io or RStudio Cloud options ({}).".format(
                ", ".join(present_connect_options), ", ".join(present_shinyapps_options)
            )
        )

    if url and 'rstudio.cloud' in url:
        if len(present_cloud_options) != len(cloud_options):
            raise RSConnectException(
                "-T/--token and -S/--secret must be provided for RStudio Cloud."
            )
    elif present_shinyapps_options:
        if len(present_shinyapps_options) != len(shinyapps_options):
            raise RSConnectException(
                "-A/--account, -T/--token, and -S/--secret must all be provided for shinyapps.io."
            )
