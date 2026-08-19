# glyphwell

Recherche pilotée par LLM sur l'intégralité du corpus de sous-titres OpenSubtitles.

`glyphwell` enchaîne quatre étapes :

1. **Télécharger** les sous-titres — corpus OPUS *OpenSubtitles*, langue `en`, format `raw`
   (XML non tokenisé), via [`opustools`](https://pypi.org/project/opustools/).
2. **Résoudre les titres** — les fichiers du corpus sont classés par identifiant IMDb,
   et les datasets IMDb officiels se joignent directement sur cet identifiant : titre,
   type (film / série / épisode), année, flag adulte, rattachement épisode → série.
   Hors-ligne, sans clé API.
3. **Chercher** — un manifeste YAML décrit le prompt, le modèle Ollama, les filtres de
   sélection et le schéma de sortie attendu. Chaque sous-titre est découpé en fenêtres
   glissantes de N phrases, chaque fenêtre donne un appel au modèle.
4. **Reprendre** — l'état est persisté en SQLite au grain de la fenêtre : une recherche
   interrompue reprend à la ligne en cours, pas au début du fichier. Un sous-titre dont
   le contenu change (nouvelle release OPUS) voit ses seuls résultats invalidés.

## Installation

```bash
pip install uv          # une fois, si uv n'est pas déjà présent
uv sync --all-extras    # crée le venv, résout et installe tout
```

Copier `.env.example` en `.env` et ajuster `GLYPHWELL_DATA_DIR` : le corpus anglais
complet représente **plusieurs dizaines de Go** décompressés et des centaines de
milliers de fichiers.

## Commandes

Toutes les commandes passent par `uv run`.

```bash
# Base de données
uv run glyphwell db init                  # crée le schéma
uv run glyphwell db status                # version du schéma + compteurs
uv run glyphwell db vacuum

# Corpus de sous-titres
uv run glyphwell corpus fetch --language en          # téléchargement OPUS
uv run glyphwell corpus index                        # scan de l'arborescence -> SQLite
uv run glyphwell corpus refresh                      # re-hash + invalidation ciblée

# Métadonnées des titres
uv run glyphwell metadata fetch-imdb                 # datasets IMDb officiels
uv run glyphwell metadata import-imdb                # import en SQLite

# Recherche
uv run glyphwell search run searches/example.yaml
uv run glyphwell search status
uv run glyphwell search resume 1
uv run glyphwell search export 1 --format jsonl
```

## Écrire une recherche

Un manifeste YAML, versionnable et hashé — toute modification du fichier crée une
nouvelle recherche au lieu de réutiliser des résultats obsolètes. Voir
[`searches/example.yaml`](searches/example.yaml), entièrement commenté.

## Développement

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit install
```

Le projet est typé de bout en bout et vérifié par mypy en mode très strict
(`strict` + `disallow_any_explicit` + `disallow_any_unimported`). Les conventions
sont détaillées dans [CLAUDE.md](CLAUDE.md).

## État

Squelette initialisé : packaging, schéma SQLite, CLI, chargement des manifestes et
outillage qualité sont opérationnels. La logique métier (téléchargement OPUS, lecture
XML, import des datasets IMDb, moteur de recherche) est présente sous forme de stubs typés — voir
la section « Périmètre actuel » de [CLAUDE.md](CLAUDE.md).
