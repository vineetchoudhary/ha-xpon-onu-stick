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

EPON tests use sanitized captures in `tests/fixtures/epon_*.html` and cover mode changes, dynamic LLID indices, oversized integer conversion, isolated field errors, and GPON regression checks. Session tests cover default session reuse, the logout option, the captured POST/response, repeated login, and noncritical failures. These simulations do not establish live EPON compatibility.

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
