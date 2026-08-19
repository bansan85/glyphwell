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

Quatre pièges rencontrés, à ne pas réintroduire :

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
- **Une seule `Console` Rich.** Elle vit dans [console.py](src/glyphwell/console.py) et
  personne n'en construit d'autre — ni les sous-commandes, ni le `RichHandler` de
  [logging.py](src/glyphwell/logging.py), qui la reçoit explicitement. Rich ne coordonne un
  affichage vivant (`Progress`, `Live`) avec les écritures ordinaires que si les deux passent
  par la *même* instance : chacune tient sa propre position de curseur. Avec deux consoles, la
  moindre ligne de journal émise pendant un téléchargement s'écrit par-dessus la barre de
  progression. `RichHandler()` sans argument prend la console globale de Rich — c'est
  précisément le piège.

## 4. Sources de données et leurs pièges

### Corpus OPUS OpenSubtitles (`opustools`)

- Corpus `OpenSubtitles`, version **`v2024`**, langue `en`, préprocessing **`raw`** (texte non
  tokenisé, balises `<s id="...">` et `<time>`). Le format `xml`/parsed découpe en `<w>` — inutile ici.
  L'index connaît sept releases (`v1`, `v2011`, `v2012`, `v2013`, `v2016`, `v2018`, `v2024`) ;
  `v2024` est la plus récente et la plus complète.
- **L'archive zip n'est jamais décompressée.** Elle *est* le corpus : les sous-titres en sont
  lus membre par membre via [corpus/archive.py](src/glyphwell/corpus/archive.py). On évite
  ainsi des dizaines de Go et des centaines de milliers d'inodes, et le corpus reste un
  artefact unique vérifiable par une seule empreinte. Deux conséquences à connaître :
  `zipfile` charge tout le répertoire central à l'ouverture (~150 Mo pour 400 000 membres),
  et les lectures concurrentes sur un même handle se sérialisent — **un handle par thread**.
- Arborescence interne, **préfixe compris** :
  `<corpus>/<preprocessing>/<langue>/<année>/<imdb_id>/<opensubtitles_file_id>.xml`, par
  exemple `OpenSubtitles/raw/fr/2022/1596342/1957893755.xml`. L'identifiant IMDb y est **nu**
  (`1596342` → `tt1596342`). Le dernier segment est l'identifiant du sous-titre **sur
  opensubtitles.org**, pas un identifiant OPUS : il désigne une traduction précise là où
  l'`ImdbId` désigne l'œuvre. Ne pas confondre les deux — c'est la raison d'être des alias
  distincts de [types.py](src/glyphwell/types.py).
- Les membres de sous-titres sont des `.xml` **simples** : le zip est le seul niveau de
  compression. `corpus fetch` compte les membres au suffixe inattendu et les signale plutôt
  que de coder défensivement contre un cas hypothétique. Les fichiers de service `INFO`,
  `README`, `LICENSE` à la racine de l'archive sont comptés à part, sans alarme.
- L'attribut `id` des balises `<s>` est la clé de la reprise. Il est ordonné mais pas
  nécessairement contigu ni purement numérique — le traiter comme un ordinal opaque.
- Les XML OPUS ne sont pas toujours bien formés : `lxml` avec `recover=True`.

#### Pièges d'`opustools` et de l'API OPUS

Tous vérifiés contre `opustools` 1.8.3 et l'index en ligne. Ne pas les réintroduire.

- **Le stub était faux.** La vraie signature est `OpusGet(source, target, directory, release,
  preprocess, list_resources, list_languages, list_corpora, download_dir, local_db,
  suppress_prompts, database)` : `directory` est le *nom du corpus*, `source` la *langue*.
  `get_corpora_data()` ne prend aucun argument et rend une taille **formatée en chaîne**.
  Ne jamais réécrire [le stub](stubs/opustools/__init__.pyi) de mémoire.
- **`OpusGet.get_files()` n'échoue jamais** : il avale `urllib.error.URLError` pour se
  contenter d'un `print`, n'a pas de délai d'attente, ne sait pas reprendre, et écrit
  directement sous le nom définitif. Une coupure à 90 % laisserait une archive tronquée
  indiscernable d'une archive complète. D'où le transfert par `httpx` vers un `.part` repris
  par en-tête `Range`, renommé seulement une fois terminé.
