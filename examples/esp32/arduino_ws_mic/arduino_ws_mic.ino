/*
 * Generic ESP32-S3 + I2S microphone -> Voice Input Bridge WebSocket example.
 *
 * Install: WebSockets by Markus Sattler (arduinoWebSockets).
 * Board: any ESP32 with an I2S digital microphone. Change the three I2S pins,
 * Wi-Fi, host, and token placeholders below. Never commit real credentials.
 *
 * Press-and-hold the button to speak. Release it to commit the ASR final.
 */

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <driver/i2s_std.h>

// ---------------- User configuration ----------------
static const char *WIFI_SSID = "YOUR_2_4GHZ_SSID";
static const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
static const char *BRIDGE_HOST = "YOUR_BRIDGE_IP";
static const uint16_t BRIDGE_PORT = 18766;
static const char *BRIDGE_PATH = "/v1/audio";
static const char *BRIDGE_TOKEN = "";  // Prefer a build-time secret, do not commit one.

static const int I2S_BCLK_PIN = 5;
static const int I2S_WS_PIN = 6;
static const int I2S_DIN_PIN = 7;
static const int PTT_BUTTON_PIN = 0;  // Active LOW, INPUT_PULLUP.
// ----------------------------------------------------

static const uint32_t SAMPLE_RATE = 16000;
static const size_t PCM_CHUNK_BYTES = 640;  // 20 ms, mono, s16le
static const size_t FRAME_HEADER_BYTES = 8;

WebSocketsClient webSocket;
i2s_chan_handle_t rxChannel = nullptr;
bool bridgeReady = false;
bool recording = false;
uint16_t sequenceNumber = 0;
uint8_t pcmBuffer[PCM_CHUNK_BYTES];
uint8_t packetBuffer[FRAME_HEADER_BYTES + PCM_CHUNK_BYTES];

static void sendJson(String json) {
  webSocket.sendTXT(json);
  Serial.println(json);
}

static void sendHello() {
  String message = "{\"type\":\"hello\",\"token\":\"";
  message += BRIDGE_TOKEN;
  message += "\"}";
  sendJson(message);
}

static void sendStart() {
  sendJson("{\"type\":\"start\",\"sampleRate\":16000,\"channels\":1,"
           "\"bitsPerSample\":16,\"encoding\":\"pcm_s16le\",\"language\":\"zh-CN\"}");
}

static void sendAudio(const uint8_t *data, size_t length) {
  if (length > PCM_CHUNK_BYTES) return;
  memcpy(packetBuffer, "AUD1", 4);
  packetBuffer[4] = static_cast<uint8_t>(length & 0xff);
  packetBuffer[5] = static_cast<uint8_t>((length >> 8) & 0xff);
  packetBuffer[6] = static_cast<uint8_t>(sequenceNumber & 0xff);
  packetBuffer[7] = static_cast<uint8_t>((sequenceNumber >> 8) & 0xff);
  memcpy(packetBuffer + FRAME_HEADER_BYTES, data, length);
  webSocket.sendBIN(packetBuffer, FRAME_HEADER_BYTES + length);
  sequenceNumber++;
}

static bool initMicrophone() {
  i2s_chan_config_t channelConfig = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  if (i2s_new_channel(&channelConfig, nullptr, &rxChannel) != ESP_OK) return false;

  i2s_std_config_t standardConfig = {
      .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
      .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
          I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
      .gpio_cfg = {
          .mclk = I2S_GPIO_UNUSED,
          .bclk = static_cast<gpio_num_t>(I2S_BCLK_PIN),
          .ws = static_cast<gpio_num_t>(I2S_WS_PIN),
          .dout = I2S_GPIO_UNUSED,
          .din = static_cast<gpio_num_t>(I2S_DIN_PIN),
          .invert_flags = {
              .mclk_inv = false,
              .bclk_inv = false,
              .ws_inv = false,
          },
      },
  };
  standardConfig.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;
  if (i2s_channel_init_std_mode(rxChannel, &standardConfig) != ESP_OK) return false;
  return i2s_channel_enable(rxChannel) == ESP_OK;
}

static void handleServerMessage(const String &payload) {
  if (payload.indexOf("\"type\":\"hello_ack\"") >= 0) {
    bridgeReady = true;
    Serial.println("Bridge authenticated");
  } else if (payload.indexOf("\"type\":\"listening\"") >= 0) {
    Serial.println("ASR listening");
  } else if (payload.indexOf("\"type\":\"final\"") >= 0 ||
             payload.indexOf("\"type\":\"partial\"") >= 0 ||
             payload.indexOf("\"type\":\"error\"") >= 0 ||
             payload.indexOf("\"type\":\"session_end\"") >= 0) {
    Serial.println(payload);
  }
}

static void webSocketEvent(WStype_t type, uint8_t *payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      bridgeReady = false;
      Serial.println("WebSocket connected");
      sendHello();
      break;
    case WStype_DISCONNECTED:
      bridgeReady = false;
      recording = false;
      Serial.println("WebSocket disconnected");
      break;
    case WStype_TEXT: {
      String message;
      message.reserve(length);
      for (size_t i = 0; i < length; ++i) message += static_cast<char>(payload[i]);
      handleServerMessage(message);
      break;
    }
    case WStype_ERROR:
      Serial.println("WebSocket error");
      break;
    default:
      break;
  }
}

static void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print('.');
  }
  Serial.print("\nLocal IP: ");
  Serial.println(WiFi.localIP());
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(PTT_BUTTON_PIN, INPUT_PULLUP);
  if (!initMicrophone()) {
    Serial.println("I2S microphone initialization failed");
    while (true) delay(1000);
  }
  connectWiFi();
  webSocket.begin(BRIDGE_HOST, BRIDGE_PORT, BRIDGE_PATH);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(3000);
  webSocket.enableHeartbeat(15000, 3000, 2);
}

void loop() {
  webSocket.loop();
  const bool pressed = digitalRead(PTT_BUTTON_PIN) == LOW;

  if (pressed && bridgeReady && !recording) {
    sequenceNumber = 0;
    recording = true;
    sendStart();
    Serial.println("Recording...");
  }
  if (!pressed && recording) {
    recording = false;
    sendJson("{\"type\":\"stop\"}");
    Serial.println("Stopped");
  }

  if (recording) {
    size_t bytesRead = 0;
    esp_err_t result = i2s_channel_read(
        rxChannel, pcmBuffer, sizeof(pcmBuffer), &bytesRead, pdMS_TO_TICKS(100));
    if (result == ESP_OK && bytesRead > 0) {
      sendAudio(pcmBuffer, bytesRead);
    }
  }
}
