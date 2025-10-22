import os
import sys
import json
import base64
import tempfile
import pytest
import sqlite3
from unittest.mock import patch, MagicMock
from datetime import datetime


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db, log_and_publish, current_attempt, templates_db, mqtt_client


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client


@pytest.fixture
def db_connection():
    conn = sqlite3.connect(':memory:')
    yield conn
    conn.close()



def test_init_db_creates_tables():
    with tempfile.NamedTemporaryFile(delete=False) as tmp_db:
        tmp_db_name = tmp_db.name

    try:
       
        with patch('app.sqlite3.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            init_db()

            
            assert mock_conn.cursor.called
            execute_calls = [call[0][0] for call in mock_conn.cursor().execute.call_args_list]
            assert any('CREATE TABLE IF NOT EXISTS users' in call for call in execute_calls)
            assert any('CREATE TABLE IF NOT EXISTS logs' in call for call in execute_calls)
            mock_conn.commit.assert_called_once()
    finally:
        if os.path.exists(tmp_db_name):
            os.remove(tmp_db_name)



def test_login_page_get(client):
    rv = client.get('/login')
    assert rv.status_code == 200
    assert b'login' in rv.data.lower()


def test_login_success(client):
    rv = client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    assert rv.status_code == 302  # redirect
    assert rv.headers['Location'].endswith('/')
    with client.session_transaction() as sess:
        assert sess['logged_in'] is True


def test_login_failure(client):
    rv = client.post('/login', data={'username': 'admin', 'password': 'wrong'})
    assert rv.status_code == 200
    assert b'error' in rv.data


def test_logout(client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
    rv = client.get('/logout')
    assert rv.status_code == 302
    with client.session_transaction() as sess:
        assert 'logged_in' not in sess


def test_index_redirects_if_not_logged_in(client):
    rv = client.get('/')
    assert rv.status_code == 302
    assert 'login' in rv.headers['Location']


def test_index_shows_logs_when_logged_in(client):
  
    client.post('/login', data={'username': 'admin', 'password': 'admin123'})

   
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO logs (user_id, status, timestamp) VALUES (?, ?, ?)",
              ('test_user', 'success', '12:00:00'))
    conn.commit()
    conn.close()

    rv = client.get('/')
    assert rv.status_code == 200
    assert b'test_user' in rv.data
    assert b'success' in rv.data



def test_api_status_unauthorized(client):
    rv = client.get('/api/status')
    assert rv.status_code == 401
    data = json.loads(rv.data)
    assert 'error' in data


def test_api_status_authorized(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    global current_attempt
    current_attempt = {"user_id": "test", "status": "success", "timestamp": "12:00:00"}
    rv = client.get('/api/status')
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert data == current_attempt



@patch('app.mqtt_client')
def test_log_and_publish(mock_mqtt, db_connection):
    global current_attempt
    current_attempt = {}

    
    with patch('app.sqlite3.connect') as mock_connect:
        mock_connect.return_value = db_connection
        log_and_publish(mock_mqtt, 'user123', 'success')

  
    c = db_connection.cursor()
    c.execute("SELECT * FROM logs")
    logs = c.fetchall()
    assert len(logs) == 1
    assert logs[0][1] == 'user123'
    assert logs[0][2] == 'success'

 
    mock_mqtt.publish.assert_called_with("auth/response", "success")

  
    assert current_attempt['user_id'] == 'user123'
    assert current_attempt['status'] == 'success'



@patch('app.get_face_encoding')
@patch('app.compare_faces')
@patch('app.sqlite3.connect')
@patch('app.mqtt_client')
def test_on_message_success(mock_mqtt, mock_sqlite, mock_compare, mock_get_encoding, client):

    user_id = "user123"
    photo_data = b"fake_image_binary"
    photo_b64 = base64.b64encode(photo_data).decode()

    mock_get_encoding.return_value = [0.1, 0.2, 0.3]
    mock_compare.return_value = True

  
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {'face_encoding': np.array([0.1, 0.2, 0.3]).tobytes()}
    mock_conn.cursor.return_value = mock_cursor
    mock_sqlite.return_value = mock_conn

    payload = json.dumps({"user_id": user_id, "photo": photo_b64})
    msg = MagicMock()
    msg.topic = "auth/attempts"
    msg.payload = payload.encode()
    app.on_message(mock_mqtt, None, msg)


    saved_path = f"registered_faces/{user_id}_latest.jpg"
    assert os.path.exists(saved_path)
    with open(saved_path, "rb") as f:
        assert f.read() == photo_data
    os.remove(saved_path)

    mock_get_encoding.assert_called_once()
    mock_compare.assert_called_once()
    mock_mqtt.publish.assert_called_with("auth/response", "success")


@patch('app.get_face_encoding')
@patch('app.sqlite3.connect')
@patch('app.mqtt_client')
def test_on_message_no_face_detected(mock_mqtt, mock_sqlite, mock_get_encoding):
    mock_get_encoding.return_value = None

    payload = json.dumps({"user_id": "user123", "photo": base64.b64encode(b"fake").decode()})
    msg = MagicMock()
    msg.topic = "auth/attempts"
    msg.payload = payload.encode()
    app.on_message(mock_mqtt, None, msg)

    mock_mqtt.publish.assert_called_with("auth/response", "failed")


@patch('app.sqlite3.connect')
@patch('app.mqtt_client')
def test_on_message_user_not_found(mock_mqtt, mock_sqlite):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor
    mock_sqlite.return_value = mock_conn

    payload = json.dumps({"user_id": "unknown", "photo": base64.b64encode(b"fake").decode()})
    msg = MagicMock()
    msg.topic = "auth/attempts"
    msg.payload = payload.encode()
    app.on_message(mock_mqtt, None, msg)

    mock_mqtt.publish.assert_called_with("auth/response", "failed")


@patch('app.mqtt_client')
def test_on_message_json_decode_error(mock_mqtt):
    msg = MagicMock()
    msg.topic = "auth/attempts"
    msg.payload = b"invalid json"
    app.on_message(mock_mqtt, None, msg)

    mock_mqtt.publish.assert_called_with("auth/response", "failed")



def test_secret_key_set():
    assert app.secret_key == 'supersecretkey'


def test_admin_credentials():
    from app import ADMIN_LOGIN, ADMIN_PASS
    assert ADMIN_LOGIN == "admin"
    assert ADMIN_PASS == "admin123"



