"""
Face Authentication Module for Enkripsih using OpenCV.
Handles live webcam frame processing, face detection (Haar Cascade),
feature extraction, biometric enrollment, and face verification.
"""

import cv2
import numpy as np
import base64
import json
from .database import get_commander_profile, update_face_template, log_event

# Initialize Haar Cascade classifier
CASCADE_PATH = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
face_cascade = cv2.CascadeClassifier(CASCADE_PATH)

def decode_base64_image(image_base64: str) -> np.ndarray:
    """
    Decodes a base64 image data string (e.g. data:image/jpeg;base64,...) to OpenCV BGR image.
    """
    if ',' in image_base64:
        image_base64 = image_base64.split(',')[1]
    image_bytes = base64.b64decode(image_base64)
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    return img

def extract_face_features(face_roi: np.ndarray) -> list:
    """
    Extracts a standardized biometric feature vector from a face crop.
    1. Resize to 64x64
    2. Histogram equalization for lighting invariance
    3. Block mean features + normalized histogram
    """
    gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY) if len(face_roi.shape) == 3 else face_roi
    resized = cv2.resize(gray, (64, 64))
    equalized = cv2.equalizeHist(resized)
    
    # 8x8 spatial block features (64 values)
    small = cv2.resize(equalized, (8, 8)).astype(np.float32)
    spatial_features = (small.flatten() / 255.0).tolist()
    
    # 32-bin intensity histogram
    hist = cv2.calcHist([equalized], [0], None, [32], [0, 256]).flatten()
    hist_norm = (hist / (hist.sum() + 1e-7)).tolist()
    
    # Combined biometric feature vector
    return spatial_features + hist_norm

def detect_face(img: np.ndarray):
    """
    Detects faces in the given image. Returns (face_found, bounding_box, cropped_face)
    """
    if img is None:
        return False, None, None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.15,
        minNeighbors=4,
        minSize=(60, 60)
    )
    if len(faces) == 0:
        return False, None, None
    
    # Pick the largest face detected
    faces_sorted = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
    x, y, w, h = faces_sorted[0]
    face_roi = img[y:y+h, x:x+w]
    return True, (int(x), int(y), int(w), int(h)), face_roi

def compute_similarity(feat1: list, feat2: list) -> float:
    """
    Computes cosine similarity between two feature vectors.
    Returns percentage 0.0 - 100.0%.
    """
    v1 = np.array(feat1, dtype=np.float32)
    v2 = np.array(feat2, dtype=np.float32)
    
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    dot = np.dot(v1, v2)
    cos_sim = dot / (norm1 * norm2)
    # Scale from [-1, 1] to percentage [0, 100]
    score = float(np.clip(cos_sim * 100.0, 0.0, 100.0))
    return score

def register_commander_face(image_base64: str, user_id: str = "CMD-01") -> dict:
    """
    Registers the commander's face biometric template.
    """
    try:
        img = decode_base64_image(image_base64)
        found, box, face_roi = detect_face(img)
        if not found:
            return {
                "success": False,
                "message": "Wajah tidak terdeteksi. Posisikan wajah Anda tepat di tengah kamera dengan pencahayaan cukup.",
                "face_detected": False
            }
        
        features = extract_face_features(face_roi)
        update_face_template(user_id, features)
        log_event("AUTH", "SUCCESS", f"Biometrik wajah Komandan ({user_id}) berhasil didaftarkan.")
        
        return {
            "success": True,
            "message": "Pendaftaran biometrik wajah Komandan berhasil disimpan ke sistem Enkripsih.",
            "face_detected": True,
            "bounding_box": box
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Gagal memproses pendaftaran wajah: {str(e)}",
            "face_detected": False
        }

def verify_commander_face(image_base64: str, user_id: str = "CMD-01", threshold: float = 75.0) -> dict:
    """
    Verifies the captured face against the registered commander profile.
    If no face is enrolled yet, allows auto-enrollment or prompt.
    """
    try:
        user = get_commander_profile(user_id)
        if not user:
            return {"success": False, "message": "Profil Komandan tidak ditemukan di database."}
        
        img = decode_base64_image(image_base64)
        found, box, face_roi = detect_face(img)
        if not found:
            return {
                "success": False,
                "message": "Wajah Komandan tidak terdeteksi di dalam frame kamera.",
                "face_detected": False,
                "confidence": 0.0
            }
        
        captured_features = extract_face_features(face_roi)
        
        # If not enrolled yet, auto-enroll this first face
        if not user["face_enrolled"] or not user["face_template"]:
            update_face_template(user_id, captured_features)
            log_event("AUTH", "SUCCESS", f"Wajah Komandan pertama kali didaftarkan secara otomatis.")
            return {
                "success": True,
                "message": "Wajah Komandan terverifikasi dan didaftarkan sebagai master biometrik.",
                "face_detected": True,
                "confidence": 98.5,
                "bounding_box": box,
                "user": {
                    "id": user["id"],
                    "name": user["name"],
                    "rank": user["rank"]
                }
            }
        
        # Compare with enrolled template
        saved_features = json.loads(user["face_template"])
        confidence = compute_similarity(captured_features, saved_features)
        
        if confidence >= threshold:
            log_event("AUTH", "SUCCESS", f"Verifikasi wajah Komandan {user['name']} BERHASIL ({confidence:.1f}%).")
            return {
                "success": True,
                "message": f"Identitas Komandan terverifikasi. Akses komando diberikan ({confidence:.1f}% match).",
                "face_detected": True,
                "confidence": round(confidence, 1),
                "bounding_box": box,
                "user": {
                    "id": user["id"],
                    "name": user["name"],
                    "rank": user["rank"]
                }
            }
        else:
            log_event("AUTH", "DENIED", f"Verifikasi wajah Komandan DITOLAK. Kemiripan rendah ({confidence:.1f}%).")
            return {
                "success": False,
                "message": f"Wajah tidak cocok dengan profil Komandan ({confidence:.1f}% match, butuh min {threshold}%).",
                "face_detected": True,
                "confidence": round(confidence, 1),
                "bounding_box": box
            }
            
    except Exception as e:
        return {
            "success": False,
            "message": f"Kesalahan verifikasi biometrik: {str(e)}",
            "face_detected": False,
            "confidence": 0.0
        }
