# ADR-0014: One HTTP client factory, and a bounded TLS escape hatch

**Status**: Accepted
**Date**: 2026-08-25

## Context

On a Debian GitLab runner, `glyphwell metadata fetch-imdb` fails before a single byte of the
dataset arrives:

```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer
certificate (_ssl.c:1000)
```

`wget` and `curl` fetch the same URL on the same machine without complaint, and the same
code path works from a Windows workstation. The message reads like a broken server; it is
not.

The cause was read in `httpx` 0.28.1 rather than guessed.
`httpx._config.create_ssl_context` builds its context with
`ssl.create_default_context(cafile=certifi.where())` and never calls `load_default_certs()`:
**`httpx` verifies against the certifi bundle, not the operating system's trust store.** A
TLS-inspecting corporate proxy makes itself trusted the only way it can — by installing its
root certificate system-wide, `update-ca-certificates` on Debian — and that is exactly the
store `httpx` does not consult. Every tool that reads the system store keeps working, which
is what makes the failure look local to glyphwell.

The same function shows the way out already exists, and this is the load-bearing detail of
this ADR: with `trust_env=True`, its default, it checks `SSL_CERT_FILE` then `SSL_CERT_DIR`
*before* falling back on certifi. An environment variable that the project neither invented
nor has to maintain restores trust with verification still on.

Two facts about this project made the fix more than a documentation note:

- **Two client factories, not one.** `corpus/opus.py` and `metadata/imdb_datasets.py` each
  had a private `_make_client()`, each repeating `follow_redirects=True` and a 60 s timeout.
  Any TLS policy would have had to be written twice, and a third download site added later
  would have missed it without failing.
- **Neither source publishes a checksum.** OPUS and IMDb both hand out bytes and nothing to
  check them against. The `sha256` glyphwell computes (ADR-0006) proves an archive is
  intact, not that it is authentic. Turning verification off therefore cannot be compensated
  for afterwards, which is what makes the escape hatch genuinely expensive and worth
  bounding.

## Decision Drivers

- Must let a download complete on a machine behind a TLS-inspecting proxy; the project is
  simply unusable there otherwise.
- Must make the secure fix the obvious one, and any insecure one deliberate, visible and
  logged.
- Must apply a single TLS policy to everything that leaves the machine, with no per-module
  drift.
- Should not add a dependency for behaviour the standard library and `httpx` already
  express.
- Should not require root, or a change to the system trust store, before anything works.

## Considered Options

### Option 1: Document `SSL_CERT_FILE` / `SSL_CERT_DIR`, change no code

- **Pros**: no code, no dependency, no new name; verification stays on and is pinned to a
  real authority; `httpx` honors both already; it fixes every other Python tool on that
  machine at the same time.
- **Cons**: it needs a bundle that already contains the proxy's root — a user who cannot
  obtain the certificate is still stuck. The project's own `.env` cannot carry it, since
  `pydantic-settings` feeds `Settings` and not `os.environ`, which is a surprise worth a
  paragraph of documentation. And on its own it leaves the two duplicated factories in
  place.

### Option 2: A `GLYPHWELL_CA_BUNDLE` setting resolved into an `ssl.SSLContext`

- **Pros**: explicit, validated by pydantic, `.env`-friendly like every other setting;
  verification stays on.
- **Cons**: `ssl.create_default_context(cafile=...)` **replaces** the default authorities
  instead of adding to them, so pointing it at the corporate root alone silently stops every
  host the proxy does not re-sign from verifying — a footgun inside the very setting meant
  to repair trust. It also duplicates `SSL_CERT_FILE` under a name only this project knows,
  with a worse failure mode than the variable it shadows.

### Option 3: Depend on `truststore` and read the OS trust store

- **Pros**: zero configuration on any machine whose store is already correct, which is
  precisely the corporate case; works the same on Linux, macOS and Windows; verification
  stays on.
- **Cons**: a runtime dependency for one line of behaviour, and an implicit global change of
  how verification resolves — a later failure becomes "which store answered?" instead of
  "certifi does not know this CA". It still cannot help when the certificate was never
  installed system-wide.

### Option 4: A `verify=False` escape hatch, with the environment fix documented first

- **Pros**: works unconditionally, including for the user who cannot get the CA file at all;
  no dependency; `--no-check-certificate` is wget's spelling, so it needs no explanation.
- **Cons**: insecure by construction, and unverifiable after the fact given that neither
  source ships a checksum. An escape hatch that works is one people keep using, so it has to
  be impossible to leave on by accident.

## Decision

Options 1 and 4, layered, on top of a single factory. Options 2 and 3 are rejected and must
not be added without superseding this ADR.

1. **`glyphwell.http.make_client(timeout=..., verify=...)` is the only place an
   `httpx.Client` is constructed.** `corpus/opus.py` and `metadata/imdb_datasets.py` keep
   their injected `client` parameter — that is how tests substitute an `httpx.MockTransport`
   — and fall back on this factory when none is given. Each downloading CLI command opens
   exactly one client and passes it down through the index lookup and the transfer.
