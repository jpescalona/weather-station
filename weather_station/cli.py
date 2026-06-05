"""CLI commands: --check, --passes, --duration, --scan."""
import csv
import grp
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

from weather_station.config import Config
from weather_station.predictor import Predictor, SatellitePass
from weather_station.tle_manager import TLEManager


# ─── helpers ──────────────────────────────────────────────────────────────────

def _ok(msg: str) -> None:
    print(f"  [OK]  {msg}")

def _err(msg: str) -> None:
    print(f"  [!!]  {msg}")

def _info(msg: str) -> None:
    print(f"  [ ]   {msg}")

def _build_predictor(config: Config) -> Predictor:
    return Predictor(
        latitude=config.location.latitude,
        longitude=config.location.longitude,
        altitude=config.location.altitude,
        min_elevation=config.capture.min_elevation,
    )

def _build_tle_manager(config: Config) -> TLEManager:
    return TLEManager(
        tle_file=config.tle.file,
        satellites={n: s.norad_id for n, s in config.satellites.items()},
        max_age_hours=config.tle.max_age_hours,
    )


# ─── --check ──────────────────────────────────────────────────────────────────

def cmd_check() -> bool:
    all_ok = True

    print("=== [1] Dispositivo RTL-SDR ===")
    try:
        out = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5).stdout
        rtl_lines = [l for l in out.splitlines()
                     if any(v in l for v in ("0bda:2838", "0bda:2832", "0bda:2837", "Realtek"))]
        if rtl_lines:
            for l in rtl_lines:
                _ok(l.strip())
        else:
            _err("RTL-SDR no detectado por lsusb (¿desconectado?)")
            all_ok = False
    except FileNotFoundError:
        _info("lsusb no disponible en este sistema")

    print("\n=== [2] Herramientas requeridas ===")
    required = {"rtl_fm": "rtl-sdr", "sox": "sox", "noaa-apt": "make install-noaa-apt"}
    optional = {"rtl_test": "rtl-sdr", "rtl_power": "rtl-sdr"}
    for tool, pkg in {**required, **optional}.items():
        path = shutil.which(tool)
        tag = "(opcional)" if tool in optional else ""
        if path:
            _ok(f"{tool:<14} {path}")
        elif tool in required:
            _err(f"{tool:<14} no encontrado  ->  instalar: {pkg}")
            all_ok = False
        else:
            _info(f"{tool:<14} no encontrado {tag}  ->  {pkg}")

    print("\n=== [3] Permisos ===")
    try:
        user_groups = [g.gr_name for g in grp.getgrall() if "pi" in g.gr_mem]
        if "plugdev" in user_groups:
            _ok("Usuario 'pi' en grupo plugdev")
        else:
            _err("Usuario 'pi' NO esta en grupo plugdev")
            _info("Ejecuta: sudo usermod -a -G plugdev pi  (y vuelve a iniciar sesion)")
            all_ok = False
    except Exception as e:
        _info(f"No se pudo comprobar grupos: {e}")

    print("\n=== [4] Acceso al dispositivo (rtl_test) ===")
    if shutil.which("rtl_test"):
        try:
            r = subprocess.run(["rtl_test", "-t"], capture_output=True, text=True, timeout=8)
            output = (r.stderr + r.stdout)
            if "No supported devices found" in output:
                _err("Dispositivo no accesible — posiblemente en uso por otro proceso")
                all_ok = False
            else:
                for line in output.splitlines():
                    if any(k in line for k in ("Found", "Using", "Tuner")):
                        _ok(line.strip())
        except subprocess.TimeoutExpired:
            _err("rtl_test tardo demasiado (dispositivo bloqueado?)")
            all_ok = False
    else:
        _info("rtl_test no instalado, prueba omitida")

    print()
    if all_ok:
        print("Sistema listo para recibir satelites.")
    else:
        print("Se encontraron problemas. Revisa los puntos marcados con [!!].")
    return all_ok


