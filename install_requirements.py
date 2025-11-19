#!/usr/bin/env python3
"""
Script d'installation des dépendances pour Desync Checker
"""
import subprocess
import sys
import platform
import shutil
import os

def install_package(package):
    """Installe un package pip"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"✅ {package} installé avec succès")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Erreur lors de l'installation de {package}: {e}")
        return False

def check_ffmpeg():
    """Vérifie si FFmpeg est installé"""
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        print(f"✅ FFmpeg trouvé: {ffmpeg_path}")
        return True
    else:
        print("❌ FFmpeg non trouvé")
        return False

def install_ffmpeg():
    """Installe FFmpeg selon le système d'exploitation"""
    system = platform.system().lower()
    
    if system == "windows":
        return install_ffmpeg_windows()
    elif system == "darwin":  # macOS
        return install_ffmpeg_macos()
    elif system == "linux":
        return install_ffmpeg_linux()
    else:
        print(f"❌ Système d'exploitation non supporté: {system}")
        return False

def install_ffmpeg_windows():
    """Installe FFmpeg sur Windows"""
    print("Installation de FFmpeg sur Windows...")
    
    # Méthode 1: Téléchargement direct automatique
    if download_and_install_ffmpeg_windows():
        return True
    
    # Méthode 2: Essayer winget
    try:
        result = subprocess.run(["winget", "install", "Gyan.FFmpeg", "--accept-source-agreements", "--accept-package-agreements"], 
                              capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print("✅ FFmpeg installé avec winget")
            print("⚠️  Redémarrez votre terminal ou votre éditeur pour que FFmpeg soit disponible")
            return True
        else:
            print(f"❌ Erreur winget: {result.stderr}")
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"❌ Winget non disponible ou erreur: {e}")
    
    # Méthode 3: Essayer chocolatey
    try:
        result = subprocess.run(["choco", "install", "ffmpeg", "-y"], 
                              capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print("✅ FFmpeg installé avec chocolatey")
            return True
        else:
            print(f"❌ Erreur chocolatey: {result.stderr}")
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"❌ Chocolatey non disponible ou erreur: {e}")
    
    # Instructions manuelles
    print("📥 Installation manuelle requise:")
    print("   1. Téléchargez FFmpeg depuis: https://ffmpeg.org/download.html")
    print("   2. Ou installez winget: https://aka.ms/getwinget")
    print("   3. Puis relancez ce script")
    return False

