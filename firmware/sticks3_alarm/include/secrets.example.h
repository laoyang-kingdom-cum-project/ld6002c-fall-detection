#pragma once

// Copy this file to secrets.h and replace the values for your local network.
constexpr char WIFI_SSID[] = "your-wifi-name";
constexpr char WIFI_PASSWORD[] = "your-wifi-password";
constexpr char SERVER_HOST[] = "192.168.1.100";
constexpr unsigned int SERVER_PORT = 8765;

// Optional sound settings. M5Unified speaker volume is 0 to 255.
// Lower these values for classroom demos in a quiet room.
// #define SPEAKER_VOLUME 60
// #define SUSPECT_TONE_HZ 1200
// #define SUSPECT_TONE_MS 140
// #define CANCEL_TONE_HZ 850
// #define CANCEL_TONE_MS 120
// #define ALARM_LOW_TONE_HZ 1350
// #define ALARM_HIGH_TONE_HZ 1900
// #define ALARM_TONE_MS 300
// #define ALARM_TONE_INTERVAL_MS 550