# ─── --passes ─────────────────────────────────────────────────────────────────

def cmd_passes(config: Config, per_satellite: int = 3) -> None:
    tle_manager = _build_tle_manager(config)
    predictor = _build_predictor(config)

    print("Actualizando TLE...", end=" ", flush=True)
    if not tle_manager.update_if_needed():
        print("ERROR")
        return
    print("OK\n")

    print(
        f"Proximas pasadas desde "
        f"({config.location.latitude:.4f} N, {abs(config.location.longitude):.4f} O)  "
        f"-- elevacion minima {config.capture.min_elevation}°\n"
    )
    col = "{:<12}  {:<19}  {:<19}  {:>8}  {:>9}  {}"
    print(col.format("Satelite", "AOS (UTC)", "LOS (UTC)", "Duracion", "Max Elev", "Espera"))
    print("-" * 84)

    all_passes: list[SatellitePass] = []
    for name, sat_cfg in config.satellites.items():
        tle = tle_manager.get_tle(name)
        if not tle:
            print(f"  [!!] TLE no disponible para {name}")
            continue
        after = None
        for _ in range(per_satellite):
            p = predictor.get_next_pass(name, tle[0], tle[1], sat_cfg.frequency, after=after)
            if not p:
                break
            all_passes.append(p)
            after = p.los + timedelta(minutes=1)

    all_passes.sort(key=lambda p: p.aos)
    now = datetime.now(timezone.utc)
    for p in all_passes:
        wait_s = (p.aos - now).total_seconds()
        wait_str = (f"en {int(wait_s//3600)}h{int((wait_s%3600)//60)}m"
                    if wait_s > 0 else "EN CURSO")
        dur = f"{int(p.duration_seconds//60)}m{int(p.duration_seconds%60):02d}s"
        print(col.format(
            p.satellite,
            p.aos.strftime("%Y-%m-%d %H:%M:%S"),
            p.los.strftime("%Y-%m-%d %H:%M:%S"),
            dur,
            f"{p.max_elevation:.1f}°",
            wait_str,
        ))


# ─── --duration ───────────────────────────────────────────────────────────────

def cmd_receive(config: Config, satellite_name: str, duration_seconds: int) -> bool:
    # Normalize name: "noaa19" / "NOAA-19" / "NOAA 19" all accepted
    normalized = satellite_name.upper().replace("-", " ").replace("_", " ")
    sat_cfg = next(
        (v for k, v in config.satellites.items() if k.upper() == normalized),
        None,
    )
    if sat_cfg is None:
        known = ", ".join(config.satellites.keys())
        print(f"Satelite '{satellite_name}' no reconocido. Disponibles: {known}")
        return False

    from weather_station.cleaner import Cleaner
    from weather_station.decoder import Decoder
    from weather_station.main import _paused_services
    from weather_station.receiver import Receiver
    from weather_station.sender import TelegramSender

    receiver = Receiver(
        recordings_dir=config.paths.recordings_dir,
        gain=config.capture.gain,
        rtl_sample_rate=config.capture.rtl_sample_rate,
        final_sample_rate=config.capture.final_sample_rate,
        ppm=config.capture.ppm,
        device_index=config.capture.device_index,
    )
    decoder = Decoder()
    cleaner = Cleaner(delete_wav=config.cleanup.delete_wav, delete_png=config.cleanup.delete_png)
    sender = (TelegramSender(config.telegram.bot_token, config.telegram.chat_id)
              if config.telegram.bot_token and config.telegram.chat_id else None)

    print(f"Grabando {normalized} a {sat_cfg.frequency/1e6:.4f} MHz durante {duration_seconds}s...")
    with _paused_services(config.capture.competing_services):
        wav_file = receiver.record(
            frequency=sat_cfg.frequency,
            duration_seconds=float(duration_seconds),
            satellite_name=normalized,
        )

    if not wav_file:
        print("Grabacion fallida.")
        return False

    print(f"Grabacion completada: {wav_file.name} ({wav_file.stat().st_size/1e6:.1f} MB)")
    print("Decodificando...")
    bw, thermal = decoder.decode(wav_file)
    images = [i for i in (bw, thermal) if i]

    if not images:
        print("Decodificacion fallida.")
        cleaner.cleanup([wav_file])
        return False

    for img in images:
        print(f"  Imagen: {img}")

    if sender:
        print("Enviando por Telegram...")
        ok = sender.send(images, normalized, datetime.now(timezone.utc))
        if ok:
            cleaner.cleanup([wav_file] + images)
            print("Enviado y archivos temporales eliminados.")
        else:
            print("Error al enviar. Archivos conservados.")
    else:
        print("Telegram no configurado — imagenes guardadas en:", wav_file.parent)

    return True


