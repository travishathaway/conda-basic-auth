from __future__ import annotations

import sys
from collections.abc import MutableMapping

import click
from conda.base.context import context
from conda.models.channel import Channel

from .condarc import CondaRC, CondaRCError
from .exceptions import CondaAuthError
from .handlers import (
    AuthManager,
    basic_auth_manager,
    token_auth_manager,
    HTTP_BASIC_AUTH_NAME,
    TOKEN_NAME,
)
from .options import MutuallyExclusiveOption

# Constants
AUTH_MANAGER_MAPPING = {
    HTTP_BASIC_AUTH_NAME: basic_auth_manager,
    TOKEN_NAME: token_auth_manager,
}

SUCCESSFUL_LOGIN_MESSAGE = "Successfully stored credentials"

SUCCESSFUL_LOGOUT_MESSAGE = "Successfully removed credentials"

SUCCESSFUL_COLOR = "green"

VALID_AUTH_CHOICES = tuple(AUTH_MANAGER_MAPPING.keys())

OPTION_DEFAULT = "CONDA_AUTH_DEFAULT"


def parse_channel(ctx, param, value):
    """
    Converts the channel name into a Channel object
    """
    return Channel(value)


def get_auth_manager(options) -> tuple[str, AuthManager]:
    """
    Based on CLI options provided, return the correct auth manager to use.
    """
    auth_type = options.get("auth")

    if auth_type is not None:
        auth_manager = AUTH_MANAGER_MAPPING.get(auth_type)
        if auth_manager is None:
            raise CondaAuthError(
                f'Invalid authentication type. Valid types are: "{", ".join(VALID_AUTH_CHOICES)}"'
            )
        return auth_type, auth_manager

    # we use http basic auth when "username" or "password" are present
    if (
        "username" in option_tracker.options_used
        or "password" in option_tracker.options_used
    ):
        auth_manager = basic_auth_manager
        auth_type = HTTP_BASIC_AUTH_NAME

    # we use token auth when "token" is present
    elif "token" in option_tracker.options_used:
        auth_manager = token_auth_manager
        auth_type = TOKEN_NAME

    # default authentication handler
    else:
        auth_manager = basic_auth_manager
        auth_type = HTTP_BASIC_AUTH_NAME

    return auth_type, auth_manager


def get_channel_settings(channel: str) -> MutableMapping[str, str] | None:
    """
    Retrieve the channel settings from the context object
    """
    for settings in context.channel_settings:
        if settings.get("channel") == channel:
            return dict(**settings)


@click.group("auth")
def group():
    """
    Commands for handling authentication within conda
    """


def auth_wrapper(args):
    """Authentication commands for conda"""
    group(args=args, prog_name="conda auth", standalone_mode=True)


class OptionTracker:
    """
    Used to track whether the option was actually provided when command
    was issued
    """

    def __init__(self):
        self.options_used = set()

    def track_callback(self, ctx, param, value):
        """
        Callback used to see if the option was provided

        This is also converts the ``OPTION_DEFAULT`` value to ``None``
        """
        for opt in param.opts:
            if opt in sys.argv:
                self.options_used.add(param.name)
                break

        value = value if value != OPTION_DEFAULT else None

        return value


option_tracker = OptionTracker()


@group.command("login")
@click.option(
    "-u",
    "--username",
    help="Username to use for private channels using HTTP Basic Authentication",
    cls=MutuallyExclusiveOption,
    is_flag=False,
    flag_value=OPTION_DEFAULT,
    mutually_exclusive=("token",),
    callback=option_tracker.track_callback,
)
@click.option(
    "-p",
    "--password",
    help="Password to use for private channels using HTTP Basic Authentication",
    cls=MutuallyExclusiveOption,
    mutually_exclusive=("token",),
    callback=option_tracker.track_callback,
)
@click.option(
    "-t",
    "--token",
    help="Token to use for private channels using an API token",
    is_flag=False,
    flag_value=OPTION_DEFAULT,
    cls=MutuallyExclusiveOption,
    mutually_exclusive=("username", "password"),
    callback=option_tracker.track_callback,
)
@click.argument("channel", callback=parse_channel)
@click.pass_context
def login(ctx, channel: Channel, **kwargs):
    """
    Log in to a channel by storing the credentials or tokens associated with it
    """
    kwargs = {key: val for key, val in kwargs.items() if val is not None}
    settings = get_channel_settings(channel.canonical_name) or {}
    settings.update(kwargs)

    auth_type, auth_manager = get_auth_manager(settings)
    username: str | None = auth_manager.store(channel, settings)

    click.echo(click.style(SUCCESSFUL_LOGIN_MESSAGE, fg=SUCCESSFUL_COLOR))

    try:
        condarc = CondaRC()
        if auth_type == TOKEN_NAME:
            username = None
        condarc.update_channel_settings(channel.canonical_name, auth_type, username)
        condarc.save()
    except CondaRCError as exc:
        raise CondaAuthError(str(exc))


@group.command("logout")
@click.argument("channel", callback=parse_channel)
def logout(channel: Channel):
    """
    Log out of a by removing any credentials or tokens associated with it.
    """
    settings = get_channel_settings(channel.canonical_name)

    if settings is None:
        raise CondaAuthError("Unable to find information about logged in session.")

    auth_type, auth_manager = get_auth_manager(settings)
    auth_manager.remove_secret(channel, settings)

    click.echo(click.style(SUCCESSFUL_LOGOUT_MESSAGE, fg=SUCCESSFUL_COLOR))