2. **The documentation leads with `SSL_CERT_FILE` / `SSL_CERT_DIR`**, in
   `doc/configuration.md` and in the corpus troubleshooting list. That is the fix to
   prefer, and it is presented before the flag appears on the page.
3. **`Settings.verify_tls` (`GLYPHWELL_VERIFY_TLS`, default `true`) carries the policy**,
   and the global `--no-check-certificate` is the escape hatch. The two compose as
   `verify_tls=from_env.verify_tls and not no_check_certificate`: the flag can only ever
   loosen the policy, never restore verification the environment has already given up on.
4. **Every unverified client logs a warning as it is built**, naming `SSL_CERT_FILE` as
   the thing to do instead.

## Rationale

The two accepted mechanisms deliberately live at different layers. The safe fix belongs to
the environment, because `SSL_CERT_FILE` is not glyphwell's invention and setting it once
also fixes `pip` and `requests` on the same runner; the unsafe one belongs to the CLI, where
it has to be typed out and shows up in the log. Option 2 would have moved the safe fix into
glyphwell's namespace and shipped a sharper edge than the variable it duplicates. Option 3
is the tempting one — it would have made the corporate case work with no configuration at
all — but it buys that with a dependency and with verification resolving somewhere the
reader cannot see, for a population of machines whose store may be wrong anyway.

Composing the flag with `and not` rather than the project's usual override pattern is the
one asymmetry worth spelling out. For `--data-dir` or `--log-level`, absent means "no
opinion, take the environment", which `x if x is None else ...` expresses exactly. A boolean
flag has no "absent": `--no-check-certificate` not being passed cannot mean "no opinion",
because the only other value is the secure default. `and not` is what makes its absence
harmless in both directions, and it is pinned by `tests/test_cli_tls.py`, which drives all
three combinations of flag and environment through a real command.

Centralising the factory is not tidying. It is what made a single policy expressible: with
two `_make_client()`s, `verify` would have been a parameter to thread twice and to remember
a third time. `follow_redirects=True` is in the same position — load-bearing for both
sources, since the OPUS index answers with an object-storage URL that redirects — and it too
is now decided once instead of copied.

Warning on every construction rather than once per process follows from the CLI building one
client per command: that is one line per invocation. Enough that an unverified transfer is
never silent in a CI log, not enough to become noise.

## Consequences

### Positive

- A download succeeds behind a TLS-inspecting proxy: with verification on when the authority
  can be named, off only when someone asked for it in writing.
- Redirects, timeout and TLS policy are decided in one file for everything that leaves the
  machine; a future network module inherits all three by construction.
- Fewer connections opened: one client per command, reused across the OPUS index lookup and
  the archive transfer, and across both IMDb datasets.
- The insecure mode is auditable from three places at once — the command line, the log,
  and a single `Settings` field.

### Negative

- `--no-check-certificate` exists. Once it is on, nothing in the code can tell a corporate
  proxy from an attacker, and no checksum from OPUS or IMDb can settle it afterwards.
- The recommended fix lives outside the project's own configuration. `GLYPHWELL_*` in `.env`
  cannot express it, so "why doesn't `.env` work for this one" has to be documented rather
  than inferred.
- `make_client(verify=...)` is narrowed to `bool`, which hides two capabilities `httpx`
  really has: an `ssl.SSLContext`, and a path to a bundle. That is the door Options 2 and 3
  would reopen, and reopening it is a decision, not a patch.
- The fallback inside `resolve_archive` / `download_corpus` / `download` is `verify=True`
  with no way to loosen it: a library caller bypassing the CLI gets the strict default and
  must inject its own client. Deliberate — the loose default belongs to a human typing a
  flag.

### Risks

- **The hatch becomes the habit.** Bounded by the `true` default, the warning on every
  command, documentation that reaches `SSL_CERT_FILE` first, and the option being global: it
  has to appear before the subcommand, so it never hides among a subcommand's options.
- **A silent downgrade through the environment.** `GLYPHWELL_VERIFY_TLS=false` in a `.env`
  disables verification with nothing on the command line to show it. Bounded by the same
  warning line, and by the flag being unable to restore verification — which keeps the state
  visible instead of accidentally recoverable. Pinned by test.
- **`httpx` changing how it resolves the trust store.** The `SSL_CERT_FILE` / `SSL_CERT_DIR`
  precedence lives in `httpx._config.create_ssl_context`, a private function read at 0.28.1,
  not a documented contract. If it changes, the *recommended* fix stops working while
  `verify=False` keeps working — the wrong way round. Bounded only by the failure being loud
  (the same `CERTIFICATE_VERIFY_FAILED`, never a wrong result) and by this ADR naming the
  exact function, so the claim can be re-checked in one place on an upgrade.

## Related

- `http.py` (`make_client`), `Settings.verify_tls` in `config.py`, the root callback in
  `cli/__init__.py`, and `tests/test_cli_tls.py`.
- `doc/configuration.md` — "TLS certificates behind a proxy" — and the troubleshooting entry
  in `doc/corpus.md`.
- ADR-0009 (why the transfer is `httpx`'s and not `opustools`'), ADR-0006 (why the `sha256`
  proves integrity and not authenticity).
