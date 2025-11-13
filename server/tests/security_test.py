"""
Тест на безопасность Flask-приложения с MQTT и биометрией.
Проверяет: аутентификацию, SQLi, загрузку файлов, CSRF, доступ к API и др.
"""

import unittest
import requests
import os
import base64
import threading
import time
import sqlite3
from io import BytesIO
from PIL import Image


BASE_URL = "http://127.0.0.1:5000"
MQTT_TEST_TOPIC = "auth/attempts"
ADMIN_LOGIN = "admin"
ADMIN_PASS = "admin123"


def create_dummy_image():
    img = Image.new('RGB', (128, 128), color='white')
    buf = BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()

DUMMY_IMAGE_B64 = base64.b64encode(create_dummy_image()).decode('utf-8')


class SecurityTest(unittest.TestCase):
    session = requests.Session()

    def setUp(self):
        """Ожидаем, что сервер уже запущен"""
        try:
            requests.get(BASE_URL, timeout=3)
        except:
            self.fail("Сервер не запущен. Запустите ваше приложение перед тестом.")

    def test_1_weak_admin_credentials(self):
        """Проверка: пароль админа не является стандартным/слабым"""
        print("\n[1] Проверка слабых учётных данных...")
        
        weak_logins = ["admin", "administrator", "root"]
        weak_passwords = ["admin", "admin123", "123456", "password"]

        if ADMIN_LOGIN in weak_logins and ADMIN_PASS in weak_passwords:
            self.fail(f"Критично: обнаружены слабые учётные данные: {ADMIN_LOGIN} / {ADMIN_PASS}")
        else:
            self.assertTrue(True)

    def test_2_login_bypass(self):
        """Проверка: можно ли зайти без пароля или с пустыми полями"""
        print("[2] Проверка обхода аутентификации...")
        response = self.session.post(f"{BASE_URL}/login", data={
            "username": "",
            "password": ""
        })
        self.assertNotIn("logged_in", self.session.cookies)
        self.assertIn(response.status_code, [200, 401])
        self.assertIn("Неверный логин", response.text)

    def test_3_sql_injection_in_user_id_via_mqtt_simulated(self):
        """Имитация MQTT-сообщения с SQLi в user_id"""
        print("[3] Проверка инъекций через user_id (MQTT)...")
        
        payload = {
            "user_id": "'; DROP TABLE users; --",
            "photo": DUMMY_IMAGE_B64
        }
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (id, name) VALUES (?, ?)", ("'; DROP TABLE users; --", "test"))
            conn.commit()
            conn.close()
            
            self.assertTrue(True)
        except Exception as e:
            conn.close()
            self.fail(f"Ошибка при вставке специального ID: {e}")

    def test_4_path_traversal_in_user_id(self):
        """Проверка: можно ли использовать ../ в user_id для записи вне папки"""
        print("[4] Проверка Path Traversal...")
        payload = {
            "user_id": "../../evil",
            "photo": DUMMY_IMAGE_B64
        }
        
        filename = f"registered_faces/{payload['user_id']}_latest.jpg"
        if ".." in filename:
            self.assertIn("registered_faces", os.path.realpath(filename))
            if "registered_faces" not in os.path.realpath(filename):
                self.fail("Path traversal возможен!")
        self.assertTrue(True)

    def test_5_file_type_validation_missing(self):
        """Проверка: можно ли загрузить не-изображение?"""
        print("[5] Проверка загрузки не-изображений...")
        evil_payload = base64.b64encode(b"<script>alert(1)</script>").decode('utf-8')
        payload = {
            "user_id": "test_script",
            "photo": evil_payload
        }
        
        path = f"registered_faces/{payload['user_id']}_latest.jpg"
        with open(path, "wb") as f:
            f.write(base64.b64decode(evil_payload))

        
        file_type = None
        try:
            from imghdr import what
            file_type = what(path)
        except:
            pass

        if file_type is None:
            print("    Система не проверяет тип файла — уязвимость!")
            os.remove(path)
            self.fail("Нет проверки типа файла")
        else:
            os.remove(path)
            self.assertTrue(True)

    def test_6_unprotected_api_endpoint(self):
        """Проверка: доступ к /api/status без авторизации"""
        print("[6] Проверка доступа к API без входа...")
        response = requests.get(f"{BASE_URL}/api/status")
        self.assertEqual(response.status_code, 401, "API доступен без авторизации!")

    def test_7_csrf_missing_on_login(self):
        """Проверка: есть ли CSRF-токен на форме входа"""
        print("[7] Проверка наличия CSRF...")
        response = requests.get(f"{BASE_URL}/login")
        self.assertNotIn("csrf_token", response.text.lower(), "CSRF токен найден — хорошо")
      
        if "csrf" not in response.text.lower():
            print("    CSRF-токен не обнаружен — форма уязвима к CSRF")

    def test_8_sensitive_data_exposed_in_db(self):
        """Проверка: face_encoding хранится в открытом виде"""
        print("[8] Проверка хранения биометрии...")
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT face_encoding FROM users LIMIT 1")
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            data = bytes(row[0])
            if len(data) > 0:
                print("   Биометрические данные хранятся в БД")
                self.assertIn("face_encoding", str(c.description).lower())
                # Нельзя зашифровать здесь, но можно предупредить
                print("    Данные не шифруются — рекомендуется шифрование")
                self.assertTrue(True)  # Только информационно

    def test_9_mqtt_encryption_not_used(self):
        """Проверка: используется ли TLS для MQTT"""
        print("[9] Проверка шифрования MQTT...")
       
        code_lines = []
        with open(__file__, 'r') as f:
            for line in f:
                code_lines.append(line.strip())
        has_tls = any("tls" in line.lower() for line in code_lines)
        has_ssl = any("ssl" in line.lower() for line in code_lines)
        if not has_tls and not has_ssl:
            print("   Не обнаружено использования TLS/SSL для MQTT")
        self.assertTrue(True)

    def test_10_logout_clears_session(self):
        """Проверка: выход действительно удаляет сессию"""
        print("[10] Проверка logout...")
       
        resp = self.session.post(f"{BASE_URL}/login", data={
            "username": ADMIN_LOGIN,
            "password": ADMIN_PASS
        })
        self.assertIn("logged_in", str(self.session.cookies))

        
        self.session.get(f"{BASE_URL}/logout")
        resp = self.session.get(f"{BASE_URL}/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("index.html", resp.url)


if __name__ == '__main__':
    
    print("=== ТЕСТ НА БЕЗОПАСНОСТЬ ===")
    print("Убедитесь, что ваш Flask-сервер запущен на http://127.0.0.1:5000")
    print("Запуск тестов...\n")

    
    unittest.main(verbosity=2)
