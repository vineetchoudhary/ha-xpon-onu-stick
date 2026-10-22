// UI tests for the dashboard card. `./scripts/card.sh test` runs them in a
// headless browser; open preview.html?mode=test to watch them in any browser.
import { SCENARIOS } from "./scenarios.js";
import { createHass, DEVICE_ID, loadTranslations, nextPoll } from "./mock-hass.js";

const CARD = "xpon-onu-stick-card";
const tests = [];
let translations;

const test = (name, run) => tests.push({ name, run });
const tick = (ms = 30) => new Promise((resolve) => setTimeout(resolve, ms));
const text = (element) => (element?.textContent || "").replace(/\s+/g, " ").trim();
const $ = (card, selector) => card.shadowRoot.querySelector(selector);
const $$ = (card, selector) => [...card.shadowRoot.querySelectorAll(selector)];

function equal(actual, expected, what) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${what}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function ok(condition, message) {
  if (!condition) throw new Error(message);
}

const toneOf = (element) => [...(element?.classList || [])].find((name) => name.startsWith("tone-"));

async function mount(scenario, config = {}, options = {}) {
  const card = document.createElement(CARD);
  card.setConfig({ type: `custom:${CARD}`, ...config });
  card.hass = createHass(SCENARIOS[scenario], translations, options);
  document.getElementById("tests").append(card);
  await tick();
  return card;
}

const tiles = (card) =>
  $$(card, ".tile").map((tile) => [text(tile.querySelector(".label")), text(tile.querySelector(".value")), text(tile.querySelector(".status"))]);

test("shows the stick name, firmware, uptime, and connection", async () => {
  const card = await mount("healthy");
  equal(text($(card, ".title")), "AOT5222ZY", "title");
  equal(text($(card, ".subtitle")), "Firmware V1.0-220923 · Up 3 days, 21:22", "subtitle");
  equal(text($(card, ".badge")), "Connected O5", "badge");
  equal(toneOf($(card, ".badge")), "tone-ok", "badge tone");
});

test("renders firmware text as text without executing HTML", async () => {
  const card = await mount("healthy");
  window.__onuHtmlExecuted = false;
  const payload = '\"><img src=x onerror="window.__onuHtmlExecuted=true"><script>window.__onuHtmlExecuted=true</script>';
  const hass = card._hass;
  const states = { ...hass.states };
  for (const key of ["firmware_version", "uptime", "loid_status"]) {
    const entityId = `sensor.aot5222zy_${key}`;
    states[entityId] = { ...states[entityId], state: payload };
  }
  card.setConfig({ type: `custom:${CARD}`, title: payload });
  card.hass = { ...hass, states };
  await tick();
  equal(text($(card, ".title")), payload, "escaped title");
  ok(text($(card, ".subtitle")).includes(payload), "firmware text remains visible");
  equal($$(card, "img, script").length, 0, "no injected elements");
  equal(window.__onuHtmlExecuted, false, "untrusted text did not execute");
});

test("keeps EPON optical readings without claiming GPON registration", async () => {
  const card = await mount("healthy");
  const hass = card._hass;
  const entities = { ...hass.entities };
  const states = { ...hass.states };
  for (const key of ["onu_state", "onu_id", "loid_status", "onu_registration_status"]) {
    delete entities[`sensor.aot5222zy_${key}`];
    delete states[`sensor.aot5222zy_${key}`];
  }
  card.hass = { ...hass, entities, states };
  await tick();
  equal(text($(card, ".value-xl")), "-21.84dBm", "optical reading");
  equal($$(card, ".tile").length, 4, "common measurement tiles");
  ok(!text($(card, ".badge")).includes("Connected"), "no invented registration state");
  ok(!$$(card, ".detail .key").map(text).includes("ONU ID"), "GPON-only detail omitted");
});

