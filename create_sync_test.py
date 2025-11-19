#!/usr/bin/env python3
"""
Générateur de vidéo de test synchronisée pour Desync Checker
"""

import sys
import os

# Ajouter le répertoire actuel au chemin pour importer le module
sys.path.append(os.path.dirname(__file__))

from create_test_video import create_test_video

def main():
    print("=== Créateur de vidéo SYNCHRONISÉE ===\n")
    
    # Vidéo parfaitement synchronisée
    sync_file = "C:\\Users\\berry\\Downloads\\test_sync_video.mp4"
    flash_time = 2.0
    bip_time = 2.0  # Même moment que le flash
    
    print("Création d'une vidéo parfaitement synchronisée...")
    
    create_test_video(
        output_path=sync_file,
        duration=5,
        flash_time=flash_time,
        bip_time=bip_time
    )
    
    print(f"\n📹 Vidéo synchronisée créée : {sync_file}")
    print(f"🎯 Flash et bip au même moment : {flash_time}s")
    print(f"📊 Décalage attendu : 0ms (parfaitement synchrone)")
    
    # Vidéo légèrement désynchronisée (20ms)
    slight_desync_file = "C:\\Users\\berry\\Downloads\\test_slight_desync_video.mp4"
    flash_time_2 = 2.0
    bip_time_2 = 2.02  # 20ms de retard
    
    print("\nCréation d'une vidéo légèrement désynchronisée...")
    
    create_test_video(
        output_path=slight_desync_file,
        duration=5,
        flash_time=flash_time_2,
        bip_time=bip_time_2
    )
    
    print(f"\n📹 Vidéo légèrement désynchronisée créée : {slight_desync_file}")
    print(f"🎯 Flash à {flash_time_2}s, bip à {bip_time_2}s")
    print(f"📊 Décalage attendu : 20ms (dans la tolérance)")

if __name__ == "__main__":
    main()