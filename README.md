# glyphwell

Recherche pilotée par LLM sur l'intégralité du corpus de sous-titres OpenSubtitles.

`glyphwell` enchaîne quatre étapes :

1. **Télécharger** les sous-titres — corpus OPUS *OpenSubtitles*, langue `en`, format `raw`
   (XML non tokenisé), via [`opustools`](https://pypi.org/project/opustools/). L'archive
   n'est jamais décompressée : les sous-titres en sont lus à la volée.
2. **Résoudre les titres** — les sous-titres sont classés par identifiant IMDb,
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

Copier `.env.example` en `.env` et ajuster `GLYPHWELL_DATA_DIR` : l'archive anglaise
complète pèse **35,8 Go** pour la release `v2024`.

## Démarrage rapide

Deux commandes suffisent à récupérer le corpus :

```bash
uv run glyphwell db init                      # crée la base
uv run glyphwell corpus fetch --language en   # télécharge l'archive OpenSubtitles
```

`fetch` annonce l'URL et la taille avant d'engager quoi que ce soit, puis affiche le
volume, le débit et le temps restant :

```
Archive OPUS : https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2024/raw/en.zip
Release v2024, langue en, préprocessing raw — environ 35.8 GB
Destination : data\corpus
téléchargement ━━━━━━━━━━━━━━━━━━ 4.2/35.8 GB 18.4 MB/s 0:28:31
```

Coupé en route ? Relancez la même commande : le téléchargement reprend à l'octet où il
s'était arrêté. À l'arrivée, l'archive est ouverte et son contenu résumé — sans jamais être
décompressée :

```
 Archive              data\corpus\OpenSubtitles_v2024_raw_en.zip
 Taille               35.8 GB
 Empreinte            …
 Sous-titres          …
 Fichiers de service  …
Arborescence interne :
  OpenSubtitles/raw/en/2022/1596342/1957893755.xml
  …
```

Pour valider toute la chaîne en quelques secondes plutôt qu'en quelques heures, essayez
d'abord sur un petit corpus OPUS :

```bash
uv run glyphwell corpus fetch --corpus Books --language en --version latest
```

## Commandes

Toutes les commandes passent par `uv run`.

```bash
# Base de données
uv run glyphwell db init                  # crée le schéma
uv run glyphwell db status                # version du schéma + compteurs
uv run glyphwell db vacuum

# Corpus de sous-titres
uv run glyphwell corpus fetch --language en          # téléchargement OPUS
uv run glyphwell corpus index                        # scan de l'archive -> SQLite
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

## Documentation

La documentation détaillée vit dans [`doc/`](doc/index.md) :

- [installation.md](doc/installation.md) — `uv`, prérequis, espace disque
- [configuration.md](doc/configuration.md) — variables `GLYPHWELL_*`, arborescence de `data/`
- [corpus.md](doc/corpus.md) — l'étape 1 en détail : releases, reprise, arborescence
  interne de l'archive, traçabilité, dépannage

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

Le squelette est en place — packaging, schéma SQLite, CLI, chargement des manifestes,
outillage qualité — et **l'étape 1 est opérationnelle** : `glyphwell corpus fetch`
télécharge, reprend, vérifie et trace l'archive OpenSubtitles.

Le reste de la logique métier (indexation de l'archive, import des datasets IMDb, moteur de
recherche) est présent sous forme de stubs typés — voir la section « Périmètre actuel » de
[CLAUDE.md](CLAUDE.md).
