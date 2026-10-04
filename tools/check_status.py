"""Print current readings, authenticating with the ONU login form if needed."""

import argparse
import asyncio
import json
import sys
from getpass import getpass
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.xpon_onu_stick.api import OnuClient, OnuError  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", required=True, help="ONU hostname, IP address, or HTTP(S) base URL"
    )
    parser.add_argument("--username", default="")
    args = parser.parse_args()
    password = getpass("ONU password: ") if args.username else ""
    try:
        async with aiohttp.ClientSession() as session:
            status = await OnuClient(session, args.host, args.username, password).async_get_status()
        print(json.dumps(status.values, indent=2))
    except (OnuError, ValueError) as err:
        parser.exit(1, f"Could not read ONU status: {err}\n")


if __name__ == "__main__":
    asyncio.run(main())
