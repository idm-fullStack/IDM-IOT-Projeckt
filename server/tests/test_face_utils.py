import sys
import os
import numpy as np
import cv2
from unittest.mock import patch, MagicMock


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.face_utils import get_face_encoding, compare_faces



def create_mock_face_image():
   
    img = np.zeros((100, 100, 3), dtype=np.uint8)
   
    return img


def encode_image_for_test(img):
    _, buffer = cv2.imencode('.jpg', img)
    return buffer.tobytes()



@patch('utils.face_utils.face_recognition.face_encodings')
def test_get_face_encoding_success(mock_face_encodings):
    
    fake_img = np.zeros((100, 100, 3), dtype=np.uint8)
    image_data = encode_image_for_test(fake_img)

  
    mock_encoding = np.array([0.1, 0.2, 0.3])
    mock_face_encodings.return_value = [mock_encoding]

    result = get_face_encoding(image_data)

    assert result is not None
    assert isinstance(result, np.ndarray)
    assert np.array_equal(result, mock_encoding)
    mock_face_encodings.assert_called_once()


@patch('utils.face_utils.face_recognition.face_encodings')
def test_get_face_encoding_no_face(mock_face_encodings):
    fake_img = np.zeros((100, 100, 3), dtype=np.uint8)
    image_data = encode_image_for_test(fake_img)

    mock_face_encodings.return_value = []

    result = get_face_encoding(image_data)

    assert result is None
    mock_face_encodings.assert_called_once()


@patch('utils.face_utils.cv2.imdecode')
@patch('utils.face_utils.face_recognition.face_encodings')
def test_get_face_encoding_cv2_decode_failure(mock_face_encodings, mock_imdecode):
    
    mock_imdecode.return_value = None

    image_data = b"invalid_image_data"

    result = get_face_encoding(image_data)

   
    assert result is None
    mock_face_encodings.assert_not_called()



@patch('utils.face_utils.face_recognition.compare_faces')
def test_compare_faces_match(mock_compare):
    known = np.array([0.1, 0.2, 0.3])
    unknown = np.array([0.11, 0.21, 0.31])
    mock_compare.return_value = [True]

    result = compare_faces(known, unknown, tolerance=0.6)

    assert result is True
    mock_compare.assert_called_once_with([known], unknown, 0.6)


@patch('utils.face_utils.face_recognition.compare_faces')
def test_compare_faces_no_match(mock_compare):
    known = np.array([0.1, 0.2, 0.3])
    unknown = np.array([0.9, 0.8, 0.7])
    mock_compare.return_value = [False]

    result = compare_faces(known, unknown, tolerance=0.6)

    assert result is False
    mock_compare.assert_called_once_with([known], unknown, 0.6)



