# Desync Checker

Outil Windows pour mesurer automatiquement un decalage audio/video a partir d'une capture contenant un flash visuel et un bip sonore.

## Projet

- Version : `1.0.0`
- Createur : `Vincent Berry`
- Licence open source : `MIT`
- GitHub : [vincentberry/desync_checker](https://github.com/vincentberry/desync_checker)

## Idee generale

Le projet repose maintenant sur un workflow unique et lisible :

1. Diagnostiquer l'environnement.
2. Generer une video de reference si besoin.
3. Charger une video et caler le flash / le bip sur la timeline.
4. Comparer l'ecart mesure avec l'ecart attendu.

L'objectif est de ne plus avoir une suite de scripts isoles, mais un petit outil coherent avec un coeur commun reutilisable.

## Ce qui a ete ameliore

- Logique detection/generation extraite dans `desync_core.py`
- Interface PyQt plus guidee avec diagnostic, menu de tests et lecture audio/video
- Calage manuel ajoute avec timeline audio, apercu frame par frame, zoom molette et marqueurs audio/video
- Support des pistes audio multiples dans la timeline, avec affichage des temps en secondes, ms et frames
- Lecture/pause, vitesses de lecture, raccourcis clavier et panneau d'infos media type MediaInfo
- CLI ajoutee pour industrialiser le process (`doctor`, `generate`, `analyze`)
- Installation simplifiee avec `requirements.txt`
- Sorties par defaut moins fragiles, sans chemins utilisateurs hardcodes

## Installation

### Prerequis

- Python 3.10+
- FFmpeg recommande pour une extraction audio plus fiable et pour generer des videos de test avec audio integre

### Installation rapide

```bash
python install_requirements.py
```

### Installation manuelle

```bash
pip install -r requirements.txt
```

## Utilisation GUI

```bash
python desync_checker_app.py
```

Dans l'application :

1. Clique sur `Diagnostiquer`
2. Ouvre le menu `Tests` si tu veux generer une video test `0 ms` ou `+100 ms`
3. Charge une capture reelle ou glisse-depose un fichier
4. Verifie ou corrige le resultat dans `Calage manuel sur timeline`
5. Si aucune piste audio n'apparait, utilise la zone `Point audio libre` ou la saisie manuelle en millisecondes
6. Utilise la molette souris pour zoomer l'audio, et un double-clic pour revenir au zoom global
7. Utilise `Espace`, `Fleche gauche/droite`, `Shift + fleches` et `Fleche haut/bas` pour naviguer rapidement
8. Coche `Audio` pour ecouter la bande son pendant la lecture

Le logo et l'icone de l'application sont stockes dans `assets/`.

## Utilisation CLI

### Verifier l'environnement

```bash
python desync_cli.py doctor
```

### Generer une video test a +100 ms

```bash
python desync_cli.py generate --output test_desync_video.mp4 --offset-ms 100
```

### Generer une video parfaitement synchronisee

```bash
python desync_cli.py generate --output test_sync_video.mp4 --offset-ms 0
```

### Analyser une video

```bash
python desync_cli.py analyze chemin\\vers\\capture.mp4
```

## Compilation EXE

```bash
python build_exe.py
```

Notes de build :

- la spec PyInstaller embarque maintenant le logo et l'icone
- si `ffmpeg` et `ffprobe` sont detectes au moment de la compilation, leurs vrais binaires sont integres dans l'executable
- l'app cherche aussi ses ressources dans le contexte PyInstaller (`_MEIPASS`) pour fonctionner en version compilee

## Interpreting resultats

- Valeur positive : audio en retard
- Valeur negative : audio en avance
- Dans la tolerance par defaut (+/- 40 ms) : considere comme synchrone

## Structure

```text
desync_core.py              # coeur detection + generation + diagnostic
desync_checker_app.py       # interface graphique PyQt
desync_cli.py               # interface en ligne de commande
create_test_video.py        # wrapper simple pour generer une video test
create_sync_test.py         # wrappers pour videos de reference
install_requirements.py     # installation des dependances Python
test_dependencies.py        # smoke test environnement
build_exe.py                # compilation PyInstaller
```

## Limites actuelles

- Le systeme reste optimise pour des signaux simples : un flash net et un bip distinct.
- Si FFmpeg manque, la detection audio peut encore fonctionner mais avec moins de fiabilite selon le format video.
- Il n'y a pas encore de mode temps reel ni de calibration multi-scenarios.

## Process recommande pour la suite

- Ajouter des profils de detection selon le type de bip ou de flash
- Sauvegarder un rapport JSON/CSV par analyse
- Ajouter un lot d'echantillons de reference pour valider les regressions
- Continuer a nettoyer les noms historiques et le packaging si besoin
