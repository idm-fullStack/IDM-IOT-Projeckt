#include "esp_camera.h"
#include <WiFi.h>
#include <PubSubClient.h>
#include <Adafruit_Fingerprint.h>
#include <ArduinoJson.h>
#include <base64.h>

// === Настройки WiFi ===
const char* ssid = "your_wifi_ssid";
const char* password = "your_wifi_password";

// === Настройки MQTT ===
const char* mqtt_server = "192.168.1.100"; // IP сервера с Mosquitto
WiFiClient espClient;
PubSubClient client(espClient);

// === Датчик отпечатков ===
SoftwareSerial fpSerial(17, 16);
Adafruit_Fingerprint finger = Adafruit_Fingerprint(&fpSerial);

// === Камера ===
#define PWDN_GPIO_NUM    32
#define RESET_GPIO_NUM   -1
#define XCLK_GPIO_NUM    0
#define SIOD_GPIO_NUM    26
#define SIOC_GPIO_NUM    27
#define Y9_GPIO_NUM      35
#define Y8_GPIO_NUM      34
#define Y7_GPIO_NUM      39
#define Y6_GPIO_NUM      36
#define Y5_GPIO_NUM      21
#define Y4_GPIO_NUM      19
#define Y3_GPIO_NUM      18
#define Y2_GPIO_NUM      5
#define VSYNC_GPIO_NUM   25
#define HREF_GPIO_NUM    23
#define PCLK_GPIO_NUM    22

// === RGB LED ===
#define LED_RED   4
#define LED_GREEN 15
#define LED_BLUE  2

String userId = "";

void setup() {
  Serial.begin(115200);
  pinMode(LED_RED, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_BLUE, OUTPUT);
  setupCamera();
  connectToWiFi();
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);
  finger.begin(57600);
  if (!finger.verifyPassword()) {
    Serial.println(" Датчик отпечатков не найден!");
    while (1) delay(1);
  }
  Serial.println(" Датчик подключён");
}

void loop() {
  if (!client.connected()) reconnectMQTT();
  client.loop();

  int id = getFingerprintIDez();
  if (id != -1) {
    userId = String(id);
    Serial.println(" Отпечаток ID: " + userId);

    digitalWrite(LED_BLUE, HIGH);
    delay(300);
    digitalWrite(LED_BLUE, LOW);

    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println(" Ошибка фото");
      return;
    }

    size_t encodedSize = base64_encoded_size(fb->len);
    char* encoded = (char*)malloc(encodedSize);
    base64_encode(encoded, fb->buf, fb->len);

    DynamicJsonDocument doc(2048);
    doc["user_id"] = userId;
    doc["photo"] = encoded;

    char output[2048];
    serializeJson(doc, output);

    client.publish("auth/attempts", output, true);
    Serial.println("📷 Фото отправлено на проверку");

    free(encoded);
    esp_camera_fb_return(fb);
    delay(1000);
  }
  delay(100);
}

int getFingerprintIDez() {
  uint8_t p = finger.getImage();
  if (p != FINGERPRINT_OK) return -1;

  p = finger.image2Tz();
  if (p != FINGERPRINT_OK) return -1;

  p = finger.fingerFastSearch();
  if (p != FINGERPRINT_OK) return -1;

  return finger.fingerID;
}

void setupCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if(psramFound()){
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 10;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Ошибка камеры: %s\n", esp_err_to_name(err));
    return;
  }
}

void connectToWiFi() {
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n WiFi подключён, IP: " + WiFi.localIP().toString());
}

void reconnectMQTT() {
  while (!client.connected()) {
    Serial.print(" Подключение к MQTT...");
    if (client.connect("ESP32CamAuth")) {
      Serial.println("успешно");
      client.subscribe("auth/response");
    } else {
      Serial.print("ошибка: ");
      Serial.print(client.state());
      delay(5000);
    }
  }
}

void callback(char* topic, byte* payload, unsigned int length) {
  String message = "";
  for (int i = 0; i < length; i++) message += (char)payload[i];

  if (String(topic) == "auth/response") {
    if (message == "success") {
      digitalWrite(LED_GREEN, HIGH);
      delay(2000);
      digitalWrite(LED_GREEN, LOW);
    } else {
      digitalWrite(LED_RED, HIGH);
      delay(2000);
      digitalWrite(LED_RED, LOW);
    }
  }
}