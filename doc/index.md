# Documentation glyphwell

`glyphwell` cherche dans l'intégralité des sous-titres OpenSubtitles à l'aide d'un LLM
exécuté localement par Ollama.

## Sommaire

| Document | Contenu |
|---|---|
| [installation.md](installation.md) | Installer `uv`, l'environnement, et dimensionner le disque. |
| [configuration.md](configuration.md) | Variables `GLYPHWELL_*`, arborescence de `data/`. |
| [corpus.md](corpus.md) | **Étape 1** : récupérer l'archive OpenSubtitles et la lire. |

## Le pipeline en quatre étapes

1. **Télécharger le corpus.** L'archive OPUS *OpenSubtitles* (langue `en`, format `raw`)
   est déposée telle quelle sur le disque. Elle n'est jamais décompressée : les
   sous-titres en sont lus à la volée. → [corpus.md](corpus.md)
2. **Résoudre les titres.** Les sous-titres sont classés par identifiant IMDb ; les
   datasets IMDb officiels se joignent directement dessus et donnent le titre, le type
   (film / série / épisode), l'année et le rattachement épisode → série. Hors-ligne, sans
   clé API.
3. **Chercher.** Un manifeste YAML décrit le prompt, le modèle Ollama, les filtres de
   sélection et le schéma de sortie attendu. Chaque sous-titre est découpé en fenêtres
   glissantes de N phrases ; chaque fenêtre donne un appel au modèle.
4. **Reprendre.** L'état est persisté en SQLite au grain de la fenêtre : une recherche
   interrompue reprend à la ligne en cours, pas au début du fichier.

## État d'avancement

Seule l'étape 1 est opérationnelle à ce jour.

| Capacité | État |
|---|---|
| `glyphwell db init` / `status` / `vacuum` | opérationnel |
| `glyphwell corpus fetch` | **opérationnel** |
| `glyphwell corpus index` / `refresh` | à implémenter |
| `glyphwell metadata fetch-imdb` / `import-imdb` | à implémenter |
| `glyphwell search run` / `resume` / `status` / `export` | à implémenter |

Les commandes non implémentées sont câblées dans la CLI et exposent déjà leur aide : leur
signature est arrêtée, seul le traitement manque.

## Deux principes qui traversent le projet

**Rien n'est décompressé.** L'archive du corpus reste un fichier zip unique. Cela économise
une quarantaine de Go et des centaines de milliers de fichiers, et donne un artefact
vérifiable par une seule empreinte.

**Rien n'est perdu à l'interruption.** Le téléchargement reprend où il s'est arrêté ; la
recherche reprendra au milieu d'un sous-titre. Un `Ctrl-C` n'est jamais coûteux.
