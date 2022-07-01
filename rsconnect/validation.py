import typing

from . import api


def _get_present_options(options: typing.Dict[str, typing.Optional[str]]) -> typing.List[str]:
    return [k for k, v in options.items() if v]


def validate_connection_options(name, url, api_key, insecure, cacert, account, token, secret):
    """
    Validates provided Connect or shinyapps.io connection options and returns which target to use given the provided
    options.
    """
    connect_options = {"-k/--api-key": api_key, "-i/--insecure": insecure, "-c/--cacert": cacert}
    shinyapps_options = {"-T/--token": token, "-S/--secret": secret, "-a/--account": account}
    options_mutually_exclusive_with_name = {"--server": url, **connect_options, **shinyapps_options}

    present_options_mutually_exclusive_with_name = _get_present_options(options_mutually_exclusive_with_name)

    if name and present_options_mutually_exclusive_with_name:
        raise api.RSConnectException(
            "-n/--name cannot be specified in conjunction with options {}".format(
                ", ".join(present_options_mutually_exclusive_with_name)
            )
        )
    if not name and not url:
        raise api.RSConnectException(
            "You must specify one of -n/--name OR -s/--server OR  -a/--account, -T/--token, -S/--secret."
        )

    present_connect_options = _get_present_options(connect_options)
    present_shinyapps_options = _get_present_options(shinyapps_options)

    if present_connect_options and present_shinyapps_options:
        raise api.RSConnectException(
            "Connect options ({}) may not be passed alongside shinyapps.io options ({}).".format(
                ", ".join(present_connect_options), ", ".join(present_shinyapps_options)
            )
        )

    if present_shinyapps_options:
        if len(present_shinyapps_options) != 3:
            raise api.RSConnectException(
                "-a/--account, -T/--token, and -S/--secret must all be provided for shinyapps.io."
            )
