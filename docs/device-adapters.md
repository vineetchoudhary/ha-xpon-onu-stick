# Device adapters and firmware profiles

Device communication is separate from Home Assistant entities. Devices that use the same web interface share an adapter. Captured differences within that interface belong in small firmware profiles.

## Code layout

All paths below are inside `custom_components/xpon_onu_stick/`:

| File | Responsibility |
| --- | --- |
| [api.py](../custom_components/xpon_onu_stick/api.py) | Shared client workflow, login/session ownership, successful-poll logout, and field-error logging. Existing client and parser imports remain available here. |
| [transport.py](../custom_components/xpon_onu_stick/transport.py) | Host validation, HTTP requests, per-origin lock, isolated cookies, Basic authentication, timeouts, response limits, and request-policy enforcement. |
| [models.py](../custom_components/xpon_onu_stick/models.py) | Status snapshots, capabilities, MAC normalization, request policies, and exceptions. |
| [devices/base.py](../custom_components/xpon_onu_stick/devices/base.py) | The adapter and request interfaces. |
| [devices/boa/](../custom_components/xpon_onu_stick/devices/boa/) | The currently supported web-interface family, covering the supplied GPON and EPON pages. |
| [devices/boa/parsing.py](../custom_components/xpon_onu_stick/devices/boa/parsing.py) | Table parsing, numeric validation, PON mode detection, and raw LLID values. |
| [devices/boa/auth.py](../custom_components/xpon_onu_stick/devices/boa/auth.py) | Supported form validation, login/logout payloads, and acknowledgement parsing. |
| [devices/boa/profiles.py](../custom_components/xpon_onu_stick/devices/boa/profiles.py) | Proven field differences for captured firmware. |

The coordinator, sensors, config flow, and dashboard consume the shared status model. They do not select parsing rules by manufacturer or firmware version. Adapter, model, and transport modules do not import Home Assistant APIs.

## Interface families

An adapter owns the page formats and authentication semantics of a web interface. This can cover several device brands and firmware versions. GPON and EPON are detected from the PON page and do not require separate copies of the client.

There is one supported family today, `BoaAdapter`, which is the default. `OnuClient` accepts an explicit `adapter=` for another implementation of the same contract. There is no search through alternate endpoints or repeated login attempts to guess a family. When adding another family, introduce an explicit selection path or deterministic identification from verified pages before credentials are submitted.

An adapter must:

- Declare its allowed request methods/paths and POST Referer paths in an immutable `HttpPolicy`.
- Read status through the supplied asynchronous request function, sequentially, and return an `OnuStatus` only after all required pages and device identity are validated.
- Parse values into the common sensor keys and units while preserving raw GPON text and EPON codes.
- Validate its login form before building a payload, recognize login/session-busy responses, and verify logout acknowledgement.
- Interpret authentication redirects and known malformed login responses without following redirects.

The shared client owns login retries, session ownership, and optional logout. An adapter must not create an HTTP session, bypass the shared transport, decide to close a borrowed session, or change a device setting. The transport enforces the selected policy and rejects foreign URLs, query/fragment paths, and unreviewed methods before sending a request.

## Firmware profiles

Profiles describe confirmed differences within a family. Do not create a separate parser or client for each model or version that uses the same schema.

The Boa adapter parses and validates both pages before selecting a profile. It uses the reported firmware version and the mode detected from the PON table. Firmware names alone never establish PON mode, manufacturer, or hardware identity.

The supplied EPON capture reports `V2.11.00P3T1` and omits the visible Device Name row. Its profile marks `device_name` as optional. Other EPON firmware does not automatically inherit that exception.

Unrecognized versions use the generic Boa profile when their page structure is supported. A missing or unknown firmware version does not prevent valid readings from updating, but cannot establish a firmware-specific exception. If multiple profiles match, the snapshot is rejected with an ambiguous-profile error instead of choosing the first match.

Each profile can declare:

| Field setting | Behavior |
| --- | --- |
| Supported, required by default | Missing or invalid data produces an unknown reading with a field error. Other valid readings continue updating. |
| `optional_fields` | A missing row produces an unknown reading without a field error. A present but invalid value still produces an error. |
| `unsupported_fields` | The field is excluded from supported capabilities and does not produce a parsing error. New entities and their related friendly statuses are not created for it. Existing entities become unavailable without changing their unique IDs. |

MAC identity cannot be optional or unsupported. A field cannot be both optional and unsupported. Keep each exception narrow and cite its captured device/firmware evidence beside the profile.

## Adding a device

1. Collect and sanitize the actual status and authentication HTML using [device support requests](device-support.md). Preserve fixture provenance and the [model/firmware directory layout](../tests/fixtures/README.md).
2. Replay the pages through the existing adapter. If they match its schema and behavior, add fixture coverage and compatibility documentation.
3. Add a profile only for a demonstrated difference in field expectations. Include the exact matching conditions and regression tests. Avoid deriving a hardware model from firmware comments.
4. Add a new family under `devices/` when the status format, endpoints, or authentication protocol requires different code. Implement the shared contract and keep all requests behind the shared transport. Do not fork the coordinator, sensors, or dashboard.
5. Run the checks in [development](development.md). Cover captured values, malformed/missing fields, authentication, session ownership, recovery, profile ambiguity, PON mode changes, and stable entity identity as applicable.
6. Update the compatibility record with the evidence actually available. Fixture tests do not establish acceptance on a physical device or in a running Home Assistant dashboard.

`tests/test_devices.py` covers profile and adapter boundaries. The existing capture, parser, session, integration, and browser tests remain the shared regression suite. Its synthetic JSON adapter exercises the extension contract and does not represent support for an additional physical device.
