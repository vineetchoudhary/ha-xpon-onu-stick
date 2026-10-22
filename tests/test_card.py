"""Verify the dashboard card is served and can find every sensor."""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from homeassistant.components.http.server import HomeAssistantHTTP
from homeassistant.components.lovelace import LovelaceData
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE, MODE_YAML
from homeassistant.components.lovelace.dashboard import LovelaceStorage
from homeassistant.components.lovelace.resources import (
    ResourceStorageCollection,
    ResourceYAMLCollection,
)
from homeassistant.components.lovelace.websocket import websocket_lovelace_resources_impl
from homeassistant.const import CONF_HOST, EVENT_COMPONENT_LOADED, EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.http import KEY_ALLOW_CONFIGURED_CORS

from custom_components.xpon_onu_stick import async_setup
from custom_components.xpon_onu_stick.const import CARD_URL, DOMAIN
from custom_components.xpon_onu_stick.frontend import async_register_card
from custom_components.xpon_onu_stick.sensor import GPON_SENSOR_KEYS, SENSORS, STATUS_SENSORS
from tools.card_ui import Browser, find_browser

CARD = (
    Path(__file__).parents[1] / "custom_components" / DOMAIN / "frontend" / "xpon-onu-stick-card.js"
)
CARD_VERSION = json.loads((CARD.parents[1] / "manifest.json").read_text())["version"]


@pytest.fixture
def dashboard(hass):
    """Use Home Assistant's real static server and resource collection."""
    hass.http = HomeAssistantHTTP(hass, None, None, None, ["127.0.0.1"], 0, [], "modern")
    hass.http.app[KEY_ALLOW_CONFIGURED_CORS] = lambda route: None
    resources = ResourceStorageCollection(hass, LovelaceStorage(hass, None))
    hass.data[LOVELACE_DATA] = LovelaceData(MODE_STORAGE, {}, resources, {})
    hass.config.components.add("frontend")
    return resources


async def test_card_is_served_at_the_registered_dashboard_resource(hass, dashboard):
    assert await async_setup(hass, {})
    await hass.async_block_till_done()

    connection = MagicMock()
    await websocket_lovelace_resources_impl(hass, connection, {"id": 1})
    resources = connection.send_result.call_args.args[1]
    assert len(resources) == 1
    resource = resources[0]
    assert resource["type"] == "module"
    assert resource["url"] == f"{CARD_URL}?v={CARD_VERSION}"
    async with TestServer(hass.http.app) as server, ClientSession() as session:
        async with session.get(server.make_url(resource["url"])) as response:
            assert response.status == 200
            assert response.content_type in ("text/javascript", "application/javascript")
            assert await response.text() == CARD.read_text()


@pytest.mark.skipif(find_browser() is None, reason="needs a Chromium-based browser")
async def test_registered_resource_defines_the_card_in_a_browser(hass, dashboard):
    assert await async_setup(hass, {})
    await hass.async_block_till_done()
    connection = MagicMock()
    await websocket_lovelace_resources_impl(hass, connection, {"id": 1})
    resources = connection.send_result.call_args.args[1]

    async def page_handler(request):
        return web.Response(
            text="<!doctype html><title>Card loading test</title>", content_type="text/html"
        )

    hass.http.app.router.add_get("/card-test", page_handler)
    async with TestServer(hass.http.app) as server, Browser(find_browser()) as browser:
        page = await browser.new_page(1280, 1000)
        await page.goto(str(server.make_url("/card-test")))
        result = await page.evaluate(
            "(async () => {"
            f"for (const resource of {json.dumps(resources)}) await import(resource.url);"
            'const card = document.createElement("xpon-onu-stick-card");'
            'card.setConfig({type: "custom:xpon-onu-stick-card"});'
            "document.body.append(card);"
            "return {card: Boolean(card.shadowRoot), "
            'editor: Boolean(customElements.get("xpon-onu-stick-card-editor")), '
            'picker: window.customCards.some(item => item.type === "xpon-onu-stick-card")};'
            "})()"
        )
        assert result == {"card": True, "editor": True, "picker": True}
        assert not browser.errors


