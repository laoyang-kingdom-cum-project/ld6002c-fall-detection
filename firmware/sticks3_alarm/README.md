# StickS3 Alarm Client

This PlatformIO project turns M5Stack StickS3 into a display, audible alarm,
and cancellation button for the Python fall-detection service. The fall
decision remains entirely in Python.

## Configure

```bash
cd firmware/sticks3_alarm
cp include/secrets.example.h include/secrets.h
```

Edit `include/secrets.h` with the 2.4 GHz Wi-Fi credentials and the LAN IP of
the computer running `ld6002c-fall`. Do not use `0.0.0.0` as `SERVER_HOST`.

Optional sound settings can also be added to `include/secrets.h`. M5Unified
speaker volume uses `0` to `255`:

```cpp
// Quiet classroom demo
#define SPEAKER_VOLUME 45
#define ALARM_LOW_TONE_HZ 900
#define ALARM_HIGH_TONE_HZ 1200
#define ALARM_TONE_MS 220
#define ALARM_TONE_INTERVAL_MS 700
```

```cpp
// More obvious alarm
#define SPEAKER_VOLUME 120
#define ALARM_LOW_TONE_HZ 1500
#define ALARM_HIGH_TONE_HZ 2300
#define ALARM_TONE_MS 320
#define ALARM_TONE_INTERVAL_MS 480
```

## Build and upload

```bash
pio run
pio run --target upload --upload-port /dev/ttyACM0
pio device monitor --port /dev/ttyACM0 --baud 115200
```

The upload command replaces the factory UiFlow2 firmware. Button A cancels an
active `CONFIRMED_FALL` alarm locally and sends `ALARM_CANCELLED` to Python.
