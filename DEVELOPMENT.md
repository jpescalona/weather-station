# Guía de desarrollo

## Dependencias

### Sistema (Raspberry Pi OS Bookworm)

```bash
sudo apt-get install -y \
    rtl-sdr \       # rtl_fm, rtl_test, rtl_power
    sox \           # conversión y remuestreo de audio
    python3-pip \
    python3-dev \
    python3-venv \
    libusb-1.0-0-dev
```

**noaa-apt 1.4.1** — no hay `.deb` para ARM; se instala desde el binario del release:

```bash
make install-noaa-apt
```

Esto descarga el `.zip` correspondiente a la arquitectura (`aarch64`, `armv7l`, o `x86_64`), extrae el binario y lo copia a `/usr/local/bin/noaa-apt`.

### Python

| Paquete       | Versión  | Uso                                      |
|---------------|----------|------------------------------------------|
| `ephem`       | ≥ 4.1.5  | Predicción de pasos de satélite          |
| `pyyaml`      | ≥ 6.0.1  | Carga de `config.yaml`                   |
| `requests`    | ≥ 2.31.0 | Envío de imágenes por Telegram Bot API   |
| `pytest`      | ≥ 8.0.0  | Ejecución de tests (dev)                 |
| `pytest-cov`  | ≥ 5.0.0  | Cobertura de tests (dev)                 |
| `pytest-mock` | ≥ 3.12.0 | Mocks en tests (dev)                     |

Todas las dependencias están declaradas en `pyproject.toml` y bloqueadas en `poetry.lock`.

## Configurar el entorno local

```bash
# Crear virtualenv e instalar dependencias (equivale a make install-python)
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet poetry
.venv/bin/poetry config virtualenvs.create false
.venv/bin/poetry install --no-root
```

> `virtualenvs.create false` hace que Poetry instale los paquetes dentro del `.venv` del proyecto en lugar de crear uno propio en `~/.cache/pypoetry`.

Activar el entorno para trabajar en la shell:

```bash
source .venv/bin/activate
```

## Ejecutar los tests

```bash
make test
# equivalente a:
.venv/bin/pytest
```

La configuración en `pyproject.toml` ejecuta automáticamente cobertura:

```
tests/
├── test_config.py       # carga y validación de config.yaml
├── test_tle_manager.py  # descarga y parseo de TLEs
├── test_predictor.py    # predicción de pasos con ephem
├── test_receiver.py     # pipeline rtl_fm + sox
├── test_decoder.py      # llamadas a noaa-apt
├── test_sender.py       # Telegram Bot API
├── test_cleaner.py      # limpieza de ficheros
└── test_main.py         # bucle principal y _paused_services
```

Para ejecutar solo un módulo o test:

```bash
.venv/bin/pytest tests/test_receiver.py -v
.venv/bin/pytest tests/test_predictor.py::TestPredictor::test_returns_pass_above_min_elevation -v
```

Para ver la cobertura en HTML:

```bash
.venv/bin/pytest --cov-report=html
open htmlcov/index.html
```

## Arquitectura de módulos

```
config.py          lee config.yaml + variables de entorno
     │
     ├── tle_manager.py   descarga TLEs de CelesTrak (CATNR={norad_id})
     │                    cachea en disco; refresca si > max_age_hours
     │
     ├── predictor.py     usa ephem.Observer + ephem.readtle()
     │                    devuelve SatellitePass(aos, los, max_elevation, ...)
     │
     ├── receiver.py      lanza rtl_fm | sox con Popen
     │                    produce un fichero WAV
     │
     ├── decoder.py       llama a noaa-apt como subproceso
     │                    produce imagen B&W y/o térmica (PNG)
     │
     ├── sender.py        ImageSender (abstracta)
     │                    └── TelegramSender  (sendPhoto + sendMessage)
     │
     ├── cleaner.py       elimina WAV y/o PNG según config
     │
     ├── cli.py           comandos --check, --passes, --duration, --scan
     │
     └── main.py          bucle demonio; _paused_services() context manager
```

### Nota sobre `_paused_services`

`main._paused_services(services)` es un context manager que para los servicios systemd indicados en `competing_services` antes de usar el RTL-SDR y los vuelve a arrancar al terminar. Requiere que el usuario `pi` pueda ejecutar `sudo systemctl stop/start <servicio>` sin contraseña (ver `make setup-sudoers`).

## Añadir un satélite nuevo

1. Busca su NORAD ID en [CelesTrak](https://celestrak.org) o [n2yo.com](https://www.n2yo.com).
2. Añade una entrada en `config.yaml`:

```yaml
satellites:
  NOAA 18:
    frequency: 137912500
    norad_id: 28654
```

3. No se necesita ningún cambio en el código; el sistema descarga el TLE y predice pasos automáticamente.

## Variables de entorno

| Variable             | Descripción                          |
|----------------------|--------------------------------------|
| `TELEGRAM_BOT_TOKEN` | Token del bot (sobrescribe config.yaml) |
| `TELEGRAM_CHAT_ID`   | ID del chat destino                  |

Se pueden definir en `.env` (ver `.env.example`) o exportar directamente. Las variables de entorno tienen prioridad sobre los valores en `config.yaml`.

## Makefile — targets disponibles

| Target              | Descripción                                              |
|---------------------|----------------------------------------------------------|
| `make install`      | Instala dependencias de sistema + noaa-apt + Python      |
| `make install-system` | Solo dependencias apt                                  |
| `make install-noaa-apt` | Solo noaa-apt (detecta arquitectura automáticamente) |
| `make install-python` | Solo virtualenv + Poetry + dependencias Python         |
| `make install-service` | Instala y arranca el servicio systemd                 |
| `make uninstall-service` | Para y elimina el servicio systemd                  |
| `make setup-sudoers` | Añade regla sudoers para pausar dump1090-fa             |
| `make test`         | Ejecuta la suite de tests con cobertura                  |
| `make clean`        | Elimina `__pycache__`, `.pyc`, `.pytest_cache`, `.coverage` |

## Logs

El demonio escribe en `logs/weather-station.log` (configurable en `config.yaml`) y también en el journal de systemd:

```bash
journalctl -u weather-station -f          # en tiempo real
journalctl -u weather-station --since today
```

El formato de log es:

```
2026-05-10 14:23:05 [INFO] weather_station.main: Next: NOAA 19 at 2026-05-10 14:23 UTC (in 0 min, max el 67.3°)
2026-05-10 14:23:05 [INFO] weather_station.main: Stopped competing service: dump1090-fa
2026-05-10 14:36:50 [INFO] weather_station.main: Restarted service: dump1090-fa
```
