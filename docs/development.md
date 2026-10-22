# Development

Run commands from the repository root with **Python 3.14.2 or newer in the 3.14 series**.

## Set up and run the checks

Create the environment and install dependencies:

```sh
./scripts/test.sh --setup
```

For later runs:

```sh
./scripts/test.sh
```

Checks cover metadata, dependencies, formatting, integration behavior, and the dashboard. Logs are saved in `.test-results/`.

Tests replay sanitized captures from both the ODI GPON device and the issue #1 EPON device. Pages are stored directly under `tests/fixtures/devices/<model>/<firmware>/`, using `default` when the firmware version is unknown. Older snapshots use descriptive filenames within the same firmware directory. GPON captures saved through the browser's View Source page were decoded back to their original HTML. See [fixture layout and provenance](../tests/fixtures/README.md).

Coverage includes mode changes, dynamic LLID indices, oversized integer conversion with Python's limit enabled and disabled, and isolated field errors. Session tests cover cookie reuse across setup, shared device locks, login conflicts, owned-session logout, failure recovery, and options reloads. Security regressions cover cookie isolation, foreign form actions, fixed request paths, response size limits, bounded entity creation, and safe dashboard rendering of firmware text. These simulations do not establish live EPON compatibility.

## Test the real stick

Replace `http://onu.example` with your ONU address:

```sh
./scripts/test.sh --live --host http://onu.example
```

When login is required:

```sh
./scripts/test.sh --live --host http://onu.example --username YOUR_USERNAME
```

The password is prompted privately. Readings are printed and saved in the log. Invalid fields show as `null` with an error. No device settings are changed.

## Preview and test the dashboard card

```sh
./scripts/card.sh debug
```

Open `http://127.0.0.1:8765` to try sample readings, themes, and options.

```sh
./scripts/card.sh test
```

Browser checks need Chrome, Edge, Chromium, or Brave. Set `CHROME_PATH` if needed. Failure screenshots are saved in `.test-results/`.

Regenerate the card images:

```sh
./scripts/card.sh screenshots
```

Preview files and UI tests are in [tools/card](../tools/card/).
