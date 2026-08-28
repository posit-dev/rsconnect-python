from __future__ import annotations

import os
from typing import Any, Optional

import click

from rsconnect.connect_cloud import is_connect_cloud_url
from rsconnect.exception import RSConnectException


def get_parameter_source_name_from_ctx(
    var_or_param_name: str,
    ctx: Optional[click.Context],
) -> str:
    if ctx:
        varName = var_or_param_name.replace("-", "_")
        source = ctx.get_parameter_source(varName)
        if source and source.name:
            return source.name
    return "<source unknown>"


def effective_connect_cloud_account(ctx: Optional[click.Context], account_name: Optional[str]) -> Optional[str]:
    """The -A value to use when the target is Posit Connect Cloud.

    -A/--account is shared with shinyapps.io, whose environment variable is
    SHINYAPPS_ACCOUNT; a value exported for shinyapps.io CI must not retarget a
    Connect Cloud deploy. A typed -A (or one passed programmatically, where no
    click context exists) applies as-is; otherwise the account comes from
    CONNECT_CLOUD_ACCOUNT, or is left unset for a saved server to supply.
    """
    if account_name and get_parameter_source_name_from_ctx("account", ctx) != "ENVIRONMENT":
        return account_name
    return os.environ.get("CONNECT_CLOUD_ACCOUNT") or None


def _get_present_options(
    options: dict[str, Optional[Any]],
    ctx: Optional[click.Context],
    ignore_sources: tuple[str, ...] = (),
) -> list[str]:
    """The options that have a value, labelled with where each came from.

    :param ignore_sources: parameter sources to leave out, named as click's
    ParameterSource members are ("ENVIRONMENT", "COMMANDLINE", ...). Only applies
    when a context is available to ask; without one every value counts.
    """
    result: list[str] = []
    for k, v in options.items():
        if v:
            parts = k.split("--")
            if ctx and len(parts) == 2:
                sourceName = get_parameter_source_name_from_ctx(parts[1], ctx)
                if sourceName in ignore_sources:
                    continue
                result.append(f"{k} (from {sourceName})")
            else:
                result.append(f"{k}")
    return result


# Deploy options that configure Posit Connect features Connect Cloud does not
# have.
_CONNECT_ONLY_DEPLOY_OPTIONS: dict[str, str] = {
    "image": "-I/--image",
    "disable_env_management": "--disable-env-management",
    "env_management_py": "--disable-env-management-py",
    "env_management_r": "--disable-env-management-r",
    "env_management_node": "--disable-env-management-node",
    "node": "--node",
    "draft": "--draft",
    "metadata": "--metadata",
}


def typed_connect_only_deploy_options(ctx: Optional[click.Context]) -> list[str]:
    """The Connect-only deploy options this command line passed.

    Judged by parameter source rather than by value: --disable-env-management-py
    inverts to False when given, and the --disable-env-management shorthand fills
    in the per-language parameters without being their source.

    Only options count. `environment add` takes a positional IMAGE argument, whose
    parameter is also named `image` and is not this option.
    """
    if ctx is None:
        return []
    option_names = {param.name for param in ctx.command.params if isinstance(param, click.Option)}
    return [
        label
        for name, label in _CONNECT_ONLY_DEPLOY_OPTIONS.items()
        if name in option_names and get_parameter_source_name_from_ctx(name, ctx) == "COMMANDLINE"
    ]


def _reject_options_the_target_has_no_use_for(
    ctx: Optional[click.Context],
    target: str,
    api_key: Optional[str],
    insecure: bool,
    cacert: Optional[str],
    snowflake_connection_name: Optional[str],
    reject_connect_only_deploy_options: bool,
):
    """Reject typed Posit Connect and SPCS options for another target.

    :param target: how to name the target in the error, e.g. "shinyapps.io".
    :param reject_connect_only_deploy_options: also reject Connect deploy options.
    """
    present_connect_options = _get_present_options(
        {"-k/--api-key": api_key, "-i/--insecure": insecure, "-c/--cacert": cacert},
        ctx,
        ignore_sources=("ENVIRONMENT",),
    )
    if present_connect_options:
        raise RSConnectException(
            f"Posit Connect options ({', '.join(present_connect_options)}) may not be passed \
alongside {target}. See command help for further details."
        )
    present_spcs_options = _get_present_options(
        {"--snowflake-connection-name": snowflake_connection_name}, ctx, ignore_sources=("ENVIRONMENT",)
    )
    if present_spcs_options:
        raise RSConnectException(
            f"SPCS options ({', '.join(present_spcs_options)}) may not be passed \
alongside {target}. See command help for further details."
        )
    if reject_connect_only_deploy_options:
        connect_only_deploy_options = typed_connect_only_deploy_options(ctx)
        if connect_only_deploy_options:
            raise RSConnectException(
                f"Posit Connect options ({', '.join(connect_only_deploy_options)}) may not be passed \
alongside {target}. See command help for further details."
            )


