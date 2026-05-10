NOAA_APT_VERSION := 1.4.1
ARCH := $(shell uname -m)

# Map uname -m to the noaa-apt release filename triplet.
# ARM releases ship as .zip (no .deb); x86_64 has a .deb.
ifeq ($(ARCH),aarch64)
    NOAA_APT_TRIPLE := aarch64-linux-gnu
    NOAA_APT_PKG    := zip
else ifeq ($(ARCH),armv7l)
    NOAA_APT_TRIPLE := armv7-linux-gnueabihf
    NOAA_APT_PKG    := zip
else
    NOAA_APT_TRIPLE := x86_64-linux-gnu
    NOAA_APT_PKG    := zip
endif

NOAA_APT_ZIP  := noaa-apt-$(NOAA_APT_VERSION)-$(NOAA_APT_TRIPLE)-nogui.zip
NOAA_APT_URL  := https://github.com/martinber/noaa-apt/releases/download/v$(NOAA_APT_VERSION)/$(NOAA_APT_ZIP)

.PHONY: install install-system install-python install-noaa-apt \
        install-service uninstall-service setup-sudoers test clean

install: install-system install-noaa-apt install-python

install-system:
	sudo apt-get update
	sudo apt-get install -y \
		rtl-sdr \
		sox \
		at \
		python3-pip \
		python3-dev \
		python3-venv \
		libusb-1.0-0-dev

install-noaa-apt:
	sudo apt-get install -y unzip
	@echo "Downloading noaa-apt $(NOAA_APT_VERSION) ($(NOAA_APT_TRIPLE)-nogui)..."
	wget -q -O /tmp/$(NOAA_APT_ZIP) $(NOAA_APT_URL)
	unzip -o /tmp/$(NOAA_APT_ZIP) -d /tmp/noaa-apt-extract/
	sudo install -m 755 /tmp/noaa-apt-extract/noaa-apt /usr/local/bin/noaa-apt
	rm -rf /tmp/$(NOAA_APT_ZIP) /tmp/noaa-apt-extract/
	@echo "noaa-apt installed: $$(noaa-apt --version)"

install-python:
	python3 -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install --quiet poetry
	.venv/bin/poetry config virtualenvs.create false
	.venv/bin/poetry install --no-root

install-service:
	mkdir -p /home/pi/weather-station/logs
	sudo cp systemd/weather-station.service /etc/systemd/system/
	sudo cp systemd/weather-station.timer /etc/systemd/system/
	sudo systemctl daemon-reload
	sudo systemctl enable weather-station.service
	sudo systemctl start weather-station.service
	@echo "Service installed and started."

setup-sudoers:
	@echo "pi ALL=(ALL) NOPASSWD: /bin/systemctl stop dump1090-fa, /bin/systemctl start dump1090-fa" \
	  | sudo tee /etc/sudoers.d/weather-station-rtlsdr > /dev/null
	sudo chmod 440 /etc/sudoers.d/weather-station-rtlsdr
	@echo "Sudoers rule installed."

uninstall-service:
	sudo systemctl stop weather-station.service || true
	sudo systemctl disable weather-station.service || true
	sudo rm -f /etc/systemd/system/weather-station.service
	sudo rm -f /etc/systemd/system/weather-station.timer
	sudo systemctl daemon-reload

test:
	.venv/bin/pytest

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name ".pytest_cache" -delete
	find . -type d -name "*.egg-info" -delete
	rm -rf .coverage htmlcov/
