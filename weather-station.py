#!/usr/bin/env python3
"""NOAA Weather Satellite Ground Station — entry point."""
import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="weather-station",
        description="Estacion terrena automatizada para satelites NOAA (15/18/19)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Ejemplos:
  python weather-station.py                          # modo daemon (bucle continuo)
  python weather-station.py --check                  # verifica hardware y herramientas
  python weather-station.py --passes                 # proximas pasadas
  python weather-station.py --duration 600           # graba NOAA 19 durante 10 min
  python weather-station.py --duration 900 --satellite "NOAA 15"
  python weather-station.py --scan                   # busca senales en 137 MHz
""",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Comprueba que el RTL-SDR esta conectado y las herramientas instaladas",
    )
    parser.add_argument(
        "--passes",
        action="store_true",
        help="Muestra las proximas pasadas de satelite sobre tu ubicacion",
    )
    parser.add_argument(
        "--duration",
        type=int,
        metavar="SEGUNDOS",
        help="Graba bajo demanda durante N segundos (por defecto satelite: NOAA 19)",
    )
    parser.add_argument(
        "--satellite",
        default="NOAA 19",
        metavar="NOMBRE",
        help="Satelite para --duration (por defecto: 'NOAA 19')",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Escanea la banda 137 MHz y muestra niveles de senal en frecuencias NOAA",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    # If no flag is given, run as continuous daemon
    if not any([args.check, args.passes, args.duration is not None, args.scan]):
        from weather_station.main import main as daemon_main
        daemon_main()
        return

    from weather_station.cli import cmd_check, cmd_passes, cmd_receive, cmd_scan
    from weather_station.config import load_config

    if args.check:
        sys.exit(0 if cmd_check() else 1)

    config = load_config()

    if args.passes:
        cmd_passes(config)

    elif args.duration is not None:
        if args.duration <= 0:
            print("--duration debe ser un numero positivo de segundos.")
            sys.exit(1)
        sys.exit(0 if cmd_receive(config, args.satellite, args.duration) else 1)

    elif args.scan:
        cmd_scan(config)


if __name__ == "__main__":
    main()