# ─── --scan ───────────────────────────────────────────────────────────────────

def _parse_rtl_power_csv(csv_text: str, target_hz: int, step_hz: int = 5000) -> float | None:
    """Return the peak power (dBm) within ±step_hz of target_hz."""
    best: float | None = None
    for row in csv.reader(StringIO(csv_text)):
        if len(row) < 7:
            continue
        try:
            hz_low = int(row[2])
            hz_step = float(row[4])
            db_vals = [float(v) for v in row[6:] if v.strip()]
            for i, db in enumerate(db_vals):
                freq = hz_low + i * hz_step
                if abs(freq - target_hz) <= step_hz:
                    if best is None or db > best:
                        best = db
        except (ValueError, IndexError):
            continue
    return best


def cmd_scan(config: Config) -> None:
    if not shutil.which("rtl_power"):
        print("rtl_power no encontrado. Instala rtl-sdr: sudo apt install rtl-sdr")
        return

    from weather_station.main import _paused_services

    scan_file = Path(tempfile.mktemp(suffix=".csv", prefix="noaa_scan_"))
    print("Escaneando banda 137 MHz (aprox. 5s)...", flush=True)
    try:
        with _paused_services(config.capture.competing_services):
            subprocess.run(
                ["rtl_power", "-d", str(config.capture.device_index),
                 "-f", "137.0M:138.0M:5k", "-i", "2", "-1", str(scan_file)],
                capture_output=True, timeout=20,
            )
    except FileNotFoundError:
        print("rtl_power no disponible.")
        return
    except subprocess.TimeoutExpired:
        print("rtl_power tardo demasiado (dispositivo en uso?).")
        scan_file.unlink(missing_ok=True)
        return

    if not scan_file.exists():
        print("No se genero el fichero de escaneo (dispositivo en uso?).")
        return

    csv_text = scan_file.read_text()
    scan_file.unlink(missing_ok=True)

    print(f"\n{'Satelite':<12}  {'Frecuencia':>12}  {'Nivel':>10}  Estado")
    print("-" * 56)

    powers: dict[str, float | None] = {}
    for name, sat_cfg in config.satellites.items():
        powers[name] = _parse_rtl_power_csv(csv_text, sat_cfg.frequency)

    valid = [p for p in powers.values() if p is not None]
    noise_floor = min(valid) if valid else -100.0

    for name, sat_cfg in config.satellites.items():
        pwr = powers[name]
        if pwr is None:
            status = "sin datos"
            pwr_str = "    N/A"
        else:
            delta = pwr - noise_floor
            status = "SENAL DETECTADA" if delta >= 10 else "sin senal"
            pwr_str = f"{pwr:+8.1f} dBm"
        print(f"{name:<12}  {sat_cfg.frequency/1e6:>10.4f} MHz  {pwr_str}  {status}")

    print(f"\n(Ruido de fondo estimado: {noise_floor:+.1f} dBm)")
    print("Nota: la senal solo es visible durante el paso del satelite sobre el horizonte.")
