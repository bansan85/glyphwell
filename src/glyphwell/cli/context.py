"""State shared between subcommands.

Deliberately a separate module: subcommand modules need `get_context`, and
`glyphwell.cli` needs their `Typer`. Going through a third module avoids the import
cycle that direct access to the package would produce.
"""

from dataclasses import dataclass

import typer

from glyphwell.config import Settings

__all__ = ["AppContext", "get_context"]


@dataclass(frozen=True, slots=True)
class AppContext:
    """What the root callback stores in ``ctx.obj``."""

    settings: Settings


def get_context(ctx: typer.Context) -> AppContext:
    """Retrieves the application context, building it if Typer has not.

    The fallback covers a subcommand invoked directly from a test, where the root
    callback has not run.
    """
    obj = ctx.obj
    if isinstance(obj, AppContext):
        return obj
    return AppContext(settings=Settings())
