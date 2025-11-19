import sys
import cv2
import numpy as np
import librosa
import tempfile
import os
from scipy.signal import find_peaks
from PyQt6 import QtWidgets, QtGui, QtCore
import subprocess

class DesyncChecker(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Desync Checker – Audio/Video Offset")
        self.setGeometry(200, 200, 500, 300)

        layout = QtWidgets.QVBoxLayout()

        self.video_path = None

        self.label = QtWidgets.QLabel("Aucune vidéo chargée")
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

        btn_load = QtWidgets.QPushButton("Charger une vidéo PGM enregistrée")
        btn_load.clicked.connect(self.load_video)
        layout.addWidget(btn_load)

        self.btn_analyze = QtWidgets.QPushButton("Analyser décalage")
        self.btn_analyze.clicked.connect(self.analyze)
        self.btn_analyze.setEnabled(False)
        layout.addWidget(self.btn_analyze)

        self.result_label = QtWidgets.QLabel("")
        self.result_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.result_label)

        self.setLayout(layout)

    def load_video(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choisir vidéo",
            "",
            "Video Files (*.mp4 *.mov *.mkv *.avi)"
        )
        if path:
            self.video_path = path
            self.label.setText(f"Vidéo chargée : {path}")
            self.btn_analyze.setEnabled(True)

    def analyze(self):
        if not self.video_path:
            return

        self.result_label.setText("⏳ Analyse en cours...")
        QtWidgets.QApplication.processEvents()  # Mettre à jour l'interface

        flash_time = self.detect_flash(self.video_path)
        print(f"Flash détecté à : {flash_time}s" if flash_time else "Flash non détecté")
        
        bip_time = self.detect_bip(self.video_path)
        print(f"Bip détecté à : {bip_time}s" if bip_time else "Bip non détecté")

        if flash_time is None:
            self.result_label.setText("❌ Flash non détecté (vérifiez l'éclairage/contraste)")
            return
        if bip_time is None:
            self.result_label.setText("❌ Bip non détecté (vérifiez le volume et la fréquence du bip)")
            return

        offset_ms = (bip_time - flash_time) * 1000
        
        # Tolérance pour considérer la synchronisation (±40ms est généralement imperceptible)
        sync_tolerance = 40  # millisecondes
        
        # Déterminer si l'audio est en avance, en retard ou synchrone
        if abs(offset_ms) <= sync_tolerance:
            sync_info = f"✅ Audio et vidéo SYNCHRONES ! (écart: {offset_ms:+.1f} ms)"
            status_color = "color: green; font-weight: bold;"
        elif offset_ms > sync_tolerance:
            sync_info = f"⚠️ Audio en RETARD de {abs(offset_ms):.1f} ms"
            status_color = "color: orange; font-weight: bold;"
        else:  # offset_ms < -sync_tolerance
            sync_info = f"⚠️ Audio en AVANCE de {abs(offset_ms):.1f} ms"
            status_color = "color: red; font-weight: bold;"
        
        # Ajouter des informations sur la précision
        precision_info = "\n📊 Détection: "
        precision_info += f"Flash à {flash_time:.3f}s, Bip à {bip_time:.3f}s"
        
        result_text = f"{sync_info}{precision_info}"
        self.result_label.setText(result_text)
        self.result_label.setStyleSheet(status_color)
        print(f"Résultat: {sync_info}")
        print(f"Détails: Flash={flash_time:.3f}s, Bip={bip_time:.3f}s, Écart={offset_ms:+.1f}ms")

    def detect_flash(self, video_file):
        cap = cv2.VideoCapture(video_file)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_index = 0

        flash_time = None
        baseline_brightness = None
        
        # Calculer la luminosité de base sur les 30 premières frames pour plus de stabilité
        baseline_frames = []
        temp_cap = cv2.VideoCapture(video_file)
        for i in range(30):
            ret, frame = temp_cap.read()
            if ret:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                # Analyser différentes zones de l'image
                h, w = gray.shape
                # Zone centrale (50% de l'image)
                center_region = gray[h//4:3*h//4, w//4:3*w//4]
                # Zone complète
                full_brightness = gray.mean()
                center_brightness = center_region.mean()
                
                baseline_frames.append({
                    'full': full_brightness,
                    'center': center_brightness,
                    'max': gray.max()
                })
        temp_cap.release()
        
        if not baseline_frames:
            cap.release()
            return None
            
        # Calculer les moyennes de base
        baseline_full = np.mean([f['full'] for f in baseline_frames])
        baseline_center = np.mean([f['center'] for f in baseline_frames])
        baseline_max = np.mean([f['max'] for f in baseline_frames])
        baseline_std = np.std([f['full'] for f in baseline_frames])
        
        # Seuils adaptatifs basés sur le contraste de base
        min_increase_factor = 1.3  # Augmentation minimum de 30%
        adaptive_threshold_full = baseline_full + max(20, baseline_std * 2)
        adaptive_threshold_center = baseline_center + max(25, baseline_std * 2.5)
        
        print(f"Baseline: full={baseline_full:.1f}, center={baseline_center:.1f}, max={baseline_max:.1f}, std={baseline_std:.1f}")
        
        # Variables pour détecter le flash le plus significatif
        best_flash_time = None
        best_flash_score = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape
            
            # Analyser différentes régions
            center_region = gray[h//4:3*h//4, w//4:3*w//4]
            full_brightness = gray.mean()
            center_brightness = center_region.mean()
            max_brightness = gray.max()
            
            # Ignorer les premières frames (instabilité de début)
            if frame_index < 15:  # Ignorer les 0.5 premières secondes
                frame_index += 1
                continue
                
            # Score de flash basé sur plusieurs critères
            flash_score = 0
            
            # Critère 1: Augmentation de luminosité moyenne
            if full_brightness > adaptive_threshold_full and full_brightness > baseline_full * min_increase_factor:
                if baseline_full > 0:  # Éviter la division par zéro
                    flash_score += (full_brightness - baseline_full) / baseline_full
                else:
                    flash_score += (full_brightness - baseline_full) / 1.0  # Fallback
            
            # Critère 2: Augmentation dans la zone centrale (plus important)
            if center_brightness > adaptive_threshold_center and center_brightness > baseline_center * min_increase_factor:
                if baseline_center > 0:  # Éviter la division par zéro
                    flash_score += 2 * (center_brightness - baseline_center) / baseline_center
                else:
                    flash_score += 2 * (center_brightness - baseline_center) / 1.0  # Fallback
            
            # Critère 3: Pics de luminosité élevés
            if max_brightness > baseline_max * 1.2:  # 20% d'augmentation du pic
                flash_score += (max_brightness - baseline_max) / 255.0
            
            # Si c'est un flash significatif, le garder s'il est meilleur
            # Seuil adaptatif basé sur la luminosité de base
            min_flash_score = max(0.3, min(2.0, baseline_std / 50.0))  # Seuil adaptatif
            
            if flash_score > min_flash_score and flash_score > best_flash_score:
                best_flash_time = frame_index / fps
                best_flash_score = flash_score
                print(f"Flash candidat à {best_flash_time:.3f}s, score={flash_score:.2f}")

            frame_index += 1

        cap.release()
        
        if best_flash_time is not None:
            print(f"Flash sélectionné à {best_flash_time:.3f}s avec score={best_flash_score:.2f}")
        
        return best_flash_time

    def detect_bip_with_ffmpeg(self, video_file, target_freq=1000, freq_tolerance=150):
        """
        Détecte un bip en utilisant ffmpeg pour extraire l'audio avec analyse spectrale améliorée
        """
        temp_audio_file = None
        try:
            # Créer un fichier temporaire pour l'audio
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_audio_file = temp_file.name
            
            # Extraire l'audio avec ffmpeg avec meilleure qualité
            cmd = [
                "ffmpeg", "-i", video_file, 
                "-ac", "1", "-ar", "44100",  # Mono, 44kHz sample rate pour meilleure résolution
                "-af", "highpass=f=200,lowpass=f=8000",  # Filtrer les fréquences hors gamme utile
                "-y", temp_audio_file
            ]
            
            # Exécuter ffmpeg
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Erreur ffmpeg: {result.stderr}")
                return None
            
            # Charger l'audio avec librosa
            y, sr = librosa.load(temp_audio_file, sr=None)
            
            if len(y) == 0:
                return None
            
            # Paramètres d'analyse adaptés
            hop_length = 256  # Plus de résolution temporelle
            frame_length = 2048
            
            # Calculer le spectrogramme
            stft = librosa.stft(y, hop_length=hop_length, n_fft=frame_length)
            magnitude = np.abs(stft)
            
            # Fréquences correspondantes
            freqs = librosa.fft_frequencies(sr=sr, n_fft=frame_length)
            
            # Chercher plusieurs fréquences cibles communes pour les bips
            target_frequencies = [800, 1000, 1200, 1500, 2000]  # Fréquences typiques de bip
            best_bip_time = None
            best_score = 0
            
            for test_freq in target_frequencies:
                # Trouver les indices de fréquences proches de la fréquence de test
                freq_mask = (freqs >= test_freq - freq_tolerance) & (freqs <= test_freq + freq_tolerance)
                
                if not np.any(freq_mask):
                    continue
                
                # Sommer l'énergie dans la bande de fréquence du bip
                target_energy = np.sum(magnitude[freq_mask, :], axis=0)
                
                if len(target_energy) == 0:
                    continue
                
                # Lisser l'énergie pour réduire le bruit
                window_size = max(1, sr // hop_length // 20)  # Fenêtre de 50ms
                if window_size > 1 and len(target_energy) > window_size:
                    target_energy_smooth = np.convolve(target_energy, np.ones(window_size)/window_size, mode='same')
                else:
                    target_energy_smooth = target_energy
                
                # Seuil adaptatif basé sur la médiane (plus robuste aux pics isolés)
                energy_median = np.median(target_energy_smooth)
                energy_std = np.std(target_energy_smooth)
                threshold = energy_median + 2 * energy_std
                
                # Trouver les pics dans cette énergie
                min_height = max(
                    threshold, 
                    np.max(target_energy_smooth) * 0.25,  # Au moins 25% du pic max
                    energy_median * 3  # Ou 3x la médiane
                )
                
                peaks, properties = find_peaks(
                    target_energy_smooth, 
                    height=min_height,
                    distance=max(10, sr // hop_length // 5),  # Distance minimale entre pics (200ms)
                    width=3,  # Largeur minimum du pic
                    prominence=energy_std * 0.5  # Prominence minimum
                )
                
                if len(peaks) > 0:
                    for peak_frame in peaks:
                        candidate_time = librosa.frames_to_time(peak_frame, sr=sr, hop_length=hop_length)
                        
                        # Ignorer les bips trop précoces (première seconde)
                        if candidate_time < 1.0:
                            continue
                            
                        # Évaluer la qualité du pic
                        peak_height = target_energy_smooth[peak_frame]
                        peak_score = peak_height / (energy_median + 1e-6)  # Score relatif
                        
                        # Limiter les scores extrêmes pour éviter les faux positifs
                        peak_score = min(peak_score, 1000)  # Plafond à 1000
                        
                        if peak_score > best_score and peak_score > 5:  # Score minimum de 5
                            best_score = peak_score
                            best_bip_time = candidate_time
                            print(f"Bip candidat à {test_freq}Hz: {best_bip_time:.3f}s, score={peak_score:.2f}")
                        
                        break  # Prendre le premier pic valide
            
            if best_bip_time is not None:
                print(f"Bip sélectionné à {best_bip_time:.3f}s avec score={best_score:.2f}")
            
            return best_bip_time
            
        except Exception as e:
            print(f"Erreur dans detect_bip_with_ffmpeg: {e}")
            return None
        finally:
            # Nettoyer le fichier temporaire
            if temp_audio_file and os.path.exists(temp_audio_file):
                try:
                    os.unlink(temp_audio_file)
                except:
                    pass

    def detect_bip_simple(self, video_file):
        """
        Méthode de détection du bip simplifiée qui cherche juste le pic d'amplitude
        """
        try:
            # Essayer de charger directement avec librosa (peut ne pas marcher avec tous les formats)
            y, sr = librosa.load(video_file, sr=None)
            
            # Calculer l'énergie
            energy = np.abs(y)
            
            # Lisser l'énergie pour éviter les faux pics
            window_size = int(sr * 0.01)  # 10ms window
            if window_size > 0:
                energy_smooth = np.convolve(energy, np.ones(window_size)/window_size, mode='same')
            else:
                energy_smooth = energy
            
            # Trouver les pics
            peaks, _ = find_peaks(
                energy_smooth, 
                height=np.max(energy_smooth) * 0.5,  # Au moins 50% du pic max
                distance=int(sr * 0.1)  # Distance minimale 100ms
            )
            
            if len(peaks) == 0:
                return None
            
            # Prendre le premier pic significatif
            peak_index = peaks[0]
            bip_time = peak_index / sr
            
            return bip_time
            
        except Exception as e:
            print(f"Erreur dans detect_bip_simple: {e}")
            return None

    def detect_bip(self, video_file, target_freq=1000, freq_tolerance=100):
        """
        Détecte un bip - essaie d'abord ffmpeg, puis méthode simple
        """
        # Essayer d'abord avec ffmpeg
        bip_time = self.detect_bip_with_ffmpeg(video_file, target_freq, freq_tolerance)
        
        if bip_time is None:
            print("Méthode ffmpeg échouée, essai méthode simple...")
            # Si ça ne marche pas, essayer la méthode simple
            bip_time = self.detect_bip_simple(video_file)
        
        return bip_time


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = DesyncChecker()
    window.show()
    sys.exit(app.exec())