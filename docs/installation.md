# Installation

Requires Home Assistant **2026.9.0 or newer**. Home Assistant Core must be able to reach the ONU's web interface for stock firmware or its SSH port for [ODI OSS](configuration.md#odi-oss-over-ssh).

## HACS (recommended)

[![Open XPON ONU Stick in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=vineetchoudhary&repository=ha-xpon-onu-stick&category=integration)

Open the link, download **XPON ONU Stick**, and restart Home Assistant.

To add the repository manually:

1. In **HACS**, open **⋮ → Custom repositories**.
2. Enter `https://github.com/vineetchoudhary/ha-xpon-onu-stick`.
3. Choose **Integration** and select **Add**.
4. Find **XPON ONU Stick**, download it, and restart Home Assistant.

## Manual installation

1. Copy `custom_components/xpon_onu_stick` into `/config/custom_components/`.
2. Restart Home Assistant.

Then follow [Add the integration](configuration.md#1-add-the-integration).
