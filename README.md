# NOAA Weather Satellite Ground Station

Estación terrena automatizada para recibir imágenes APT de los satélites meteorológicos NOAA 15, 18 y 19 usando una Raspberry Pi y un dongle RTL-SDR V3.

El sistema predice los próximos pasos de cada satélite, graba la señal de radio, decodifica las imágenes en blanco y negro y en falso color térmico, y las envía por Telegram.

```
NOAA 15/18/19
      │  señal APT 137 MHz
      ▼
  RTL-SDR V3
      │  rtl_fm (60 kHz) → sox (11025 Hz WAV)
      ▼
  noaa-apt
      │  imagen B&W + térmica (PNG)
      ▼
  Telegram Bot
```

## Requisitos de hardware

- Raspberry Pi (cualquier modelo con USB; probado en Pi 4 y Pi Zero 2W)
- Dongle RTL-SDR V3 (Realtek RTL2838 / USB `0bda:2838`)
- Antena para 137 MHz (dipolo en V, QFH, o Turnstile)

## Instalación

```bash
git clone https://github.com/tu-usuario/weather-station.git
cd weather-station
make install          # instala dependencias de sistema, noaa-apt y entorno Python
make install-service  # instala y arranca el servicio systemd
```

Si tienes **dump1090-fa** u otro servicio que compita por el RTL-SDR, permite que el sistema lo pause automáticamente:

```bash
make setup-sudoers    # añade regla sudoers sin contraseña para systemctl stop/start dump1090-fa
```

## Configuración

### `config.yaml`

El fichero principal está en la raíz del proyecto. Los valores más relevantes:

```yaml
location:
  latitude: 36.5396553   # tu latitud (N positivo)
  longitude: -4.6267627  # tu longitud (O negativo)
  altitude: 78           # metros sobre el nivel del mar

capture:
  gain: 44.5             # ganancia RTL-SDR en dB
  ppm: 0                 # corrección de frecuencia (0 para RTL-SDR V3)
  min_elevation: 20      # ignora pasos por debajo de este ángulo (°)

capture:
  competing_services:
    - dump1090-fa        # servicios a pausar durante la captura
```

### Telegram

Crea un bot con [@BotFather](https://t.me/BotFather), envíale `/start` al bot desde tu cuenta, y configura las credenciales:

```bash
cp .env.example .env
# edita .env:
TELEGRAM_BOT_TOKEN=123456:ABC-...
TELEGRAM_CHAT_ID=tu_chat_id
```

Para obtener tu `chat_id`, puedes usar el script de diagnóstico:

```bash
.venv/bin/python scripts/test_telegram.py          # verifica conexión
.venv/bin/python scripts/test_telegram.py --send   # envía mensaje de prueba
```

## Uso

### Modo demonio (automático)

```bash
python weather-station.py   # ejecuta en primer plano (bucle continuo)
```

O como servicio systemd (se inicia con el sistema):

```bash
sudo systemctl start weather-station
sudo systemctl status weather-station
journalctl -u weather-station -f   # ver logs en tiempo real
```

### Comandos de diagnóstico

**Verificar hardware y herramientas:**
```bash
python weather-station.py --check
```
```
=== [1] Dispositivo RTL-SDR ===
  [OK]  Bus 001 Device 003: ID 0bda:2838 Realtek Semiconductor Corp.
=== [2] Herramientas requeridas ===
  [OK]  rtl_fm         /usr/bin/rtl_fm
  [OK]  sox            /usr/bin/sox
  [OK]  noaa-apt       /usr/local/bin/noaa-apt
...
```

**Ver próximas pasadas:**
```bash
python weather-station.py --passes
```
```
Satelite      AOS (UTC)            LOS (UTC)             Duracion   Max Elev  Espera
------------------------------------------------------------------------------------
NOAA 19       2026-05-10 14:23:11  2026-05-10 14:36:48       13m37s      67.3°  en 0h42m
NOAA 15       2026-05-10 15:01:55  2026-05-10 15:14:20       12m25s      45.1°  en 1h21m
```

**Grabación manual:**
```bash
python weather-station.py --duration 600                       # graba NOAA 19 durante 10 min
python weather-station.py --duration 900 --satellite "NOAA 15" # graba NOAA 15 durante 15 min
```

**Escanear señales en 137 MHz:**
```bash
python weather-station.py --scan
```
```
Satelite      Frecuencia       Nivel  Estado
----------------------------------------------------
NOAA 15      137.6200 MHz   -72.3 dBm  sin senal
NOAA 18      137.9125 MHz   -71.8 dBm  sin senal
NOAA 19      137.1000 MHz   -71.5 dBm  sin senal
```
> La señal solo es visible mientras el satélite está sobre el horizonte.

## Estructura de ficheros

```
weather-station/
├── weather-station.py          # punto de entrada (CLI)
├── config.yaml                 # configuración principal
├── .env                        # credenciales Telegram (no en git)
├── weather_station/
│   ├── config.py               # carga y valida config.yaml
│   ├── tle_manager.py          # descarga y cachea TLEs de CelesTrak
│   ├── predictor.py            # predice pasos con ephem
│   ├── receiver.py             # captura con rtl_fm + sox
│   ├── decoder.py              # decodifica APT con noaa-apt
│   ├── sender.py               # envío por Telegram
│   ├── cleaner.py              # limpieza de ficheros temporales
│   ├── cli.py                  # comandos --check, --passes, --duration, --scan
│   └── main.py                 # bucle demonio + _paused_services
├── systemd/
│   ├── weather-station.service
│   └── weather-station.timer
├── scripts/
│   └── test_telegram.py        # diagnóstico de Telegram
├── tests/
└── Makefile
```

## Satélites soportados

| Satélite | Frecuencia  | NORAD ID |
|----------|-------------|----------|
| NOAA 15  | 137.620 MHz | 25338    |
| NOAA 18  | 137.9125 MHz| 28654    |
| NOAA 19  | 137.100 MHz | 33591    |

Los TLEs se actualizan automáticamente desde [CelesTrak](https://celestrak.org) cada 24 horas.
