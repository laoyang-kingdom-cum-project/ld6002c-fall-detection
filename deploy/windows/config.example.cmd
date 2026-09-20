@rem Copy this file to config.cmd and edit only the values you need.
@rem config.cmd is ignored by Git and is loaded by all three root BAT files.

@rem Optional fixed radar port. Leave empty to auto-detect CP210x/CP2104.
set "LD6002C_PORT="

@rem Local Ollama settings.
set "OLLAMA_BASE_URL=http://127.0.0.1:11434"
set "OLLAMA_MODEL=qwen3:0.6b"

@rem Optional runtime overrides.
set "LD6002C_BAUDRATE=115200"
set "LD6002C_DASHBOARD_PORT=8501"
set "ALARM_VOLUME=100"