test("rates Rx power against the configured limits", async () => {
  const card = await mount("healthy");
  equal(text($(card, ".value-xl")), "-21.84dBm", "Rx value");
  equal(text($(card, ".hero .chip")), "Good", "Rx status");
  equal(toneOf($(card, ".hero .chip")), "tone-ok", "Rx tone");
  equal(text($(card, ".hero .caption")), "5.16 dB above the minimum · 13.84 dB below the maximum", "margins");
  equal($$(card, ".tick").map(text), ["-27", "-8"], "limit ticks");
  const marker = parseFloat($(card, ".marker").style.left);
  const [low, high] = $$(card, ".tick").map((tick) => parseFloat(tick.style.left));
  ok(marker > low && marker < high, `marker ${marker}% sits between the limits (${low}%-${high}%)`);
});

test("warns when Rx power nears the minimum", async () => {
  const card = await mount("weak");
  equal(text($(card, ".hero .chip")), "Weak signal", "Rx status");
  equal(toneOf($(card, ".hero .chip")), "tone-warn", "Rx tone");
  equal(text($(card, ".hero .caption")), "0.62 dB above the minimum · 18.38 dB below the maximum", "margins");
});

test("flags registration problems and readings out of range", async () => {
  const card = await mount("problem");
  equal(text($(card, ".badge")), "Waiting for registration O2", "badge");
  equal(toneOf($(card, ".badge")), "tone-warn", "badge tone");
  equal(text($(card, ".hero .chip")), "Signal too weak", "Rx status");
  equal(toneOf($(card, ".hero .chip")), "tone-bad", "Rx tone");
  equal(text($(card, ".hero .caption")), "1.4 dB below the minimum", "margin");
  equal(
    $$(card, ".tile .status").map(toneOf),
    ["tone-bad", "tone-bad", "tone-bad", "tone-ok"],
    "tile tones",
  );
});

test("shows every measurement tile with its status", async () => {
  const card = await mount("healthy");
  equal(
    tiles(card),
    [
      ["Tx power", "2.06 dBm", "Good"],
      ["Temperature", "41.20 °C", "Normal"],
      ["Voltage", "3.256 V", "Normal"],
      ["Bias current", "11.40 mA", "Limits not set"],
    ],
    "tiles",
  );
});

test("colors CPU and memory bars by load", async () => {
  const healthy = await mount("healthy");
  equal($$(healthy, ".bar").map(toneOf), ["tone-primary", "tone-primary"], "normal load");
  equal($$(healthy, ".meter-head b").map(text), ["3%", "50%"], "usage");
  const busy = await mount("problem");
  equal($$(busy, ".bar").map(toneOf), ["tone-warn", "tone-bad"], "high load");
});

test("lists ONU and network details with a readable MAC address", async () => {
  const card = await mount("healthy");
  const details = Object.fromEntries(
    $$(card, ".detail").map((detail) => [text(detail.querySelector(".key")), text(detail.querySelector(".val"))]),
  );
  equal(
    details,
    {
      "ONU state": "O5",
      "ONU ID": "0",
      "LOID status": "Initial Status",
      "IP address": "192.168.1.1",
      "Subnet mask": "255.255.255.0",
      "MAC address": "02:00:00:00:00:01",
    },
    "details",
  );
});

test("draws the 24-hour Rx trend from history", async () => {
  const card = await mount("healthy");
  const line = $(card, ".spark .line")?.getAttribute("d") || "";
  ok(line.split("L").length > 50, `trend has a point per bucket (${line.split("L").length})`);
  ok(/^Last 24 h: -2\d\.\d+ to -2\d\.\d+ dBm$/.test(text($$(card, ".hero .caption")[1])), "trend range caption");
});

test("leaves out the trend when history can't be loaded", async () => {
  const card = await mount("healthy", {}, { historyFails: true });
  equal($(card, ".spark"), null, "trend");
  equal(text($(card, ".hero .chip")), "Good", "the rest still renders");
});

test("options hide sections and the MAC address", async () => {
  const card = await mount("healthy", { title: "Fiber", show_history: false, show_system: false, hide_mac: true });
  equal(text($(card, ".title")), "Fiber", "title");
  equal($(card, ".spark"), null, "trend");
  equal($(card, ".meters"), null, "CPU and memory");
  ok(!text($(card, ".details")).includes("MAC address"), "MAC address is hidden");
  const plain = await mount("healthy", { show_details: false });
  equal($(plain, ".details"), null, "details");
});