- **Le joker « une espace » ne marche pas en ligne.** Le code d'`OpusGet` suggère que
  `release=" "` émet `version=` et signifie « toutes les versions » ; l'API rend alors zéro
  résultat. Il faut **omettre** le paramètre (chaîne vide, qu'`OpusGet` n'émet pas).
- **En préprocessing `raw`, l'index rend l'archive monolingue de *chaque* langue appariée**
  à celle demandée. Filtrer sur `target == ""` ne suffit pas : sans `source == language`, une
  requête `en` remonte une cinquantaine de candidats (`eo`, `es`, `en_ze`...) et le premier
  venu serait téléchargé.
- `OpusGet.url` se termine par `&`, que son propre code retire à l'appel.
- `make_file_name()` remplace la version par `latest` dans le nom quand `release == "latest"` :
  construire l'instance avec la version **concrète** de l'enregistrement.
- Le champ `size` de l'index est en **kilo-octets** et arrondi (cf. `format_size`).

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

L'archive anglaise `v2024` / `raw` : **35,8 Go** (13,7 Go pour `v2018`), plusieurs centaines
de milliers de membres. Elle n'est pas décompressée : prévoir sa taille, pas son double.
`GLYPHWELL_DATA_DIR` doit pointer vers un disque adéquat. `data/` est gitignoré et
entièrement reconstructible.

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
| `subtitle_files` | Un membre de l'archive : nom du membre, imdb_id, sha256, version OPUS. |
| `runs` | Une exécution de recherche : manifeste, son hash, son instantané, modèle, statut. |
| `run_files` | File de travail et **point de reprise** (`last_sentence_id`) par fichier. |
| `results` | Une réponse du modèle par fenêtre, avec sa plage de phrases. |
| `corpus_downloads` | Traçabilité des téléchargements OPUS. |
| `imports` | Traçabilité des imports de datasets IMDb. |

## 7. Périmètre actuel

Le squelette est en place, et **l'étape 1 est opérationnelle**.

**Opérationnel** : packaging, configuration, journalisation, schéma et migrations SQLite
(`db init` produit une base valide), câblage complet de la CLI, chargement + validation +
hachage des manifestes YAML, calcul de sha256, et surtout `glyphwell corpus fetch` —
résolution dans l'index OPUS ([corpus/opus.py](src/glyphwell/corpus/opus.py)), téléchargement
reprenable, lecture de l'archive sans décompression
([corpus/archive.py](src/glyphwell/corpus/archive.py)), traçabilité dans `corpus_downloads`
(`CorpusDownloadsRepository`, seul dépôt implémenté à ce jour).

**Stubs typés** (`raise NotImplementedError`, signatures déjà complètes et vertes sous
mypy strict) — points d'entrée pour la suite :

| Module | À implémenter |
|---|---|
| [corpus/layout.py](src/glyphwell/corpus/layout.py) | parse du nom de membre, normalisation de l'imdb_id |
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
| [db/repositories.py](src/glyphwell/db/repositories.py) | accès typé aux tables, hors `corpus_downloads` |

Ordre d'attaque suggéré : `corpus/layout.py`, `corpus/reader.py` et `corpus/chunker.py`
(fonctions pures, testables sans réseau), puis `db/repositories.py`, puis
`metadata/imdb_datasets.py`, et enfin `search/` avec `ollama/`.

Deux décisions de l'étape 1 contraignent la suite :

- `parse_entry` doit **absorber le préfixe** `<corpus>/<preprocessing>/` du nom de membre.
- `subtitle_files.rel_path` stocke le **nom de membre complet**, préfixe inclus : c'est la
  seule clé qui permette `CorpusArchive.open_member()`. `iter_corpus` prend désormais un
  `CorpusArchive`, pas une racine de répertoire.
- `corpus/reader.py` lira un flux (`IO[bytes]`) issu de l'archive, pas un `Path`.
