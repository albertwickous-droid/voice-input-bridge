/*
 * M5StickS3 / M5Unified -> Voice Input Bridge WebSocket example.
 *
 * Requirements:
 *   - M5Unified board support for M5StickS3
 *   - "WebSockets" by Markus Sattler (arduinoWebSockets)
 *
 * Change Wi-Fi, bridge host, and token placeholders. Never commit credentials.
 * Hold button A to speak; release it to finalize. This example is intentionally
 * small and board-specific; examples/esp32/arduino_ws_mic is the generic version.
 */

#include <M5Unified.h>
#include <WiFi.h>
#include <WebSocketsClient.h>

static const char *WIFI_SSID = "YOUR_2_4GHZ_SSID";
static const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
static const char *BRIDGE_HOST = "YOUR_BRIDGE_IP";
static const uint16_t BRIDGE_PORT = 18766;
static const char *BRIDGE_PATH = "/v1/audio";
static const char *BRIDGE_TOKEN = "";

static const uint32_t SAMPLE_RATE = 16000;
static const size_t SAMPLES_PER_CHUNK = 320;  // 20 ms
static const size_t PCM_CHUNK_BYTES = SAMPLES_PER_CHUNK * sizeof(int16_t);

WebSocketsClient webSocket;
int16_t microphone[SAMPLES_PER_CHUNK];
uint8_t packet[8 + PCM_CHUNK_BYTES];
bool ready = false;
bool recording = false;
uint16_t sequenceNumber = 0;

static void sendJson(String json) { webSocket.sendTXT(json); }

static void sendHello() {
  String hello = "{\"type\":\"hello\",\"token\":\"";
  hello += BRIDGE_TOKEN;
  hello += "\"}";
  sendJson(hello);
}

static void sendStart() {
  sendJson("{\"type\":\"start\",\"sampleRate\":16000,\"channels\":1,"
           "\"bitsPerSample\":16,\"encoding\":\"pcm_s16le\",\"language\":\"zh-CN\"}");
}

static void sendAudio(const int16_t *samples, size_t count) {
  const size_t bytes = count * sizeof(int16_t);
  memcpy(packet, "AUD1", 4);
  packet[4] = static_cast<uint8_t>(bytes & 0xff);
  packet[5] = static_cast<uint8_t>((bytes >> 8) & 0xff);
  packet[6] = static_cast<uint8_t>(sequenceNumber & 0xff);
  packet[7] = static_cast<uint8_t>((sequenceNumber >> 8) & 0xff);
  memcpy(packet + 8, samples, bytes);
  webSocket.sendBIN(packet, 8 + bytes);
  sequenceNumber++;
}

static void onWebSocketEvent(WStype_t type, uint8_t *payload, size_t length) {
  if (type == WStype_CONNECTED) {
    ready = false;
    sendHello();
    M5.Display.setCursor(0, 0);
    M5.Display.println("Authenticating");
  } else if (type == WStype_DISCONNECTED) {
    ready = false;
    recording = false;
    M5.Display.println("Disconnected");
  } else if (type == WStype_TEXT) {
    String message;
    for (size_t i = 0; i < length; ++i) message += static_cast<char>(payload[i]);
    Serial.println(message);
    if (message.indexOf("\"type\":\"hello_ack\"") >= 0) {
      ready = true;
      M5.Display.fillScreen(TFT_BLACK);
      M5.Display.setCursor(0, 0);
      M5.Display.println("Hold A to talk");
    } else if (message.indexOf("\"type\":\"partial\"") >= 0) {
      M5.Display.setCursor(0, 32);
      M5.Display.println("Listening...");
    } else if (message.indexOf("\"type\":\"final\"") >= 0) {
      M5.Display.setCursor(0, 32);
      M5.Display.println("Committed");
    }
  }
}

void setup() {
  auto config = M5.config();
  M5.begin(config);
  M5.Display.setTextSize(2);
  M5.Mic.begin();
  Serial.begin(115200);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  M5.Display.println("Connecting Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }
  M5.Display.fillScreen(TFT_BLACK);
  webSocket.begin(BRIDGE_HOST, BRIDGE_PORT, BRIDGE_PATH);
  webSocket.onEvent(onWebSocketEvent);
  webSocket.setReconnectInterval(3000);
  webSocket.enableHeartbeat(15000, 3000, 2);
}

void loop() {
  M5.update();
  webSocket.loop();

  if (M5.BtnA.wasPressed() && ready && !recording) {
    sequenceNumber = 0;
    recording = true;
    sendStart();
    M5.Display.fillScreen(TFT_BLACK);
    M5.Display.setCursor(0, 0);
    M5.Display.println("Recording...");
  }
  if (M5.BtnA.wasReleased() && recording) {
    recording = false;
    sendJson("{\"type\":\"stop\"}");
  }

  if (recording && M5.Mic.record(microphone, SAMPLES_PER_CHUNK, SAMPLE_RATE)) {
    sendAudio(microphone, SAMPLES_PER_CHUNK);
  }
}
