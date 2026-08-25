"""The single HTTP client factory for everything that leaves the machine.

Two modules download: `glyphwell.corpus.opus` (the OPUS index, then an archive of several
dozen GB) and `glyphwell.metadata.imdb_datasets` (the IMDb datasets). Both accept an
injected `httpx.Client` — that is how tests substitute a `MockTransport` — and both fall
back on the client built here, so redirects, timeout and TLS policy are decided in one
place instead of drifting apart. Nothing else constructs an `httpx.Client`.

**TLS and corporate proxies.** `httpx` verifies against **certifi**'s bundle, not the
system trust store (see `httpx._config.create_ssl_context`). Behind a TLS-inspecting
proxy, whose root certificate is typically installed system-wide, a
``CERTIFICATE_VERIFY_FAILED`` therefore happens on machines where `wget` and `curl` work
fine — they do read the system store. Two ways out, in order of preference:

1. Point `httpx` at the certificate authority to trust: ``SSL_CERT_FILE`` or
   ``SSL_CERT_DIR`` (e.g. ``SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`` on
   Debian/Ubuntu). `httpx` honors both through `trust_env`, and verification stays on.
2. `verify=False`, reached from the CLI as ``--no-check-certificate``, wget's spelling.
   Last resort: the transfer then has no protection against a man-in-the-middle, and
   neither source hands out a checksum to verify the payload after the fact.
"""

from typing import Final

import httpx

from glyphwell.logging import get_logger

__all__ = ["DEFAULT_TIMEOUT", "make_client"]

_log = get_logger(__name__)

DEFAULT_TIMEOUT: Final = 60.0
"""Timeout, in seconds, applied per block, not to the whole transfer.

An archive of several dozen GB therefore has no deadline to meet — only an obligation to
keep making progress.
"""


def make_client(*, timeout: float = DEFAULT_TIMEOUT, verify: bool = True) -> httpx.Client:
    """Builds the project's HTTP client.

    Args:
        timeout: per-block timeout, in seconds, also applied to the connection.
        verify: verify the server's TLS certificate. `False` is the
            ``--no-check-certificate`` escape hatch — see the module docstring.

    Returns:
        A client that follows redirects, which is essential for OPUS: the index returns
        an object-storage URL that redirects.
    """
    if not verify:
        # Warned on every construction rather than once per process: an unverified
        # transfer must never be silent, and the CLI builds one client per command.
        _log.warning(
            "TLS certificate verification disabled: transfers have no protection against"
            " a man-in-the-middle. Prefer SSL_CERT_FILE / SSL_CERT_DIR pointing at the"
            " certificate authority to trust."
        )
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(timeout, connect=timeout),
        verify=verify,
    )
