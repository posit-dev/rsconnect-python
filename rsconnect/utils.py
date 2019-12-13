
import click

def vecho(*args, **kw):
    """Echo the specified arguments only if the --verbose flag is set."""
    if click.get_current_context().params.get('verbose'):
        click.secho(*args, **kw)
