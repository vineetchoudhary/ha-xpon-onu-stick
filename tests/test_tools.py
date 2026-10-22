"""Exercise the live-check command against the read-only localhost ONU simulator."""

import asyncio
import json
import sys
from pathlib import Path

CHECK_STATUS = Path(__file__).resolve().parents[1] / "tools/check_status.py"


async def run_status_check(host: str | None, working_directory: Path) -> tuple[int, str, str]:
    host_args = ("--host", host) if host is not None else ()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(CHECK_STATUS),
        *host_args,
        cwd=working_directory,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(20):
            stdout, stderr = await process.communicate()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    return process.returncode, stdout.decode(), stderr.decode()


async def test_live_check_requires_an_explicit_address(tmp_path):
    returncode, stdout, stderr = await run_status_check(None, tmp_path)
    assert returncode == 2
    assert stdout == ""
    assert "required: --host" in stderr


async def test_live_check_prints_complete_status(onu_server, tmp_path):
    host, _, requests = onu_server
    returncode, stdout, stderr = await run_status_check(host, tmp_path)
    assert returncode == 0, stderr
    readings = json.loads(stdout)
    assert len(readings) == 16
    assert readings["device_name"] == "AOT5222ZY"
    assert readings["rx_power"] == -26.382721
    assert readings["onu_id"] == 0
    assert requests == [
        ("GET", "/status.asp", None),
        ("GET", "/status_pon.asp", None),
    ]


async def test_live_check_prints_epon_status(onu_server, tmp_path, epon_device_html, epon_pon_html):
    host, state, requests = onu_server
    state.update(device=epon_device_html, pon=epon_pon_html)
    returncode, stdout, stderr = await run_status_check(host, tmp_path)
    assert returncode == 0, stderr
    readings = json.loads(stdout)
    assert readings["device_name"] is None
    assert readings["rx_power"] == -18.1
    assert readings["epon_llid_0_status"] == 1
    assert readings["epon_llid_1_status"] == 0
    assert "onu_state" not in readings
    assert requests == [
        ("GET", "/status.asp", None),
        ("GET", "/status_pon.asp", None),
    ]


async def test_live_check_reports_outage_readings_and_field_error(
    onu_server, tmp_path, outage_pon_html
):
    host, state, _ = onu_server
    state["pon"] = outage_pon_html
    returncode, stdout, stderr = await run_status_check(host, tmp_path)
    assert returncode == 0, stderr
    readings = json.loads(stdout)
    assert readings["tx_power"] is None
    assert readings["rx_power"] == -40.0
    assert readings["onu_state"] == "O1"
    assert "Invalid number for tx power: '-inf dBm'" in stderr


async def test_live_check_returns_failure_on_server_error(onu_server, tmp_path):
    host, state, requests = onu_server
    state["status"] = 500
    returncode, stdout, stderr = await run_status_check(host, tmp_path)
    assert returncode == 1
    assert stdout == ""
    assert "Could not read ONU status:" in stderr
    assert requests == [("GET", "/status.asp", None)]


async def test_live_check_returns_failure_when_credentials_are_required(onu_server, tmp_path):
    host, state, requests = onu_server
    state["form_auth"] = ("test-user", "test-password")
    returncode, stdout, stderr = await run_status_check(host, tmp_path)
    assert returncode == 1
    assert stdout == ""
    assert "Could not read ONU status:" in stderr
    assert state["login_posts"] == []
    assert all(method == "GET" for method, _, _ in requests)
    assert "test-password" not in stderr