def validate_connect_cloud_incompatible_options(
    ctx: Optional[click.Context],
    api_key: Optional[str],
    insecure: bool,
    cacert: Optional[str],
    snowflake_connection_name: Optional[str],
):
    """Reject options that have no meaning on Posit Connect Cloud.

    This runs after stored targets are resolved, which command-line validation
    cannot inspect.
    """
    _reject_options_the_target_has_no_use_for(
        ctx,
        "Posit Connect Cloud",
        api_key,
        insecure,
        cacert,
        snowflake_connection_name,
        reject_connect_only_deploy_options=True,
    )


def validate_shinyapps_incompatible_options(
    ctx: Optional[click.Context],
    api_key: Optional[str],
    insecure: bool,
    cacert: Optional[str],
    snowflake_connection_name: Optional[str],
):
    """Reject options that have no meaning on shinyapps.io.

    This runs after stored targets are resolved. The caller must then clear ignored
    values so they cannot select the Posit Connect client.
    """
    _reject_options_the_target_has_no_use_for(
        ctx,
        "shinyapps.io",
        api_key,
        insecure,
        cacert,
        snowflake_connection_name,
        # Preserve the existing behavior for Connect deploy options.
        reject_connect_only_deploy_options=False,
    )


def validate_connect_cloud_credential_options(
    ctx: Optional[click.Context],
    client_id: Optional[str],
    client_secret: Optional[str],
):
    """Reject typed Connect Cloud credentials when the target is not Connect Cloud.

    validate_connection_options calls this when the target is already decided by
    the command line; the executor calls it again after a nickname or default
    server resolves to a non-Cloud target, which validation cannot see. Only a
    credential the user actually typed conflicts: an exported
    CONNECT_CLOUD_CLIENT_ID/SECRET -- which is how CI is meant to supply them --
    must not block a deploy elsewhere. They are unused then.
    """
    typed_connect_cloud_options = _get_present_options(
        {"--client-id": client_id, "--client-secret": client_secret}, ctx, ignore_sources=("ENVIRONMENT",)
    )
    if typed_connect_cloud_options:
        raise RSConnectException(
            f"Posit Connect Cloud options ({', '.join(typed_connect_cloud_options)}) require \
--connect-cloud or -s/--server connect.posit.cloud. See command help for further details."
        )


