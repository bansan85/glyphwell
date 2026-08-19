# Installation

## Prérequis

- **Python 3.12** ou plus récent.
- **[`uv`](https://docs.astral.sh/uv/)** — tout passe par lui. N'installez jamais de paquet
  avec `pip` dans `.venv` : `uv.lock` et l'environnement divergeraient silencieusement.
- **Ollama** — seulement pour l'étape de recherche, pas pour récupérer le corpus.

## Mise en place

```bash
pip install uv          # une fois, si uv n'est pas déjà présent
git clone <dépôt> glyphwell && cd glyphwell
uv sync --all-extras    # crée le venv, résout et installe tout
uv run glyphwell --help
```

`uv sync` crée `.venv/` et installe le projet en mode éditable. Toutes les commandes du
projet s'invoquent ensuite par `uv run glyphwell …`.

## Espace disque

C'est le seul point de dimensionnement réel du projet.

| Élément | Taille |
|---|---|
| Archive OpenSubtitles `en` / `raw`, release `v2024` | 35,8 Go |
| Base SQLite après indexation | quelques centaines de Mo |
| Datasets IMDb (`.tsv.gz` + import) | ~1 Go |

L'archive **n'est pas décompressée** : prévoir sa taille, pas son double. Voir
[corpus.md](corpus.md#pourquoi-larchive-nest-jamais-décompressée).

Le répertoire de travail se choisit par `GLYPHWELL_DATA_DIR` — copiez `.env.example` en
`.env` et ajustez-le, ou passez `--data-dir` à chaque commande. Tout ce qu'il contient est
reconstructible : il est ignoré par git et peut être supprimé sans rien perdre d'autre que
du temps de téléchargement.

## Vérifier l'installation

```bash
uv run glyphwell --version
uv run glyphwell db init
uv run glyphwell db status
```

Pour valider toute la chaîne d'acquisition sans engager des dizaines de Go, utilisez un
petit corpus OPUS — quelques secondes suffisent :

```bash
uv run glyphwell corpus fetch --corpus Books --language en --version latest
```

## Développement

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit install
```

Le projet est typé de bout en bout, vérifié par mypy en mode très strict. Les conventions
et les décisions de conception sont consignées dans [CLAUDE.md](../CLAUDE.md).
