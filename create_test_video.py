#!/usr/bin/env python3
"""
Générateur de vidéo de test pour Desync Checker
Crée une vidéo avec un flash visuel et un bip sonore pour tester la détection de décalage
"""

import cv2
import numpy as np
import subprocess
import tempfile
import os
import shutil
from scipy.io.wavfile import write as wav_write

def create_test_video(output_path="test_video.mp4", duration=5, flash_time=1.0, bip_time=1.1, fps=30):
    """
    Crée une vidéo de test avec flash et bip
    
    Args:
        output_path: Chemin du fichier de sortie
        duration: Durée totale en secondes
        flash_time: Moment du flash en secondes
        bip_time: Moment du bip en secondes (décalage par rapport au flash)
        fps: Images par seconde
    """
    
    # Paramètres vidéo
    width, height = 1280, 720
    total_frames = int(duration * fps)
    flash_frame = int(flash_time * fps)
    
    # Créer un fichier temporaire pour la vidéo sans audio
    temp_video_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    temp_video_path = temp_video_file.name
    temp_video_file.close()
    
    # Créer la vidéo avec OpenCV
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter(temp_video_path, fourcc, fps, (width, height))
    
    print(f"Création de la vidéo de test...")
    print(f"Flash prévu à {flash_time}s (frame {flash_frame})")
    print(f"Bip prévu à {bip_time}s")
    print(f"Décalage attendu: {(bip_time - flash_time) * 1000:.2f}ms")
    
    for frame_num in range(total_frames):
        # Créer une image noire de base
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        
        # Ajouter du texte avec le temps
        current_time = frame_num / fps
        text = f"Time: {current_time:.2f}s"
        cv2.putText(frame, text, (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        
        # Ajouter le flash (image blanche)
        if frame_num == flash_frame:
            frame = np.full((height, width, 3), 255, dtype=np.uint8)  # Image complètement blanche
            cv2.putText(frame, "FLASH!", (width//2-100, height//2), 
                       cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 0), 4)
        
        # Ajouter des frames légèrement plus claires autour du flash pour une transition plus visible
        elif abs(frame_num - flash_frame) <= 2:
            brightness = 100 - abs(frame_num - flash_frame) * 30
            frame = np.full((height, width, 3), brightness, dtype=np.uint8)
            cv2.putText(frame, text, (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        
        video_writer.write(frame)
    
    video_writer.release()
    print("Vidéo créée (sans audio)")
    
    # Créer l'audio avec un bip
    print("Création de l'audio...")
    audio_file = create_test_audio(duration, bip_time)
    
    # Vérifier si l'audio a été créé
    if audio_file is None:
        print("❌ Impossible de créer l'audio")
        print(f"Vidéo sans audio créée: {temp_video_path}")
        # Copier la vidéo sans audio vers le fichier final
        shutil.copy2(temp_video_path, output_path)
        print(f"⚠️  Vidéo créée sans audio: {output_path}")
        return
    
    # Combiner vidéo et audio avec ffmpeg
    print("Combinaison vidéo + audio...")
    ffmpeg_path = find_ffmpeg()
    
    if ffmpeg_path is None:
        print("❌ FFmpeg non trouvé sur le système.")
        print("📥 Pour installer FFmpeg:")
        print("   1. Téléchargez depuis https://ffmpeg.org/download.html")
        print("   2. Ou utilisez: winget install FFmpeg")
        print("   3. Ou utilisez chocolatey: choco install ffmpeg")
        print(f"📂 Vidéo sans audio créée: {temp_video_path}")
        print(f"🔊 Audio créé: {audio_file}")
        # Copier la vidéo sans audio vers le fichier final
        shutil.copy2(temp_video_path, output_path)
        print(f"⚠️  Vidéo créée sans audio: {output_path}")
        return
    
    cmd = [
        ffmpeg_path, "-y",
        "-i", temp_video_path,
        "-i", audio_file,
        "-c:v", "libx264",
        "-c:a", "aac",
        "-shortest",
        output_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Vidéo de test créée : {output_path}")
            print(f"Décalage programmé: {(bip_time - flash_time) * 1000:.2f}ms")
        else:
            print(f"❌ Erreur ffmpeg: {result.stderr}")
            # En cas d'erreur, copier quand même la vidéo sans audio
            shutil.copy2(temp_video_path, output_path)
            print(f"⚠️  Vidéo créée sans audio: {output_path}")
    except Exception as e:
        print(f"❌ Erreur lors de l'exécution de ffmpeg: {e}")
        # En cas d'erreur, copier quand même la vidéo sans audio
        shutil.copy2(temp_video_path, output_path)
        print(f"⚠️  Vidéo créée sans audio: {output_path}")
    
    # Nettoyer les fichiers temporaires
    try:
        os.unlink(temp_video_path)
        os.unlink(audio_file)
    except:
        pass

def find_ffmpeg():
    """
    Trouve ffmpeg dans le système
    """
    # Vérifier si ffmpeg est dans le PATH
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    
    # Chercher dans des emplacements communs sur Windows
    common_paths = [
        "C:\\ffmpeg\\bin\\ffmpeg.exe",
        "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
        "C:\\Program Files (x86)\\ffmpeg\\bin\\ffmpeg.exe",
        os.path.expanduser("~\\ffmpeg\\bin\\ffmpeg.exe"),
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            return path
    
    return None

def create_test_audio(duration, bip_time, sample_rate=44100, frequency=1000):
    """
    Crée un fichier audio avec un bip à un moment précis
    """
    # Générer le silence
    samples = int(duration * sample_rate)
    audio = np.zeros(samples, dtype=np.float32)
    
    # Générer le bip (sinusoïde de 0.1 seconde)
    bip_duration = 0.1  # 100ms
    bip_samples = int(bip_duration * sample_rate)
    bip_start = int(bip_time * sample_rate)
    
    if bip_start + bip_samples <= samples:
        t = np.linspace(0, bip_duration, bip_samples)
        # Créer un bip avec enveloppe pour éviter les clics
        envelope = np.sin(np.pi * t / bip_duration)  # Enveloppe sinusoïdale
        bip = 0.5 * envelope * np.sin(2 * np.pi * frequency * t)
        audio[bip_start:bip_start + bip_samples] = bip
    
    # Sauvegarder dans un fichier temporaire
    temp_audio_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    audio_path = temp_audio_file.name
    temp_audio_file.close()
    
    # Convertir en entiers 16-bit et sauvegarder avec scipy
    audio_int16 = (audio * 32767).astype(np.int16)
    wav_write(audio_path, sample_rate, audio_int16)
    
    return audio_path

def main():
    print("=== Générateur de vidéo de test Desync Checker ===\n")
    
    # Paramètres par défaut
    output_file = "C:\\Users\\berry\\Downloads\\test_desync_video.mp4"
    flash_time = 2.0  # Flash à 2 secondes
    bip_time = 2.1    # Bip à 2.1 secondes (100ms de retard)
    
    create_test_video(
        output_path=output_file,
        duration=5,
        flash_time=flash_time,
        bip_time=bip_time
    )
    
    print(f"\n📹 Vidéo de test créée : {output_file}")
    print(f"🔍 Utilisez cette vidéo pour tester Desync Checker")
    print(f"📊 Décalage attendu : {(bip_time - flash_time) * 1000:.0f}ms (audio en retard)")

if __name__ == "__main__":
    main()