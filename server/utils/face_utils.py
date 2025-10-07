import cv2
import face_recognition
import numpy as np

def get_face_encoding(image_data):
    nparr = np.frombuffer(image_data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    encodings = face_recognition.face_encodings(rgb_img)
    return encodings[0] if len(encodings) > 0 else None

def compare_faces(known, unknown, tolerance=0.6):
    return face_recognition.compare_faces([known], unknown, tolerance)[0]