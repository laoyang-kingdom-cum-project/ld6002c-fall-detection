#include <Arduino.h>
#include <ArduinoJson.h>
#include <M5Unified.h>
#include <WebSocketsClient.h>
#include <WiFi.h>

#include "secrets.h"

#ifndef SPEAKER_VOLUME
#define SPEAKER_VOLUME 80
#endif

#ifndef SUSPECT_TONE_HZ
#define SUSPECT_TONE_HZ 1200
#endif

#ifndef SUSPECT_TONE_MS
#define SUSPECT_TONE_MS 140
#endif

#ifndef CANCEL_TONE_HZ
#define CANCEL_TONE_HZ 850
#endif

#ifndef CANCEL_TONE_MS
#define CANCEL_TONE_MS 120
#endif

#ifndef ALARM_LOW_TONE_HZ
#define ALARM_LOW_TONE_HZ 1350
#endif

#ifndef ALARM_HIGH_TONE_HZ
#define ALARM_HIGH_TONE_HZ 1900
#endif

#ifndef ALARM_TONE_MS
#define ALARM_TONE_MS 300
#endif

#ifndef ALARM_TONE_INTERVAL_MS
#define ALARM_TONE_INTERVAL_MS 550
#endif

namespace {

enum class MonitorState {
  DISCONNECTED,
  NORMAL,
  OBSERVING,
  SUSPECTED_FALL,
  CONFIRMED_FALL,
  CANCELLED,
};

WebSocketsClient webSocket;
MonitorState currentState = MonitorState::DISCONNECTED;
bool serverConnected = false;
unsigned long lastWifiAttemptMs = 0;
unsigned long lastAlarmToneMs = 0;
bool alarmHighTone = false;

constexpr unsigned long WIFI_RETRY_MS = 10000;
constexpr unsigned long kAlarmToneIntervalMs = ALARM_TONE_INTERVAL_MS;

const char* stateName(MonitorState state) {
  switch (state) {
    case MonitorState::NORMAL:
      return "NORMAL";
    case MonitorState::OBSERVING:
      return "OBSERVING";
    case MonitorState::SUSPECTED_FALL:
      return "SUSPECTED_FALL";
    case MonitorState::CONFIRMED_FALL:
      return "CONFIRMED_FALL";
    case MonitorState::CANCELLED:
      return "CANCELLED";
    case MonitorState::DISCONNECTED:
    default:
      return "DISCONNECTED";
  }
}

uint16_t stateColor(MonitorState state) {
  switch (state) {
    case MonitorState::NORMAL:
      return TFT_GREEN;
    case MonitorState::OBSERVING:
      return TFT_CYAN;
    case MonitorState::SUSPECTED_FALL:
      return TFT_ORANGE;
    case MonitorState::CONFIRMED_FALL:
      return TFT_RED;
    case MonitorState::CANCELLED:
      return TFT_YELLOW;
    case MonitorState::DISCONNECTED:
    default:
      return TFT_LIGHTGREY;
  }
}

bool parseState(const char* value, MonitorState& state) {
  if (strcmp(value, "NORMAL") == 0) {
    state = MonitorState::NORMAL;
  } else if (strcmp(value, "OBSERVING") == 0) {
    state = MonitorState::OBSERVING;
  } else if (strcmp(value, "SUSPECTED_FALL") == 0) {
    state = MonitorState::SUSPECTED_FALL;
  } else if (strcmp(value, "CONFIRMED_FALL") == 0) {
    state = MonitorState::CONFIRMED_FALL;
  } else if (strcmp(value, "CANCELLED") == 0) {
    state = MonitorState::CANCELLED;
  } else if (strcmp(value, "DISCONNECTED") == 0) {
    state = MonitorState::DISCONNECTED;
  } else {
    return false;
  }
  return true;
}

void drawStatus() {
  auto& display = M5.Display;
  display.startWrite();
  display.fillScreen(TFT_BLACK);
  display.setTextColor(TFT_WHITE, TFT_BLACK);
  display.setTextSize(1);
  display.setCursor(8, 7);
  display.print("Fall Monitor");
  display.drawFastHLine(8, 20, display.width() - 16, TFT_DARKGREY);

  display.setCursor(8, 29);
  display.setTextColor(WiFi.status() == WL_CONNECTED ? TFT_GREEN : TFT_RED, TFT_BLACK);
  display.printf("Wi-Fi: %s", WiFi.status() == WL_CONNECTED ? "Connected" : "Offline");

  display.setCursor(8, 43);
  display.setTextColor(serverConnected ? TFT_GREEN : TFT_RED, TFT_BLACK);
  display.printf("Server: %s", serverConnected ? "Connected" : "Offline");

  display.setCursor(8, 64);
  display.setTextColor(TFT_WHITE, TFT_BLACK);
  display.print("Status:");
  display.setTextColor(stateColor(currentState), TFT_BLACK);

  if (currentState == MonitorState::SUSPECTED_FALL) {
    display.setTextSize(2);
    display.setCursor(8, 81);
    display.print("SUSPECTED");
    display.setCursor(8, 101);
    display.print("FALL");
  } else if (currentState == MonitorState::CONFIRMED_FALL) {
    display.setTextSize(2);
    display.setCursor(8, 81);
    display.print("CONFIRMED");
    display.setCursor(8, 101);
    display.print("FALL");
  } else {
    display.setTextSize(1);
    display.setCursor(8, 84);
    display.print(stateName(currentState));
  }
  display.endWrite();
}

void applyState(MonitorState nextState) {
  if (nextState == currentState) {
    return;
  }

  MonitorState previousState = currentState;
  currentState = nextState;
  if (previousState == MonitorState::CONFIRMED_FALL &&
      nextState != MonitorState::CONFIRMED_FALL) {
    M5.Speaker.stop();
  }
  if (nextState == MonitorState::SUSPECTED_FALL) {
    M5.Speaker.tone(SUSPECT_TONE_HZ, SUSPECT_TONE_MS);
  } else if (nextState == MonitorState::CANCELLED) {
    M5.Speaker.stop();
    M5.Speaker.tone(CANCEL_TONE_HZ, CANCEL_TONE_MS);
  }
  drawStatus();
}

void handleStateMessage(const uint8_t* payload, size_t length) {
  JsonDocument document;
  DeserializationError error = deserializeJson(document, payload, length);
  if (error || strcmp(document["type"] | "", "state") != 0) {
    Serial.printf("Invalid state message: %s\n", error ? error.c_str() : "wrong type");
    return;
  }

  MonitorState nextState;
  if (!parseState(document["state"] | "", nextState)) {
    Serial.println("Unknown monitor state");
    return;
  }
  applyState(nextState);
}

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      serverConnected = true;
      Serial.printf("WebSocket connected: %s\n", payload);
      drawStatus();
      break;
    case WStype_DISCONNECTED:
      serverConnected = false;
      M5.Speaker.stop();
      currentState = MonitorState::DISCONNECTED;
      Serial.println("WebSocket disconnected");
      drawStatus();
      break;
    case WStype_TEXT:
      handleStateMessage(payload, length);
      break;
    default:
      break;
  }
}

