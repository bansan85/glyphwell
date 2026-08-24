# Configuration

Tout se configure par variables d'environnement préfixées `GLYPHWELL_`, lues aussi depuis
un fichier `.env` à la racine du dépôt. Chacune a une valeur par défaut utilisable :
`glyphwell` fonctionne sans aucune configuration.

Copier le gabarit puis l'ajuster :

```bash
cp .env.example .env
```

## Variables

| Variable | Défaut | Rôle |
|---|---|---|
| `GLYPHWELL_DATA_DIR` | `./data` | Racine de toutes les données produites. |
| `GLYPHWELL_DATABASE` | `<data_dir>/glyphwell.db` | Chemin de la base SQLite. |
| `GLYPHWELL_OPUS_CORPUS` | `OpenSubtitles` | Corpus OPUS ciblé. |
| `GLYPHWELL_OPUS_VERSION` | `v2024` | Release OPUS — la plus récente. |
| `GLYPHWELL_OPUS_LANGUAGE` | `en` | Langue du corpus. |
| `GLYPHWELL_OLLAMA_HOST` | `http://localhost:11434` | Serveur Ollama. |
| `GLYPHWELL_OLLAMA_TIMEOUT` | `300` | Délai d'attente d'un appel au modèle, en secondes. |
| `GLYPHWELL_CONCURRENCY` | `4` | Fenêtres analysées en parallèle (1 à 64). |
| `GLYPHWELL_LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. |

Trois d'entre elles ont un équivalent en ligne de commande, qui l'emporte sur
l'environnement :

```bash
uv run glyphwell --data-dir /mnt/gros-disque/glyphwell --log-level DEBUG corpus fetch
```

## Pourquoi l'anglais par défaut

`en` est la langue la mieux couverte par OpenSubtitles, et de loin. Le choix se change par
`GLYPHWELL_OPUS_LANGUAGE` ou `--language`, mais toute autre langue donne un corpus
sensiblement plus petit.

## Arborescence de `data/`

```
data/
├── corpus/                             archive OPUS — un zip par (release, langue)
│   └── OpenSubtitles_v2024_raw_en.zip
├── downloads/                          TSV des datasets IMDb
├── exports/                            résultats de `search export`
└── glyphwell.db                        catalogue et progression des recherches
```

`data/corpus/` contient une **archive**, pas une arborescence de sous-titres : elle n'est
jamais décompressée (voir [corpus.md](corpus.md)). Pendant un téléchargement, un fichier
`*.zip.part` s'y ajoute temporairement ; il porte ce qui a déjà été reçu et permet la
reprise.

L'ensemble de `data/` est ignoré par git et entièrement reconstructible : le supprimer ne
coûte que le temps de retélécharger.

## Ce que contient la base

SQLite, **délibérément sans FTS5** : le texte des sous-titres n'est ni copié ni indexé en
base. L'archive reste la seule source du texte ; la base ne porte que le catalogue et
l'état de progression.

| Table | Rôle |
|---|---|
| `titles` | Titres IMDb : type, titre, année, rattachement épisode → série. |
| `subtitle_files` | Un membre de l'archive : nom, imdb_id, empreinte, release OPUS. |
| `runs` | Une recherche : manifeste, son empreinte, son instantané, modèle, statut. |
| `run_files` | File de travail et **point de reprise** par fichier. |
| `results` | Une réponse du modèle par fenêtre, avec sa plage de phrases. |
| `corpus_downloads` | Traçabilité des téléchargements OPUS. |
| `imports` | Traçabilité des imports de datasets IMDb. |

Le schéma porte sa version dans `PRAGMA user_version`. `glyphwell db init` est idempotent
et se relance sans risque.