test("shows Unavailable when the stick can't be reached", async () => {
  const card = await mount("unavailable");
  equal(text($(card, ".badge")), "Unavailable", "badge");
  equal(text($(card, ".value-xl")), "—", "Rx value");
  equal(tiles(card).map(([, value]) => value), ["—", "—", "—", "—"], "tile values");
});

test("isolates a parsing failure and restores the reading on recovery", async () => {
  const card = await mount("healthy");
  const healthy = card._hass;
  const states = { ...healthy.states };
  for (const key of ["tx_power", "tx_power_status"]) {
    const entityId = `sensor.aot5222zy_${key}`;
    states[entityId] = {
      ...states[entityId],
      state: "unknown",
      attributes: { ...states[entityId].attributes, parse_error: "Invalid number for tx power: '-inf dBm'" },
    };
  }
  card.hass = { ...healthy, states };
  await tick();
  equal(text($(card, ".badge")), "Connected O5", "registration remains visible");
  equal(text($(card, ".value-xl")), "-21.84dBm", "Rx remains visible");
  equal(tiles(card), [
    ["Tx power", "—", "—"],
    ["Temperature", "41.20 °C", "Normal"],
    ["Voltage", "3.256 V", "Normal"],
    ["Bias current", "11.40 mA", "Limits not set"],
  ], "only the affected tile is unknown");
  equal($$(card, ".meter-head b").map(text), ["3%", "50%"], "system readings remain visible");
  card.hass = healthy;
  await tick();
  equal(tiles(card)[0], ["Tx power", "2.06 dBm", "Good"], "Tx recovers");
});

test("explains when no stick is configured", async () => {
  const card = await mount("empty");
  ok(text($(card, ".empty")).startsWith("No XPON ONU Stick device found"), "empty message");
});

test("opens more-info for the selected reading", async () => {
  const card = await mount("healthy");
  const opened = [];
  card.addEventListener("hass-more-info", (event) => opened.push(event.detail.entityId));
  $$(card, ".tile")[0].click();
  $(card, ".hero").click();
  equal(opened, ["sensor.aot5222zy_tx_power", "sensor.aot5222zy_rx_power"], "more-info targets");
});

test("updates when a new poll arrives", async () => {
  const card = await mount("healthy");
  const hass = nextPoll(card._hass);
  card.hass = hass;
  await tick();
  const rx = hass.states["sensor.aot5222zy_rx_power"].state;
  equal(text($(card, ".value-xl")), `${Number(rx).toFixed(2)}dBm`, "new Rx value");
});

test("offers the only stick in the card picker", async () => {
  const hass = createHass(SCENARIOS.healthy, translations);
  equal(customElements.get(CARD).getStubConfig(hass), { device_id: DEVICE_ID }, "stub config");
  ok(window.customCards.some((card) => card.type === CARD), "registered in the card picker");
});

test("editor saves only options that differ from the defaults", async () => {
  const editor = customElements.get(CARD).getConfigElement();
  document.getElementById("tests").append(editor);
  editor.hass = createHass(SCENARIOS.healthy, translations);
  editor.setConfig({ type: `custom:${CARD}` });
  const saved = [];
  editor.addEventListener("config-changed", (event) => saved.push(event.detail.config));
  const form = editor.querySelector("ha-form");
  ok(form, "editor uses ha-form");
  form.dispatchEvent(new CustomEvent("value-changed", { detail: { value: { ...form.data, show_history: false } } }));
  form.dispatchEvent(new CustomEvent("value-changed", { detail: { value: { ...form.data, show_history: true, title: "" } } }));
  equal(saved, [{ type: `custom:${CARD}`, show_history: false }, { type: `custom:${CARD}` }], "saved configs");
});

export async function runCardTests() {
  translations = await loadTranslations();
  const results = [];
  for (const { name, run } of tests) {
    document.getElementById("tests").replaceChildren();
    try {
      await run();
      results.push({ name, ok: true, error: "" });
    } catch (error) {
      results.push({ name, ok: false, error: String(error?.message || error) });
    }
  }
  return results;
}