def download_and_install_ffmpeg_windows():
    """Télécharge et installe FFmpeg directement sur Windows"""
    import urllib.request
    import zipfile
    import tempfile
    
    try:
        print("📥 Téléchargement automatique de FFmpeg...")
        
        # URL de téléchargement FFmpeg pour Windows
        ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        
        # Répertoire d'installation
        install_dir = os.path.expanduser("~\\ffmpeg")
        bin_dir = os.path.join(install_dir, "bin")
        
        # Créer le répertoire d'installation
        os.makedirs(install_dir, exist_ok=True)
        
        # Télécharger dans un fichier temporaire
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temp_file:
            print("⬇️  Téléchargement en cours...")
            urllib.request.urlretrieve(ffmpeg_url, temp_file.name)
            zip_path = temp_file.name
        
        print("📦 Extraction en cours...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Extraire tous les fichiers
            zip_ref.extractall(install_dir)
            
            # Trouver le dossier extrait
            extracted_folders = [f for f in os.listdir(install_dir) if f.startswith("ffmpeg-")]
            if extracted_folders:
                extracted_folder = extracted_folders[0]
                extracted_path = os.path.join(install_dir, extracted_folder)
                
                # Déplacer les fichiers du dossier bin
                extracted_bin = os.path.join(extracted_path, "bin")
                if os.path.exists(extracted_bin):
                    # Copier les exécutables
                    for file in os.listdir(extracted_bin):
                        if file.endswith('.exe'):
                            src = os.path.join(extracted_bin, file)
                            dst = os.path.join(bin_dir, file)
                            os.makedirs(bin_dir, exist_ok=True)
                            shutil.copy2(src, dst)
        
        # Nettoyer
        os.unlink(zip_path)
        
        # Ajouter au PATH utilisateur
        add_to_user_path(bin_dir)
        
        print(f"✅ FFmpeg installé dans: {bin_dir}")
        print("⚠️  Redémarrez votre terminal pour que FFmpeg soit disponible")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors du téléchargement automatique: {e}")
        return False

def add_to_user_path(directory):
    """Ajoute un répertoire au PATH utilisateur sur Windows"""
    try:
        # Utiliser PowerShell pour modifier le PATH utilisateur
        ps_command = f"""
        $currentPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
        if ($currentPath -notlike '*{directory}*') {{
            $newPath = $currentPath + ';{directory}'
            [Environment]::SetEnvironmentVariable('PATH', $newPath, 'User')
            Write-Host 'PATH mis à jour'
        }} else {{
            Write-Host 'Répertoire déjà dans le PATH'
        }}
        """
        
        result = subprocess.run(["powershell", "-Command", ps_command], 
                              capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print("🔧 PATH utilisateur mis à jour")
            return True
        else:
            print(f"⚠️  Impossible de mettre à jour le PATH: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"⚠️  Erreur lors de la mise à jour du PATH: {e}")
        return False

def install_ffmpeg_macos():
    """Installe FFmpeg sur macOS"""
    print("Installation de FFmpeg sur macOS...")
    try:
        result = subprocess.run(["brew", "install", "ffmpeg"], 
                              capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print("✅ FFmpeg installé avec Homebrew")
            return True
        else:
            print(f"❌ Erreur Homebrew: {result.stderr}")
            print("📥 Installez Homebrew: https://brew.sh/")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"❌ Homebrew non disponible: {e}")
        print("📥 Installez Homebrew: https://brew.sh/")
        return False

def install_ffmpeg_linux():
    """Installe FFmpeg sur Linux"""
    print("Installation de FFmpeg sur Linux...")
    
    # Essayer apt (Ubuntu/Debian)
    try:
        result = subprocess.run(["sudo", "apt", "update"], capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            result = subprocess.run(["sudo", "apt", "install", "-y", "ffmpeg"], 
                                  capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                print("✅ FFmpeg installé avec apt")
                return True
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        pass
    
    # Essayer yum (CentOS/RHEL)
    try:
        result = subprocess.run(["sudo", "yum", "install", "-y", "ffmpeg"], 
                              capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print("✅ FFmpeg installé avec yum")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        pass
    
    # Essayer pacman (Arch)
    try:
        result = subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "ffmpeg"], 
                              capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print("✅ FFmpeg installé avec pacman")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        pass
    
    print("❌ Impossible d'installer FFmpeg automatiquement")
    print("📥 Installez manuellement: sudo apt install ffmpeg (ou équivalent)")
    return False

def main():
    print("=== Installation des dépendances pour Desync Checker ===\n")
    print(f"Système détecté: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version}\n")
    
    # 1. Installation des packages Python
    print("📦 Installation des packages Python...")
    packages = [
        "PyQt6",
        "opencv-python", 
        "librosa",
        "moviepy",
        "scipy",
        "numpy"
    ]
    
    python_success_count = 0
    for package in packages:
        print(f"Installation de {package}...")
        if install_package(package):
            python_success_count += 1
        print()
    
    print(f"=== Packages Python: {python_success_count}/{len(packages)} installés ===\n")
    
    # 2. Vérification/Installation de FFmpeg
    print("🎬 Vérification de FFmpeg...")
    ffmpeg_ok = check_ffmpeg()
    
    if not ffmpeg_ok:
        print("Installation de FFmpeg...")
        ffmpeg_ok = install_ffmpeg()
        
        # Revérifier après installation
        if ffmpeg_ok:
            print("Vérification post-installation...")
            ffmpeg_ok = check_ffmpeg()
    
    print()
    
    # 3. Résumé final
    print("=== RÉSUMÉ DE L'INSTALLATION ===")
    print(f"📦 Packages Python: {python_success_count}/{len(packages)} installés")
    print(f"🎬 FFmpeg: {'✅ Disponible' if ffmpeg_ok else '❌ Non disponible'}")
    
    if python_success_count == len(packages) and ffmpeg_ok:
        print("\n🎉 Toutes les dépendances sont installées !")
        print("✅ Vous pouvez maintenant utiliser Desync Checker complètement.")
        print("\n📋 Prochaines étapes:")
        print("   1. python create_test_video.py  # Créer une vidéo de test")
        print("   2. python desync_checker_app_fixed.py  # Lancer l'application")
    elif python_success_count == len(packages):
        print("\n⚠️  Packages Python installés, mais FFmpeg manquant.")
        print("📹 Vous pouvez utiliser Desync Checker mais sans création de vidéos de test complètes.")
    else:
        print("\n❌ Certaines dépendances manquent. Vérifiez les erreurs ci-dessus.")

if __name__ == "__main__":
    main()