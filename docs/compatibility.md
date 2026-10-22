# Device compatibility

## Compatible (tested)

| Device | Firmware |
| --- | --- |
| ODI DFP-34X-2C2, Realtek RTL9601D | `V1.0-220923`, stock SFU build `M110_sfp_ODI_220923.tar` |

## Saved pages covered by tests

| Device | Mode and firmware | Coverage |
| --- | --- | --- |
| ODI DFP-34X-2C2 | GPON, `V1.0-220923` | Saved Device Status, PON Status, login, logout form, and logout confirmation. Replayed through parser and Home Assistant tests. |
| Reported BDCOM ONU, exact model unconfirmed ([issue #1](https://github.com/vineetchoudhary/ha-xpon-onu-stick/issues/1)) | EPON, `V2.11.00P3T1` | Saved Device Status, PON Status, login form, and already-logged-in response. Replayed with cookie and IP session simulations. Live integration validation is pending. |

The EPON page contains an **EPON LLID Status** table with indices `0` and `1`. Status codes are exposed unchanged without interpreting them as GPON registration states. The commented Vendor Name `Twowing` and Part Number `GN25L95` are source-page metadata, not confirmation of the complete device model. They are not used for device identity or mode detection.

## Likely supported, not tested

These use related hardware or web pages. Run the [compatibility checks](#check-an-untested-stick) before relying on them.

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
- EPON web layouts without the recognized LLID table structure.
- PON pages containing only optical measurements without a recognized GPON heading/field or EPON LLID table.

## Check an untested stick

- Both `/status.asp` and `/status_pon.asp` must be reachable and use English field labels.
- Check the expected [sensors](sensors.md) and a valid MAC address.
- GPON registration monitoring and EPON LLID status readings are selected automatically from the PON page.
- Login must use HTTP Basic authentication or the supported `/boaform/admin/formLogin` form with `username`, `password`, `save`, and an empty `challenge`. Relative actions and absolute actions on the configured origin are accepted. Forms using a `psd` password field or a nonempty challenge are not supported.
- Confirm that setup, repeated polls, restart, and reconfiguration work on the actual device. Saved pages and simulations do not establish complete device compatibility.

Run the [live check](development.md#test-the-real-stick) to confirm readings. Missing or invalid fields are handled as described in [firmware values](firmware-values.md).

References: [firmware notes](https://github.com/Anime4000/RTL960x/blob/main/Firmware/DFP-34X-2C2/README.md), [firmware archive](https://www.tripleoxygen.net/files/devices/odi/dfp-34x-2c2/firmware/), and [hardware reference](https://hack-gpon.org/ont-odi-realtek-dfp-34x-2c2/).
