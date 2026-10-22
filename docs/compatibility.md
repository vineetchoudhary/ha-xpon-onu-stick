# Device compatibility

## Tested devices

| Device | Mode | Firmware |
| --- | --- | --- |
| ODI DFP-34X-2C2, Realtek RTL9601D | GPON | `V1.0-220923`, stock SFU build `M110_sfp_ODI_220923.tar` |
| BDCOM ONU, exact model unconfirmed ([issue #1](https://github.com/vineetchoudhary/ha-xpon-onu-stick/issues/1)) | EPON | `V2.11.00P3T1` |

## Likely supported, not tested

These use related hardware or web pages. Check compatibility below before using them.

| Device or firmware | Check |
| --- | --- |
| ODI DFP-34X-2C3 | Same firmware and pages as the tested stick. |
| Other ODI SFU builds, including `220304`, `220414`, and `220817` | Status fields. |
| ODI HGU, hybrid, newer, or community builds | Status fields and login form. Compatibility is less certain. |
| ODI DFP-34G-2C2, Realtek version | Status fields and login form. |
| HSGQ XPON stick | Status fields and login form. |
| Luleey LL-XS2510 | CPU and memory fields on Device Status. |
| V-SOL V2801F and T&W TWCGPON657 | Status fields and login form. |

## Not supported

- Older ZTE-based ODI sticks and Lantiq/MaxLinear sticks with different web interfaces.
- Replacement firmware that removes the stock status pages, such as odi-oss.
- PON pages without a recognized GPON section or an **EPON LLID Status** table.

## Check an untested stick

- `/status.asp` and `/status_pon.asp` must use English labels and report a valid MAC address.
- The PON page must include a **GPON Status** section or an **EPON LLID Status** table.
- Login must use HTTP Basic authentication or the supported Realtek/Boa form. Nonempty login challenges and `psd` password fields are not supported.
- Check [sensor readings](sensors.md), repeated polls, restart, and reconfiguration on the device.

Use the [live check](development.md#test-the-real-stick) to read the device directly.

References: [firmware notes](https://github.com/Anime4000/RTL960x/blob/main/Firmware/DFP-34X-2C2/README.md), [firmware archive](https://www.tripleoxygen.net/files/devices/odi/dfp-34x-2c2/firmware/), and [hardware reference](https://hack-gpon.org/ont-odi-realtek-dfp-34x-2c2/).
