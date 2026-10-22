[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor%20on%20GitHub-EA4AAA?style=for-the-badge&logo=github&logoColor=white)](https://github.com/sponsors/vineetchoudhary)
[![Buy me a coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/vineetchoudhary)
[![Tests](https://img.shields.io/github/actions/workflow/status/vineetchoudhary/ha-xpon-onu-stick/tests.yml?style=for-the-badge&logo=githubactions&logoColor=white&label=Build)](https://github.com/vineetchoudhary/ha-xpon-onu-stick/actions/workflows/tests.yml)

# XPON ONU Stick for Home Assistant

Monitor your ONU SFP stick in Home Assistant through its local web interface, without changing device settings.

Supports **GPON and EPON**. Requires Home Assistant **2026.9.0 or newer**. See [tested devices and firmware](docs/compatibility.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/dashboard-card-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/screenshots/dashboard-card-light.png">
  <img alt="XPON ONU Stick dashboard with connection status, optical power, temperature, and system readings" src="docs/screenshots/dashboard-card-light.png" width="600">
</picture>

## Features

- Monitor optical power, temperature, voltage, laser bias current, CPU, and memory.
- Automatically detect GPON registration states or EPON LLID status codes.
- Adjust refresh intervals, status limits, and optional logout after polling.
- Use the included dashboard card with a 24-hour Rx power trend.
- Keep valid readings available when another field cannot be parsed.

## Quick Start

### HACS

With [HACS installed](https://www.hacs.xyz/docs/use/), open the repository:

[![Open XPON ONU Stick in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=vineetchoudhary&repository=ha-xpon-onu-stick&category=integration)

1. Download **XPON ONU Stick** and restart Home Assistant.
2. Open **Settings → Devices & services → Add integration** and select **XPON ONU Stick**.
3. Enter your ONU's management address and login credentials.

See [installation](docs/installation.md) for manual HACS setup or installation without HACS.

### Dashboard

Edit a dashboard, select **Add card**, and search for **XPON ONU Stick**. Home Assistant loads the card automatically.

## Documentation

- [Installation](docs/installation.md): HACS and manual setup.
- [Configuration and troubleshooting](docs/configuration.md): Add the device, change options, and resolve common issues.
- [Sensors and status limits](docs/sensors.md): Readings, thresholds, GPON registration states, and raw EPON LLID codes.
- [Dashboard card](docs/dashboard.md): Card options and built-in dashboard examples.
- [Device compatibility](docs/compatibility.md): Tested devices, firmware, and compatibility checks.
- [Connection and read-only behavior](docs/behavior.md): Polling, authentication, device identity, and error handling.
- [Firmware value handling](docs/firmware-values.md): Supported formats, parsing failures, and verification sources.
- [Screenshots](docs/screenshots.md): Dashboard, sensors, options, and ONU status pages.
- [Development](docs/development.md): Tests, live device checks, and dashboard previews.

## License

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.

## Support

If this project has been useful to you, consider supporting its continued development.

<a href="https://github.com/sponsors/vineetchoudhary">
  <img src="https://img.shields.io/badge/Sponsor%20on%20GitHub-EA4AAA?style=for-the-badge&logo=github&logoColor=white" alt="Sponsor on GitHub" height="50">
</a>

<a href="https://buymeacoffee.com/vineetchoudhary">
  <img src="https://img.shields.io/badge/Buy%20me%20a%20coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black" alt="Buy Me a Coffee" height="50">
</a>

Thank you for supporting open source! 🙏
