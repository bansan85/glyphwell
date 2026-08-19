# CLAUDE.md

Mémoire de travail du projet `glyphwell`. Consigne ce qui **n'est pas déductible du
code** : intentions, pièges des sources de données externes, et invariants dont dépend
la correction du programme.

## 1. Objet du projet

Chercher dans l'intégralité des sous-titres OpenSubtitles à l'aide d'un LLM local.
Quatre capacités visées :

1. **Téléchargement** du corpus OPUS *OpenSubtitles* (langue `en`, format `raw`) via `opustools`.
2. **Résolution des titres** films / séries / épisodes depuis les identifiants IMDb portés
   par l'arborescence du corpus.
3. **Recherche** sur l'ensemble du corpus, pilotée par un manifeste YAML, exécutée par Ollama.
4. **Reprise** d'une recherche interrompue *au milieu d'un sous-titre* et **ré-analyse**
   des fichiers dont une version plus récente est publiée.

L'anglais est retenu parce que c'est la langue la mieux couverte par OpenSubtitles.

## 2. Commandes

**Tout passe par `uv`** (jamais `pip install` directement dans `.venv`, sinon `uv.lock`
et l'environnement divergent).

```bash
uv sync --all-extras           # installe / met à jour l'environnement
uv run glyphwell --help        # CLI
uv run pytest -q
uv run ruff check . && uv run ruff format .
uv run mypy                    # `files` est fixé dans pyproject : src + tests
```

## 3. Style et typage

Python 3.12 moderne :

- Unions natives `str | None` — jamais `Optional` / `Union`.
- Génériques builtins (`list[str]`, `dict[str, int]`) ; abstractions depuis
  `collections.abc` (`Iterator`, `Sequence`, `Mapping`, `Callable`).
- Alias de types en PEP 695 dans [types.py](src/glyphwell/types.py) : `type ImdbId = str`, etc.
  Ils documentent l'intention sans coût d'exécution.
- Objets valeur : `@dataclass(frozen=True, slots=True, kw_only=True)`.
  Données venues de l'extérieur (YAML, JSON du LLM) : modèles pydantic v2.
- Interfaces : `Protocol`, pas d'héritage — les doubles de test n'ont rien à sous-classer.
- Statuts fermés : `StrEnum`, exhaustivité vérifiée par `assert_never`.
- `pathlib.Path` partout, jamais de chemin en `str`. `Final` pour les constantes de module.
- **Générateurs obligatoires** sur tout ce qui est volumineux (lecture XML, import TSV,
  parcours du corpus). Le corpus ne tient pas en mémoire — jamais de `list(...)` global.
- Annoter les signatures publiques systématiquement ; en local, annoter seulement ce que
  mypy ne peut pas inférer (collections vides, frontières non typées, `Final`).

mypy est configuré en **mode très strict** dans `pyproject.toml`. Règles à connaître :

- **Pas d'`Any`.** `disallow_any_explicit` interdit l'annotation `Any`. Aux frontières non
  typées (`yaml.safe_load`, réponse JSON du modèle) on annote `object`, puis on resserre
  immédiatement par pydantic ou par narrowing explicite. Le type de payload JSON est
  `JsonValue` / `JsonObject`, réexportés depuis pydantic dans `types.py`.
- **Pas de `# type: ignore` nu.** `ignore-without-code` impose `# type: ignore[code]`, et
  `warn_unused_ignores` supprime les ignores devenus inutiles.
- `disallow_any_unimported` interdit `ignore_missing_imports` : une dépendance non typée
  exige un stub local dans [stubs/](stubs/). C'est le cas d'`opustools`
  ([stubs/opustools/__init__.pyi](stubs/opustools/__init__.pyi)) — n'y déclarer que la
  surface réellement utilisée.
- **Aucune dérogation par module.** Il n'y a délibérément pas de section
  `[[tool.mypy.overrides]]` : la configuration stricte passe telle quelle sur `src/` comme
  sur `tests/`, décorateurs Typer et pytest inclus. Si une future dépendance impose une
  dérogation, la restreindre au module concerné et l'expliquer ici.

Deux pièges rencontrés, à ne pas réintroduire :

- **PEP 695 et Typer.** Typer introspecte les annotations à l'exécution et ne sait pas
  déballer un `TypeAliasType`. Un `type X = Literal[...]` utilisé dans une signature de
  commande fait échouer la construction de la CLI (`RuntimeError: Type not yet supported`).
  D'où l'alias implicite `LogLevel = Literal[...]` dans [config.py](src/glyphwell/config.py).
  Pydantic, lui, gère très bien les alias PEP 695 : la règle générale reste PEP 695, avec
  cette exception documentée sur place.
- **Plugin mypy de pydantic.** `init_typed = true` interdit `Settings(**overrides)` : le
  déballage d'un dictionnaire n'est pas vérifiable. Construire l'objet avec des mots-clés
  explicites (cf. le callback racine de [cli/__init__.py](src/glyphwell/cli/__init__.py)).
- **Cycle d'imports de la CLI.** `AppContext` et `get_context` vivent dans
  [cli/context.py](src/glyphwell/cli/context.py), pas dans `cli/__init__.py` : les modules de
  sous-commandes en dépendent, et `cli/__init__.py` dépend de leurs `Typer`. Les importer
  depuis le paquet créerait un cycle que mypy signale par `Cannot determine type of "app"`.

## 4. Sources de données et leurs pièges

### Corpus OPUS OpenSubtitles (`opustools`)

- Corpus `OpenSubtitles`, version `v2018`, langue `en`, préprocessing **`raw`** (texte non
  tokenisé, balises `<s id="...">` et `<time>`). Le format `xml`/parsed découpe en `<w>` — inutile ici.
- Arborescence attendue : `<langue>/<année>/<imdb_id>/<opus_file_id>.xml`, avec un
  **identifiant IMDb sans préfixe `tt` et zéro-paddé** (`133093` donne `tt0133093`).
  ⚠️ Cette structure **n'est pas documentée** sur le site OPUS actuel ; elle est déduite
  de l'usage. Toute la normalisation est isolée dans
  [corpus/layout.py](src/glyphwell/corpus/layout.py) et couverte par un test sur
  échantillon — à confirmer et ajuster après le premier `corpus fetch` réel.
- Les XML restent **tels quels sur le disque** : jamais réécrits, jamais réindexés.
- L'attribut `id` des balises `<s>` est la clé de la reprise. Il est ordonné mais pas
  nécessairement contigu ni purement numérique — le traiter comme un ordinal opaque.
- Les XML OPUS ne sont pas toujours bien formés : `lxml` avec `recover=True`.

### Datasets IMDb officiels (seule source de métadonnées)

IMDb est la **seule** source de titres du projet, et c'est un choix délibéré : l'identifiant
que porte l'arborescence du corpus OPUS est un `tconst` IMDb, donc la jointure est directe.
Ne pas réintroduire de source tierce (TMDB ou autre) : elles sont indexées par leur propre
identifiant, pas par `tconst`, ce qui obligerait à un rapprochement approximatif sur titre et
année pour une information que les datasets IMDb donnent déjà exactement.

- `https://datasets.imdbws.com/title.basics.tsv.gz` donne `tconst`, `titleType`,
  `primaryTitle`, `originalTitle`, `isAdult`, `startYear`, `endYear`, `runtimeMinutes`, `genres`.
- `https://datasets.imdbws.com/title.episode.tsv.gz` donne `tconst`, `parentTconst`,
  `seasonNumber`, `episodeNumber`.
- TSV, **`\N` = valeur nulle** (pas une chaîne vide). Jointure directe sur `tconst`,
  100 % hors-ligne, aucune clé API. Rafraîchis quotidiennement par IMDb.

Ce que les datasets IMDb ne donnent pas : aucune mesure de popularité. Si un filtre de ce
genre devient nécessaire, la voie IMDb est `title.ratings.tsv.gz` (`averageRating`,
`numVotes`), également indexé par `tconst` — et non une source tierce.

### Volume

Le corpus anglais complet : plusieurs dizaines de Go décompressés, centaines de milliers
de fichiers. `GLYPHWELL_DATA_DIR` doit pointer vers un disque adéquat. `data/` est
gitignoré et entièrement reconstructible.

## 5. Invariants de la reprise

C'est le cœur de la correction du programme. Toute modification de
[search/](src/glyphwell/search/) doit les préserver.

1. **Grain = la fenêtre.** Un sous-titre est découpé en fenêtres glissantes de
   `chunk.size` phrases avec `chunk.overlap` de recouvrement. Un appel LLM par fenêtre.
2. **`run_files.last_sentence_id` est le point de reprise.** Il vaut l'id de la dernière
   phrase effectivement couverte par une fenêtre dont le résultat est committé.
3. **Une transaction par fenêtre**, qui écrit *à la fois* le résultat et l'avancement du
   curseur. Un crash ne peut donc ni perdre un résultat, ni avancer le curseur à tort.
4. **Idempotence** par `UNIQUE(run_id, file_id, chunk_index)` sur `results` plus
   `INSERT OR IGNORE` : rejouer une fenêtre ne duplique rien.
5. **Ordre déterministe** de la file (`ORDER BY rel_path`) dans
   [search/planner.py](src/glyphwell/search/planner.py) : une reprise reparcourt la même
   séquence, donc `chunk_index` désigne toujours la même fenêtre.
6. **Fraîcheur = `(opus_version, sha256)`.** `corpus refresh` recalcule le sha256 ; s'il
   diffère, seuls les `results` de **ce** fichier sont supprimés et ses `run_files`
   repassent à `pending` avec `last_sentence_id = NULL`. Le reste du run est conservé.
7. **Le hash du manifeste identifie la recherche.** Modifier le YAML change
   `runs.manifest_hash` : on crée un nouveau run au lieu de mélanger des résultats
   produits par deux prompts différents. Le YAML est archivé dans `runs.manifest_snapshot`.
8. **Arrêt propre.** Un SIGINT termine la fenêtre en cours, committe, marque le run
   `paused` — il ne laisse jamais un fichier en `in_progress` sans curseur cohérent.

## 6. Modèle de données

SQLite, **sans FTS5** : le texte des sous-titres n'est ni copié ni indexé en base — seuls
le catalogue et l'état de progression y vivent. Schéma déclaré dans
[db/schema.sql](src/glyphwell/db/schema.sql), version portée par `PRAGMA user_version`.

| Table | Rôle |
|---|---|
| `titles` | Titres IMDb : type, titre, année, rattachement épisode vers série. |
| `subtitle_files` | Un fichier XML du corpus : chemin, imdb_id, sha256, version OPUS. |
| `runs` | Une exécution de recherche : manifeste, son hash, son instantané, modèle, statut. |
| `run_files` | File de travail et **point de reprise** (`last_sentence_id`) par fichier. |
| `results` | Une réponse du modèle par fenêtre, avec sa plage de phrases. |
| `corpus_downloads` | Traçabilité des téléchargements OPUS. |
| `imports` | Traçabilité des imports de datasets IMDb. |

## 7. Périmètre actuel

Le squelette est en place. **Opérationnel** : packaging, configuration, journalisation,
schéma et migrations SQLite (`db init` produit une base valide), câblage complet de la
CLI, chargement + validation + hachage des manifestes YAML, calcul de sha256.

**Stubs typés** (`raise NotImplementedError`, signatures déjà complètes et vertes sous
mypy strict) — points d'entrée pour la suite :

| Module | À implémenter |
|---|---|
| [corpus/opus.py](src/glyphwell/corpus/opus.py) | téléchargement + extraction via `opustools` |
| [corpus/layout.py](src/glyphwell/corpus/layout.py) | parse du chemin, normalisation de l'imdb_id |
| [corpus/reader.py](src/glyphwell/corpus/reader.py) | lecture XML en streaming vers `Sentence` |
| [corpus/chunker.py](src/glyphwell/corpus/chunker.py) | fenêtre glissante size/overlap |
| [metadata/imdb_datasets.py](src/glyphwell/metadata/imdb_datasets.py) | download + import TSV |
| [metadata/resolver.py](src/glyphwell/metadata/resolver.py) | imdb_id vers `Title` |
| [ollama/client.py](src/glyphwell/ollama/client.py) | appel du modèle, retries, sortie JSON |
| [ollama/prompts.py](src/glyphwell/ollama/prompts.py) | rendu des gabarits du manifeste |
| [search/planner.py](src/glyphwell/search/planner.py) | construction de la file de travail |
| [search/engine.py](src/glyphwell/search/engine.py) | boucle, concurrence, arrêt propre |
| [search/checkpoint.py](src/glyphwell/search/checkpoint.py) | lecture/écriture du curseur |
| [search/results.py](src/glyphwell/search/results.py) | validation de la sortie, export |
| [db/repositories.py](src/glyphwell/db/repositories.py) | accès typé aux tables |

Ordre d'attaque suggéré : `corpus/layout.py`, `corpus/reader.py` et `corpus/chunker.py`
(fonctions pures, testables sans réseau), puis `db/repositories.py`, puis
`metadata/imdb_datasets.py`, et enfin `search/` avec `ollama/`.
