#!/usr/bin/env python3
"""
Test des imports pour diagnostiquer les problèmes
"""

def test_imports():
    """Teste tous les imports nécessaires"""
    print("=== Test des imports pour Desync Checker ===\n")
    
    imports_to_test = [
        ("sys", "Système Python"),
        ("cv2", "OpenCV"), 
        ("numpy", "NumPy"),
        ("librosa", "Librosa"),
        ("tempfile", "Fichiers temporaires"),
        ("os", "Système d'exploitation"),
        ("scipy.signal", "SciPy Signal"),
        ("PyQt6.QtWidgets", "PyQt6 Widgets"),
        ("PyQt6.QtGui", "PyQt6 GUI"),
        ("PyQt6.QtCore", "PyQt6 Core"),
        ("moviepy.editor", "MoviePy Editor")
    ]
    
    success_count = 0
    
    for module_name, description in imports_to_test:
        try:
            __import__(module_name)
            print(f"✅ {description} ({module_name}) - OK")
            success_count += 1
        except ImportError as e:
            print(f"❌ {description} ({module_name}) - ERREUR: {e}")
        except Exception as e:
            print(f"⚠️ {description} ({module_name}) - ERREUR INATTENDUE: {e}")
    
    print(f"\n=== Résultat: {success_count}/{len(imports_to_test)} modules importés avec succès ===")
    
    if success_count == len(imports_to_test):
        print("🎉 Tous les modules sont disponibles !")
        return True
    else:
        print("⚠️ Certains modules manquent. Installation nécessaire.")
        return False

def test_basic_functionality():
    """Teste les fonctionnalités de base"""
    print("\n=== Test des fonctionnalités de base ===\n")
    
    try:
        import numpy as np
        import cv2
        print("✅ Test NumPy + OpenCV - OK")
        
        # Test de création d'une image de test
        test_image = np.zeros((100, 100, 3), dtype=np.uint8)
        print("✅ Création d'image de test - OK")
        
        # Test de conversion en gris
        gray = cv2.cvtColor(test_image, cv2.COLOR_BGR2GRAY)
        print("✅ Conversion en niveaux de gris - OK")
        
        return True
    except Exception as e:
        print(f"❌ Test des fonctionnalités de base - ERREUR: {e}")
        return False

if __name__ == "__main__":
    imports_ok = test_imports()
    if imports_ok:
        test_basic_functionality()
        print("\n✅ Diagnostic terminé - L'application devrait fonctionner !")
    else:
        print("\n❌ Diagnostic terminé - Installation de dépendances requise.")