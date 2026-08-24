"""The project's single Rich console.

Rich only coordinates a live display (`Progress`, `Live`) with ordinary writes if both
go through the **same** `Console`: each one tracks its own cursor position. Two separate
instances — one for a progress bar, one for logging's `RichHandler` — would fight over
the terminal, and the slightest log line emitted during a download would slice through
the bar.

Hence this single instance, shared by subcommands and by logging.
Do not construct a `Console()` anywhere else.
"""

from typing import Final

from rich.console import Console

__all__ = ["console"]

console: Final = Console()