def validate_connection_options(
    ctx: Optional[click.Context],
    url: Optional[str],
    api_key: Optional[str],
    insecure: bool,
    cacert: Optional[str],
    account_name: Optional[str],
    token: Optional[str],
    secret: Optional[str],
    name: Optional[str] = None,
    snowflake_connection_name: Optional[str] = None,
    has_default_server: bool = False,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    connect_cloud: bool = False,
    has_saved_connect_cloud_account: bool = False,
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
    --snowflake-connection-name

    FAILURE if any of:
    -k/--api-key or CONNECT_API_KEY
    -i/--insecure or CONNECT_INSECURE
    -c/--cacert or CONNECT_CA_CERTIFICATE
    AND any of:
    -T/--token or SHINYAPPS_TOKEN
    -S/--secret or SHINYAPPS_SECRET
    -A/--account or SHINYAPPS_ACCOUNT

    FAILURE if any of following are specified, without the rest:
    -T/--token or SHINYAPPS_TOKEN
    -S/--secret or SHINYAPPS_SECRET
    -A/--account or SHINYAPPS_ACCOUNT


    FAILURE if -s/--server or CONNECT_SERVER include "snowflakecomputing.app"
    and not
    --snowflake-connection-name
    """
    connect_options = {"-k/--api-key": api_key, "-i/--insecure": insecure, "-c/--cacert": cacert}
    shinyapps_options = {"-T/--token": token, "-S/--secret": secret, "-A/--account": account_name}
    spcs_options = {"--snowflake-connection-name": snowflake_connection_name}
    # --connect-cloud names a target just like -s/--server does, so combining it
    # with a nickname is the same contradiction. Without this, `-n <connect-server>
    # --connect-cloud` silently deployed to the named server and dropped the flag.
    # `rsconnect add` is unaffected: there -n names the entry being created, and
    # add does not pass it to this function.
    #
    # A typed -T/--token or -S/--secret contradicts a nickname the same way, but
    # environment-sourced ones (SHINYAPPS_ACCOUNT/TOKEN/SECRET exported for CI
    # elsewhere) are just the environment and must not block a nickname deploy;
    # the executor drops them before resolution so they cannot merge into the
    # entry either. -A/--account is not judged here at all: a nickname may name a
    # Posit Connect Cloud credential, where -A selects the account to publish to.
    # The executor raises the conflict once the nickname is known not to be one.
    options_mutually_exclusive_with_name = {"-s/--server": url, "--connect-cloud": connect_cloud}
    present_options_mutually_exclusive_with_name = _get_present_options(
        options_mutually_exclusive_with_name, ctx
    ) + _get_present_options({"-T/--token": token, "-S/--secret": secret}, ctx, ignore_sources=("ENVIRONMENT",))

    if name and present_options_mutually_exclusive_with_name:
        name_source = get_parameter_source_name_from_ctx("name", ctx)
        raise RSConnectException(
            f"-n/--name (from {name_source}) cannot be specified in conjunction with options \
{', '.join(present_options_mutually_exclusive_with_name)}. See command help for further details."
        )

    # --connect-cloud names the target on its own, so it satisfies this the same
    # way -s/--server does.
    if not name and not url and not connect_cloud and not any(shinyapps_options.values()) and not has_default_server:
        raise RSConnectException(
            "You must specify one of -n/--name OR -s/--server OR --connect-cloud OR -T/--token, -S/--secret, \
either via command options or environment variables. See command help for further details."
        )

    present_connect_options = _get_present_options(connect_options, ctx)
    present_shinyapps_options = _get_present_options(shinyapps_options, ctx)
    present_spcs_options = _get_present_options(spcs_options, ctx)

    connect_cloud_options = {"--client-id": client_id, "--client-secret": client_secret}
    present_connect_cloud_options = _get_present_options(connect_cloud_options, ctx)

    if connect_cloud and url and not is_connect_cloud_url(url):
        # A CONNECT_SERVER environment variable left over from another target
        # should not override the flag, so a server URL is only a conflict when
        # it was passed explicitly on the command line.
        if get_parameter_source_name_from_ctx("server", ctx) != "ENVIRONMENT":
            raise RSConnectException(
                "--connect-cloud cannot be combined with -s/--server %s. "
                "--connect-cloud already selects Posit Connect Cloud." % url
            )

    # Checked before the generic conflict rules below, so that a Connect Cloud
    # mistake is reported in terms of Connect Cloud. -A/--account is shared with
    # shinyapps.io, so those rules would otherwise blame the wrong target.
    if connect_cloud or is_connect_cloud_url(url):
        # A saved server already names an account, so the account is only required
        # when there is nothing saved to take it from. `rsconnect add` leaves
        # has_saved_connect_cloud_account false: it registers a named account.
        if not account_name and not has_saved_connect_cloud_account:
            raise RSConnectException(
                "-A/--account is required for Posit Connect Cloud. \
See command help for further details."
            )
        # Same rule as validate_connect_cloud_incompatible_options: values that
        # come from environment variables (a CONNECT_API_KEY or SHINYAPPS_TOKEN
        # exported for another target) are ignored; only options passed
        # explicitly on the command line are treated as conflicts.
        typed_shinyapps_credentials = _get_present_options(
            {"-T/--token": token, "-S/--secret": secret}, ctx, ignore_sources=("ENVIRONMENT",)
        )
        if typed_shinyapps_credentials:
            raise RSConnectException(
                "-T/--token and -S/--secret are shinyapps.io options and may not be passed \
alongside Posit Connect Cloud. See command help for further details."
            )
        typed_connect_options = _get_present_options(connect_options, ctx, ignore_sources=("ENVIRONMENT",))
        if typed_connect_options:
            raise RSConnectException(
                f"Posit Connect options ({', '.join(typed_connect_options)}) may not be passed \
alongside Posit Connect Cloud. See command help for further details."
            )
        typed_spcs_options = _get_present_options(spcs_options, ctx, ignore_sources=("ENVIRONMENT",))
        if typed_spcs_options:
            raise RSConnectException(
                f"SPCS options ({', '.join(typed_spcs_options)}) may not be passed \
alongside Posit Connect Cloud. See command help for further details."
            )
        if len(present_connect_cloud_options) == 1:
            raise RSConnectException(
                "--client-id and --client-secret must be provided together for Posit Connect Cloud. \
Omit both to log in interactively. See command help for further details."
            )
        # -A/--account is shared with shinyapps.io, so return before the
        # all-or-nothing check below, which would demand a token and secret.
        return

    # A nickname, or the default server when no target is named, may yet resolve
    # to Connect Cloud; only the store lookup can tell, so the executor re-checks
    # after resolution (validate_connect_cloud_credential_options). An explicit
    # non-Cloud --server or a shinyapps credential set is already decided.
    if not name and not (has_default_server and not url):
        validate_connect_cloud_credential_options(ctx, client_id, client_secret)

    # A lone -A alongside a nickname or a default server cannot be judged yet:
    # either may resolve to Connect Cloud, where -A selects the account to publish
    # to. The conflict and all-or-nothing rules below are deferred for this case;
    # the executor raises after resolution when the target turns out not to be
    # Connect Cloud. A token or secret is unambiguous shinyapps intent, so those
    # still fail fast here.
    lone_account_with_saved_server = bool(
        account_name and not token and not secret and (has_default_server or name) and not url
    )

    # In the deferred case only *typed* Connect options conflict: an exported
    # CONNECT_API_KEY or CONNECT_CA_CERTIFICATE is just the environment, and the
    # default may not even be a Connect server. Cloud targets re-check typed
    # options after resolution (validate_connect_cloud_incompatible_options).
    # With a nickname, not even a typed one is judged here: its -A may be a
    # Connect Cloud publish target, and this rule would report the mistake as a
    # shinyapps.io conflict. That case fails after resolution too, from the Cloud
    # check above or the executor's -n/-A conflict.
    if lone_account_with_saved_server:
        connect_conflicts = [] if name else _get_present_options(connect_options, ctx, ignore_sources=("ENVIRONMENT",))
    else:
        connect_conflicts = present_connect_options
    if connect_conflicts and present_shinyapps_options:
        raise RSConnectException(
            f"Connect options ({', '.join(connect_conflicts)}) may not be passed \
alongside shinyapps.io options ({', '.join(present_shinyapps_options)}). \
See command help for further details."
        )

    if snowflake_connection_name and not url:
        raise RSConnectException(
            "--snowflake-connection-name requires -s/--server to be specified. \
See command help for further details."
        )

    if present_shinyapps_options and present_spcs_options:
        raise RSConnectException(
            f"Shinyapps.io options ({', '.join(present_shinyapps_options)}) may not be passed \
alongside SPCS options ({', '.join(present_spcs_options)}). \
    See command help for further details."
        )

    if present_shinyapps_options:
        if len(present_shinyapps_options) != len(shinyapps_options) and not lone_account_with_saved_server:
            raise RSConnectException(
                "-A/--account, -T/--token, and -S/--secret must all be provided \
for shinyapps.io. See command help for further details."
            )


class PythonVersionParamType(click.ParamType):
    name = "python-version"

    def convert(self, value: str, param: Optional[click.Parameter], ctx: Optional[click.Context]):
        try:
            parts = list(map(int, value.split(".")))
            if len(parts) == 3:
                return value
            elif len(parts) == 2:
                return value + ".0"
            else:
                raise ValueError
        except (AttributeError, ValueError):
            self.fail(f"{value!r} is not a valid python version; expected 3.x or 3.x.y", param, ctx)


PYTHON_VERSION = PythonVersionParamType()
