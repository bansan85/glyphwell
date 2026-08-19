"""État partagé entre les sous-commandes.

Module séparé à dessein : les modules de sous-commandes ont besoin de `get_context`, et
`glyphwell.cli` a besoin de leurs `Typer`. Passer par un troisième module évite le cycle
d'imports que produirait un accès direct au paquet.
"""

from dataclasses import dataclass

import typer

from glyphwell.config import Settings

__all__ = ["AppContext", "get_context"]


@dataclass(frozen=True, slots=True)
class AppContext:
    """Ce que le callback racine dépose dans ``ctx.obj``."""

    settings: Settings


def get_context(ctx: typer.Context) -> AppContext:
    """Récupère le contexte applicatif, en le construisant si Typer ne l'a pas fait.

    Le repli couvre l'invocation directe d'une sous-commande depuis un test, où le callback
    racine n'a pas été traversé.
    """
    obj = ctx.obj
    if isinstance(obj, AppContext):
        return obj
    return AppContext(settings=Settings())
