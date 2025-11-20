from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import paho.mqtt.client as mqtt
import sqlite3
import json
import threading
import time
import base64
import os
import numpy as np
from datetime import datetime
from utils.face_utils import get_face_encoding, compare_faces
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'supersecretkey'  
# === Настройки ===
os.makedirs("registered_faces", exist_ok=True)

# === Инициализация БД ===
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Таблица пользователей: теперь с login и password_hash
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        login TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        photo_path TEXT,
        fingerprint_template BLOB,
        face_encoding BLOB,
        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    # Таблица логов
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        status TEXT,
        timestamp TEXT
    )''')
    # Создаём админа по умолчанию (если его нет)
    admin_login = "admin"
    c.execute("SELECT * FROM users WHERE login=?", (admin_login,))
    if c.fetchone() is None:
        pwd_hash = generate_password_hash("admin123")
        c.execute(
            "INSERT INTO users (user_id, name, login, password_hash) VALUES (?, ?, ?, ?)",
            ("admin", "Администратор", admin_login, pwd_hash)
        )
    conn.commit()
    conn.close()

init_db()

# === Глобальные переменные ===
current_attempt = {"user_id": None, "status": None, "timestamp": None}

# === MQTT клиент ===
def on_connect(client, userdata, flags, rc):
    print("MQTT подключён")
    client.subscribe("auth/attempts")

def on_message(client, userdata, msg):
    global current_attempt

    if msg.topic == "auth/attempts":
        try:
            data = json.loads(msg.payload.decode())
            user_id = data.get("user_id")
            photo_b64 = data.get("photo")
            photo_data = base64.b64decode(photo_b64)

            # Сохраняем фото временно
            temp_path = f"registered_faces/{user_id}_latest.jpg"
            with open(temp_path, "wb") as f:
                f.write(photo_data)

            # Проверяем, зарегистрирован ли пользователь
            conn = sqlite3.connect('database.db')
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT face_encoding FROM users WHERE user_id = ?", (user_id,))
            row = c.fetchone()
            conn.close()

            if not row:
                log_and_publish(client, user_id, "failed", "Пользователь не зарегистрирован")
                return

            known_encoding = np.frombuffer(row['face_encoding'], dtype=np.float64)
            current_encoding = get_face_encoding(photo_data)

            if current_encoding is None:
                log_and_publish(client, user_id, "failed", "Лицо не обнаружено")
                return

            if compare_faces(known_encoding, current_encoding):
                log_and_publish(client, user_id, "success", "Доступ разрешён")
            else:
                log_and_publish(client, user_id, "failed", "Лицо не совпало")
        except Exception as e:
            print("Ошибка:", e)
            log_and_publish(client, "unknown", "failed", "Ошибка обработки")

def log_and_publish(client, user_id, status, reason=""):
    global current_attempt
    now = datetime.now().strftime("%H:%M:%S")
    current_attempt = {"user_id": user_id, "status": status, "timestamp": now}

    # Логируем
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO logs (user_id, status, timestamp) VALUES (?, ?, ?)", (user_id, status, now))
    conn.commit()
    conn.close()

    # Отправляем ответ
    client.publish("auth/response", "success" if status == "success" else "failed")
    print(f"{user_id}: {status.upper()} — {reason}")

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect("192.168.1.100", 1883, 60)

def start_mqtt():
    mqtt_client.loop_forever()

threading.Thread(target=start_mqtt, daemon=True).start()

# === Маршруты ===

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        login_input = request.form['login']
        password = request.form['password']

        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE login = ?", (login_input,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['logged_in'] = True
            session['username'] = user['name']
            session['user_id'] = user['user_id']
            return redirect(url_for('index'))
        else:
            error = "Неверный логин или пароль"

    # Передаём флаг авторизации, чтобы показать кнопку выхода
    return render_template('login.html', error=error, session_logged_in=session.get('logged_in'))

@app.route('/register', methods=['POST'])
def register():
    name = request.form['name']
    login_input = request.form['login']
    password = request.form['password']

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Проверка на уникальность
    c.execute("SELECT * FROM users WHERE login = ? OR user_id = ?", (login_input, login_input))
    if c.fetchone() is not None:
        conn.close()
        return render_template('login.html', error="Логин или ID уже заняты", session_logged_in=session.get('logged_in'))

    # Хэшируем пароль
    pwd_hash = generate_password_hash(password)
    user_id = login_input.lower()  # например, использовать логин как user_id

    c.execute(
        '''INSERT INTO users (user_id, name, login, password_hash) 
           VALUES (?, ?, ?, ?)''',
        (user_id, name, login_input, pwd_hash)
    )
    conn.commit()
    conn.close()

    # Автоматически логиним после регистрации
    session['logged_in'] = True
    session['username'] = name
    session['user_id'] = user_id
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 50")
    logs = [dict(row) for row in c.fetchall()]
    conn.close()

    return render_template('index.html', logs=logs, current=current_attempt)

@app.route('/api/status')
def api_status():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(current_attempt)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
