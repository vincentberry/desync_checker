# Desync Checker - Analyseur de décalage Audio/Vidéo

## Description
Logiciel Windows pour mesurer automatiquement le décalage audio/vidéo dans une régie, à partir d'une vidéo test contenant un flash lumineux et un bip sonore.

## Problèmes résolus avec la détection du bip

### 🔧 **Corrections apportées :**

1. **Extraction audio améliorée**
   - Utilisation de FFmpeg pour extraire l'audio des vidéos
   - Méthode de fallback avec librosa direct si FFmpeg n'est pas disponible
   - Support des formats MP4, MOV, AVI, MKV

2. **Détection fréquentielle du bip**
   - Analyse spectrale pour détecter un bip à une fréquence spécifique (1000Hz par défaut)
   - Filtrage dans une bande de fréquence (±100Hz de tolérance)
   - Détection des pics avec seuils adaptatifs

3. **Amélioration de la détection du flash**
   - Calcul de la luminosité de base sur les premières frames
   - Seuil adaptatif basé sur la luminosité de base
   - Détection d'augmentation relative de luminosité (50% minimum)

4. **Interface utilisateur améliorée**
   - Messages d'état pendant l'analyse
   - Affichage détaillé du décalage (avance/retard)
   - Messages de debug dans la console

## Installation

### Prérequis
- Python 3.13
- FFmpeg (optionnel, pour une meilleure extraction audio)

### Installation automatique des dépendances
```bash
python install_requirements.py
```

### Installation manuelle
```bash
pip install PyQt6 opencv-python librosa scipy numpy
```

## Utilisation

### 1. Lancement de l'application
```bash
python desync_checker_app_fixed.py
```

### 2. Création d'une vidéo de test
```bash
python create_test_video.py
```
Cela créera une vidéo de test avec un flash à 2.0s et un bip à 2.1s (100ms de décalage).

### 3. Analyse d'une vidéo
1. Cliquer sur "Charger une vidéo PGM enregistrée"
2. Sélectionner votre fichier vidéo
3. Cliquer sur "Analyser décalage"
4. Le résultat s'affiche en millisecondes

## Formats supportés
- **Vidéo :** MP4, MOV, AVI, MKV
- **Audio :** Tous les formats supportés par la vidéo (extraction automatique)

## Paramètres de détection

### Flash
- **Seuil :** Luminosité de base + 50 points
- **Augmentation minimale :** 150% de la luminosité de base

### Bip
- **Fréquence cible :** 1000Hz (modifiable dans le code)
- **Tolérance :** ±100Hz
- **Seuil de détection :** 30% du pic maximum

## Résultats d'analyse

- **Audio en RETARD :** Valeur positive (ex: +50ms)
- **Audio en AVANCE :** Valeur négative (ex: -50ms)
- **SYNCHRONE :** 0ms

## Troubleshooting

### Le bip n'est pas détecté
1. **Vérifiez la fréquence du bip :** Le logiciel recherche par défaut un bip à 1000Hz
2. **Augmentez le volume :** Le bip doit être suffisamment fort
3. **Vérifiez la durée :** Le bip doit durer au moins 100ms
4. **Format audio :** Assurez-vous que l'audio est présent dans la vidéo

### Le flash n'est pas détecté
1. **Contraste :** Le flash doit être suffisamment lumineux par rapport au fond
2. **Durée :** Le flash doit apparaître sur au moins une frame
3. **Position :** Le flash doit occuper une partie significative de l'image

### Messages d'erreur courants
- `❌ Flash non détecté` → Ajustez la luminosité ou le contraste du flash
- `❌ Bip non détecté` → Vérifiez la fréquence et le volume du bip
- `ModuleNotFoundError` → Réinstallez les dépendances

## Fonctionnalités à venir

- [ ] Générateur intégré de vidéos de test
- [ ] Réglage des seuils dans l'interface
- [ ] Support de différentes fréquences de bip
- [ ] Compilation en executable (.exe)
- [ ] Analyse en temps réel
- [ ] Correction automatique dans OBS/Hyperdeck

## Structure des fichiers

```
Downloads/
├── desync_checker_app_fixed.py    # Application principale (CORRIGÉE)
├── install_requirements.py        # Script d'installation des dépendances
├── create_test_video.py           # Générateur de vidéo de test
├── test_dependencies.py          # Test des dépendances
└── test_desync_video.mp4         # Vidéo de test générée
```

## Pourquoi le bip n'était pas détecté avant ?

1. **Librosa ne lit pas directement l'audio des vidéos** → Extraction nécessaire
2. **Détection trop simpliste** → Simple pic max sans analyse fréquentielle
3. **Pas de filtrage** → Bruit et autres sons interfèrent
4. **Seuil inadéquat** → Trop restrictif ou trop permissif

**✅ Maintenant corrigé avec l'analyse spectrale et l'extraction audio appropriée !**