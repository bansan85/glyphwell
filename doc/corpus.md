# Étape 1 — récupérer le corpus OpenSubtitles

La première étape dépose sur le disque l'archive des sous-titres et vérifie qu'elle est
exploitable. Sans elle, aucune des étapes suivantes n'a de matière.

## En une commande

```bash
uv run glyphwell db init                      # une fois
uv run glyphwell corpus fetch --language en   # 35,8 Go pour la release v2024
```

L'URL et la taille sont annoncées **avant** le transfert : rien ne s'engage sans que vous
sachiez sur quoi. Une interruption n'est pas coûteuse — voir
[Reprendre un téléchargement](#reprendre-un-téléchargement-interrompu).

Pour valider toute la chaîne en quelques secondes plutôt qu'en quelques heures, visez un
petit corpus OPUS. Voici la sortie réelle d'un tel essai :

```
$ uv run glyphwell corpus fetch --corpus Books --language en --version latest
Archive OPUS : https://object.pouta.csc.fi/OPUS-Books/v1/raw/en.zip
Release v1, langue en, préprocessing raw — environ 11.4 MB
Destination : …\data\corpus
téléchargement ━━━━━━━━━━━━━━━━━━━━━ 11.4/11.4 MB 10.5 MB/s 0:00:00
 Archive              …\data\corpus\Books_v1_raw_en.zip
 Taille               11.4 MB
 Empreinte            83279cfd5aab4bfcc54654134e35c5846027241b7a72f01774f102a815797d5c
 Sous-titres          42
 Fichiers de service  3
Arborescence interne :
  Books/raw/en/Hugo_Victor-Notre_Dame_de_Paris.xml
  Books/raw/en/Doyle_Arthur_Conan-Sign_of_Four.xml
  Books/raw/en/Zola_Emile-Germinal.xml
```

Le corpus `OpenSubtitles` ajoute deux niveaux à cette arborescence, l'année et
l'identifiant IMDb — voir [Arborescence interne](#arborescence-interne).

## D'où vient le corpus

Le corpus provient d'[OPUS](https://opus.nlpl.eu/), qui republie OpenSubtitles sous une
forme exploitable par machine. `glyphwell` interroge l'index OPUS via
[`opustools`](https://pypi.org/project/opustools/) puis télécharge l'archive.

Deux choix sont fixés par défaut :

- **Corpus `OpenSubtitles`.** Modifiable par `--corpus` — utile surtout pour tester la
  chaîne sur un petit corpus.
- **Préprocessing `raw`.** C'est la seule variante qui conserve le texte non tokenisé,
  utilisable tel quel par un LLM. La variante `xml` découpe chaque phrase en balises
  `<w>` — inexploitable ici sans recoller les mots.

L'archive est nommée d'après ces choix : `OpenSubtitles_v2024_raw_en.zip`. Plusieurs
releases peuvent donc coexister dans `data/corpus/`.

## Quelle release ?

`glyphwell` vise **`v2024`** par défaut, la plus récente et la plus complète. L'index OPUS
en propose sept pour OpenSubtitles :

| Release | Taille de l'archive `en` / `raw` |
|---|---|
| `v2024` *(défaut)* | 35,8 Go |
| `v2018` | 13,7 Go |
| `v2016` | 10,4 Go |
| `v2013` | 2,9 Go |
| `v2012` | 6,6 Go |
| `v2011` | 6,2 Go |
| `v1` | 42 Mo |

Une release plus grosse veut dire plus de sous-titres, donc une recherche plus complète et
plus longue. `--version v2018` vise une release antérieure ; `--version latest` demande à
l'index la plus récente qu'il déclare, quelle qu'elle soit.

Chaque release est une acquisition distincte : les archives coexistent dans `data/corpus/`
et la table `corpus_downloads` en garde une ligne par couple (release, langue).

## Options

| Option | Défaut | Effet |
|---|---|---|
| `--language`, `-l` | `GLYPHWELL_OPUS_LANGUAGE` (`en`) | Langue du corpus. |
| `--version` | `v2024` | Release OPUS. `latest` demande la plus récente. |
| `--corpus` | `OpenSubtitles` | Nom du corpus OPUS. |
| `--dest` | `<data-dir>/corpus` | Répertoire où déposer l'archive. |
| `--force` | — | Retélécharge même si l'archive est déjà présente. |
| `--hash` | — | Calcule l'empreinte même quand le transfert n'a pas eu lieu. |

## Pourquoi l'archive n'est jamais décompressée

Décompresser l'archive anglaise coûterait plusieurs dizaines de Go supplémentaires et
créerait des centaines de milliers de fichiers. `glyphwell` s'en dispense : le zip **est**
le corpus, et chaque sous-titre en est extrait à la volée au moment où on le lit.

Trois conséquences :

- **Un artefact unique**, décrit par une seule empreinte. Vérifier que le corpus n'a pas
  changé, c'est comparer un `sha256`, pas parcourir des centaines de milliers de fichiers.
- **Un coût mémoire assumé** : `zipfile` charge tout le répertoire central à l'ouverture,
  de l'ordre de 150 Mo pour 400 000 membres. C'est le prix de l'accès direct à un membre
  quelconque, sans index annexe.
- **Un handle par thread.** Les lectures concurrentes sur un même handle se sérialisent ;
  le moteur de recherche ouvrira donc une poignée de handles indépendants.

Rien n'est jamais réécrit dans l'archive : elle est en lecture seule d'un bout à l'autre de
la vie du projet.

## Arborescence interne

Les membres de l'archive OpenSubtitles suivent cette forme :

```
<corpus>/<preprocessing>/<langue>/<année>/<imdb_id>/<opensubtitles_file_id>.xml
OpenSubtitles/raw/fr/2022/1596342/1957893755.xml
```

| Segment | Lecture |
|---|---|
| `OpenSubtitles` | nom du corpus OPUS |
| `raw` | préprocessing |
| `fr` | langue du sous-titre |
| `2022` | année de l'œuvre |
| `1596342` | identifiant IMDb **nu** — soit `tt1596342` sous sa forme canonique |
| `1957893755` | identifiant du sous-titre sur opensubtitles.org |

Les deux derniers segments ne désignent pas la même chose : `1596342` identifie l'**œuvre**,
`1957893755` identifie **une traduction précise** de cette œuvre. Un même film a un
identifiant IMDb et autant d'identifiants de sous-titres qu'il existe de versions publiées.
Ce dernier permet de remonter à la fiche d'origine :
`https://www.opensubtitles.org/en/subtitles/1957893755`.

C'est cet identifiant IMDb qui rend l'étape 2 exacte : les datasets IMDb officiels se
joignent dessus directement, sans rapprochement approximatif sur le titre.

L'archive contient aussi trois fichiers de service à sa racine — `INFO`, `README`,
`LICENSE`. Ils sont comptés à part et ne sont pas des sous-titres.

Si `corpus fetch` signale des membres à l'**extension inattendue**, l'hypothèse « tous les
sous-titres sont des `.xml` simples » a cessé d'être vraie pour cette release : c'est à
vérifier avant d'aller plus loin, car ce serait du texte que `glyphwell` ne lirait pas.

## Reprendre un téléchargement interrompu

Le transfert s'écrit dans `<archive>.zip.part` et n'est renommé qu'une fois terminé. Une
archive incomplète ne peut donc jamais être prise pour une archive complète.

Après une coupure — réseau, `Ctrl-C`, machine éteinte — relancez simplement la même
commande :

```bash
uv run glyphwell corpus fetch --language en
```

Le `.part` est repris par en-tête HTTP `Range` : les octets déjà reçus ne le sont pas une
seconde fois. La barre de progression repart de l'offset atteint, pas de zéro.

Pour repartir de zéro délibérément, `--force` ignore aussi bien l'archive existante que le
`.part`.

## L'empreinte

`sha256` sert à détecter qu'une archive a changé — donc qu'il faudra réanalyser ce qu'elle
contient.

Elle est calculée **au fil du transfert**, ce qui est gratuit : les octets passent de toute
façon par la mémoire. Mais après une reprise, une partie du fichier n'a pas traversé le
calcul, et une passe complète sur trente-cinq Go dure plusieurs minutes. `glyphwell` ne la
déclenche donc pas de lui-même : l'empreinte est alors affichée comme `non calculée`, et
`--hash` la force.

## Traçabilité

Chaque acquisition laisse une ligne dans la table `corpus_downloads`, écrite en `pending`
**avant** le transfert — une base absente doit faire échouer la commande tout de suite, pas
après trente-cinq Go.

```bash
sqlite3 data/glyphwell.db \
  "SELECT opus_version, language, status, downloaded_at FROM corpus_downloads"
```

| Colonne | Contenu |
|---|---|
| `status` | `pending` \| `downloaded` \| `failed` |
| `url` | URL exacte servie par l'index OPUS |
| `archive_path` | emplacement local de l'archive |
| `sha256` | empreinte, si elle a pu être calculée |
| `downloaded_at` | fin du transfert |
| `verified_at` | ouverture de l'archive et comptage des membres |

Une empreinte déjà connue n'est jamais effacée par une exécution ultérieure qui n'en
produit pas. Il n'existe pas de statut `extracted` : rien n'est extrait.

## Relancer la commande

`corpus fetch` est idempotent. Relancée sur une archive déjà présente, elle ne retélécharge
rien, revérifie l'archive et met la traçabilité à jour. C'est le moyen le plus simple de
contrôler que le corpus est en bon état.

## Dépannage

**« aucune archive monolingue … dans l'index OPUS »** — la combinaison corpus / version /
langue n'existe pas. Le message énumère les releases et les langues que l'index propose
réellement ; il s'agit le plus souvent d'une release inexistante pour cette langue.

**« index OPUS injoignable »** — l'index (`https://opus.nlpl.eu/opusapi`) n'a pas répondu.
Derrière un proxy d'entreprise, renseignez `HTTPS_PROXY`. Rien n'a été téléchargé, rien
n'est à nettoyer.

**« téléchargement interrompu … le fichier … est conservé »** — la coupure est survenue en
cours de transfert. Relancez la même commande : elle reprendra.

**« … n'est pas une archive zip exploitable »** — le fichier présent est tronqué ou
corrompu. `--force` le remplace.

**Disque plein** — le message d'écriture nomme le `.part` concerné. Libérez de la place ou
déplacez la destination (`--dest`, ou `GLYPHWELL_DATA_DIR`), puis relancez : ce qui a déjà
été téléchargé est conservé.

## Et ensuite

L'archive est en place, mais son contenu n'est pas encore catalogué. `glyphwell corpus
index` — pas encore implémenté — parcourra ses membres et alimentera la table
`subtitle_files`.
