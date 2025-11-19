#!/usr/bin/env python3
"""
Script de compilation en EXE pour Desync Checker
"""
import os
import subprocess
import sys
import shutil

def install_pyinstaller():
    """Installe PyInstaller si nécessaire"""
    try:
        import PyInstaller
        print("✅ PyInstaller déjà installé")
        return True
    except ImportError:
        print("📦 Installation de PyInstaller...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
            print("✅ PyInstaller installé avec succès")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Erreur lors de l'installation de PyInstaller: {e}")
            return False

def create_spec_file():
    """Crée un fichier .spec personnalisé pour PyInstaller"""
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['desync_checker_app_fixed.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtWidgets', 
        'PyQt6.QtGui',
        'librosa',
        'librosa.core',
        'librosa.core.audio',
        'scipy',
        'scipy.signal',
        'cv2',
        'numpy',
        'tempfile',
        'subprocess',
        'numba',
        'numba.core',
        'numba.typed',
        'sklearn',
        'sklearn.utils._cython_blas',
        'sklearn.neighbors.typedefs',
        'sklearn.neighbors.quad_tree',
        'sklearn.tree._utils'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'pandas',
        'jupyter',
        'notebook',
        'IPython',
        'tkinter'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DesyncChecker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Pas de console pour l'interface graphique
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None  # Vous pouvez ajouter un fichier .ico ici
)
'''
    
    with open("desync_checker.spec", "w", encoding="utf-8") as f:
        f.write(spec_content)
    
    print("✅ Fichier .spec créé")

def compile_exe():
    """Compile l'application en EXE"""
    print("🔨 Compilation en cours...")
    print("⏳ Cela peut prendre plusieurs minutes...")
    
    try:
        # Nettoyer les anciens builds
        if os.path.exists("build"):
            shutil.rmtree("build")
        if os.path.exists("dist"):
            shutil.rmtree("dist")
        
        # Compiler avec le fichier spec
        result = subprocess.run([
            sys.executable, "-m", "PyInstaller",
            "--clean",
            "desync_checker.spec"
        ], capture_output=True, text=True, timeout=600)
        
        if result.returncode == 0:
            print("✅ Compilation réussie !")
            
            # Vérifier que l'EXE existe
            exe_path = os.path.join("dist", "DesyncChecker.exe")
            if os.path.exists(exe_path):
                exe_size = os.path.getsize(exe_path) / (1024 * 1024)  # Taille en MB
                print(f"📁 EXE créé : {exe_path}")
                print(f"📏 Taille : {exe_size:.1f} MB")
                return True
            else:
                print("❌ EXE non trouvé après compilation")
                return False
        else:
            print(f"❌ Erreur de compilation:")
            print(result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ Timeout lors de la compilation (>10 minutes)")
        return False
    except Exception as e:
        print(f"❌ Erreur lors de la compilation: {e}")
        return False

def copy_ffmpeg():
    """Copie FFmpeg à côté de l'EXE si disponible"""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        # Chercher dans l'installation utilisateur
        user_ffmpeg = os.path.expanduser("~\\ffmpeg\\bin\\ffmpeg.exe")
        if os.path.exists(user_ffmpeg):
            ffmpeg_path = user_ffmpeg
    
    if ffmpeg_path:
        try:
            # Copier FFmpeg dans le dossier dist
            dist_ffmpeg = os.path.join("dist", "ffmpeg.exe")
            shutil.copy2(ffmpeg_path, dist_ffmpeg)
            
            # Copier aussi ffprobe si disponible
            ffprobe_path = ffmpeg_path.replace("ffmpeg.exe", "ffprobe.exe")
            if os.path.exists(ffprobe_path):
                dist_ffprobe = os.path.join("dist", "ffprobe.exe")
                shutil.copy2(ffprobe_path, dist_ffprobe)
            
            print("✅ FFmpeg copié avec l'EXE")
            return True
        except Exception as e:
            print(f"⚠️  Impossible de copier FFmpeg: {e}")
            return False
    else:
        print("⚠️  FFmpeg non trouvé - la création de vidéos ne fonctionnera pas")
        return False

def create_readme():
    """Crée un README pour l'EXE"""
    readme_content = """# Desync Checker - Version Portable

## Installation
Aucune installation requise ! Double-cliquez sur DesyncChecker.exe

## Utilisation
1. Lancez DesyncChecker.exe
2. Cliquez sur "Charger une vidéo PGM enregistrée"
3. Sélectionnez votre fichier vidéo de test
4. Cliquez sur "Analyser décalage"

## Formats supportés
- Vidéo : MP4, MOV, AVI, MKV
- Audio : Extraction automatique depuis la vidéo

## Notes
- Si FFmpeg.exe est présent dans le même dossier, la création de vidéos de test sera disponible
- L'analyse fonctionne même sans FFmpeg
- Pour des résultats optimaux, utilisez des vidéos avec flash lumineux et bip sonore distincts

## Dépannage
- Si l'application ne se lance pas, vérifiez que vous avez les droits d'exécution
- Pour les erreurs audio, vérifiez que la vidéo contient une piste audio
- Pour les erreurs de flash, vérifiez le contraste et la luminosité

Version compilée le """ + str(__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"))

    with open(os.path.join("dist", "README.txt"), "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print("✅ README créé")

def main():
    print("=== Compilation Desync Checker en EXE ===\n")
    
    # Vérifier qu'on est dans le bon répertoire
    if not os.path.exists("desync_checker_app_fixed.py"):
        print("❌ Fichier desync_checker_app_fixed.py non trouvé")
        print("Assurez-vous d'être dans le bon répertoire")
        return False
    
    # Étape 1: Installer PyInstaller
    if not install_pyinstaller():
        return False
    
    # Étape 2: Créer le fichier .spec
    create_spec_file()
    
    # Étape 3: Compiler
    if not compile_exe():
        return False
    
    # Étape 4: Copier FFmpeg (optionnel)
    copy_ffmpeg()
    
    # Étape 5: Créer la documentation
    create_readme()
    
    print("\n🎉 COMPILATION TERMINÉE !")
    print("📁 Fichiers générés dans le dossier 'dist/':")
    if os.path.exists("dist"):
        for file in os.listdir("dist"):
            file_path = os.path.join("dist", file)
            if os.path.isfile(file_path):
                size = os.path.getsize(file_path) / (1024 * 1024)
                print(f"   - {file} ({size:.1f} MB)")
    
    print("\n📋 Instructions:")
    print("1. Copiez le dossier 'dist/' sur n'importe quel PC Windows")
    print("2. Lancez DesyncChecker.exe")
    print("3. L'application fonctionne sans installation !")
    
    return True

if __name__ == "__main__":
    main()