async def test_card_is_skipped_without_a_frontend(hass):
    assert hass.http is None
    assert await async_setup(hass, {})
    await hass.async_block_till_done()
    assert LOVELACE_DATA not in hass.data


async def test_card_loads_when_the_frontend_starts_later(hass, dashboard):
    hass.config.components.remove("frontend")
    assert await async_setup(hass, {})
    await hass.async_block_till_done()
    assert not dashboard.loaded

    hass.config.components.add("frontend")
    hass.bus.async_fire(EVENT_COMPONENT_LOADED, {"component": "frontend"})
    await hass.async_block_till_done()
    assert len(dashboard.async_items()) == 1
    assert dashboard.async_items()[0]["url"].startswith(CARD_URL)


async def test_card_resource_is_updated_without_duplicates_or_unrelated_changes(hass, dashboard):
    old = await dashboard.async_create_item({"url": f"{CARD_URL}?v=0.3.0", "res_type": "js"})
    await dashboard.async_create_item({"url": CARD_URL, "res_type": "module"})
    other = await dashboard.async_create_item({"url": "/other-card.js", "res_type": "module"})
    external = await dashboard.async_create_item(
        {"url": f"https://example.com{CARD_URL}", "res_type": "module"}
    )

    await async_register_card(hass, "frontend")
    await async_register_card(hass, "frontend")
    assert dashboard.async_items() == [
        {**old, "url": f"{CARD_URL}?v={CARD_VERSION}", "type": "module"},
        other,
        external,
    ]


async def test_card_resource_survives_a_restart(hass, dashboard):
    await async_register_card(hass, "frontend")
    # Exercise the real shutdown save before recreating the collection.
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()
    stored = json.loads(
        await hass.async_add_executor_job(
            Path(hass.config.path(".storage/lovelace_resources")).read_text
        )
    )
    assert stored["data"]["items"] == dashboard.async_items()
    restored = ResourceStorageCollection(hass, LovelaceStorage(hass, None))
    await restored.async_get_info()
    assert restored.async_items() == dashboard.async_items()
    assert len(restored.async_items()) == 1


async def test_yaml_resources_are_preserved_with_instructions(hass, dashboard, caplog):
    resources = ResourceYAMLCollection([{"url": "/my-card.js", "type": "module"}])
    hass.data[LOVELACE_DATA] = LovelaceData(MODE_YAML, {}, resources, {})
    await async_register_card(hass, "frontend")
    assert resources.async_items() == [{"url": "/my-card.js", "type": "module"}]
    assert f"{CARD_URL}?v={CARD_VERSION}" in caplog.text
    assert "type: module" in caplog.text


def test_card_uses_the_integration_domain():
    assert re.search(rf'const DOMAIN = "{DOMAIN}";', CARD.read_text())


@pytest.mark.parametrize("mode", ["gpon", "epon"])
async def test_card_readings_have_discoverable_translation_keys(
    hass, onu_server, epon_pon_html, mode
):
    host, state, _ = onu_server
    if mode == "epon":
        state["pon"] = epon_pon_html
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={CONF_HOST: host}
    )
    await hass.async_block_till_done()

    entries = er.async_entries_for_config_entry(er.async_get(hass), result["result"].entry_id)
    keys = {description.key for description in SENSORS + STATUS_SENSORS}
    if mode == "epon":
        keys -= GPON_SENSOR_KEYS
        llids = [entry for entry in entries if "_epon_llid_" in entry.unique_id]
        assert len(llids) == 2
        entries = [entry for entry in entries if entry not in llids]
    assert {entry.translation_key for entry in entries} == keys
    assert len(entries) == len(keys)
