"""Console Rich unique du projet.

Rich ne coordonne un affichage vivant (`Progress`, `Live`) avec les écritures ordinaires
que si les deux passent par la **même** `Console` : chacune tient sa propre position de
curseur. Deux instances distinctes — celle d'une barre de progression et celle du
`RichHandler` de la journalisation — se disputent le terminal, et la moindre ligne de
journal émise pendant un téléchargement vient hacher la barre.

D'où cette instance unique, partagée par les sous-commandes et par la journalisation.
Ne pas construire de `Console()` ailleurs.
"""

from typing import Final

from rich.console import Console

__all__ = ["console"]

console: Final = Console()