void connectWifi() {
  lastWifiAttemptMs = millis();
  Serial.printf("Connecting to Wi-Fi: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  drawStatus();
}

void updateWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }
  serverConnected = false;
  if (currentState != MonitorState::DISCONNECTED) {
    applyState(MonitorState::DISCONNECTED);
  }
  if (millis() - lastWifiAttemptMs >= WIFI_RETRY_MS) {
    WiFi.disconnect();
    connectWifi();
  }
}

void updateAlarmTone() {
  if (currentState != MonitorState::CONFIRMED_FALL) {
    return;
  }
  if (millis() - lastAlarmToneMs < kAlarmToneIntervalMs) {
    return;
  }
  lastAlarmToneMs = millis();
  alarmHighTone = !alarmHighTone;
  M5.Speaker.tone(alarmHighTone ? ALARM_HIGH_TONE_HZ : ALARM_LOW_TONE_HZ,
                  ALARM_TONE_MS);
}

void cancelAlarmFromButton() {
  if (currentState != MonitorState::CONFIRMED_FALL) {
    return;
  }
  applyState(MonitorState::CANCELLED);
  if (serverConnected) {
    webSocket.sendTXT("{\"type\":\"event\",\"event\":\"ALARM_CANCELLED\"}");
  }
  Serial.println("Alarm cancelled by Button A");
}

}  // namespace

void setup() {
  auto config = M5.config();
  config.internal_spk = true;
  config.clear_display = true;
  M5.begin(config);
  M5.Display.setRotation(1);
  M5.Display.setBrightness(100);
  M5.Speaker.setVolume(SPEAKER_VOLUME);
  Serial.begin(115200);

  drawStatus();
  connectWifi();

  webSocket.begin(SERVER_HOST, SERVER_PORT, "/");
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
  webSocket.enableHeartbeat(15000, 3000, 2);
}

void loop() {
  M5.update();
  updateWifi();
  if (WiFi.status() == WL_CONNECTED) {
    webSocket.loop();
  }
  if (M5.BtnA.wasClicked()) {
    cancelAlarmFromButton();
  }
  updateAlarmTone();
  delay(5);
}
