/*
 * XPON ONU Stick dashboard card.
 *
 * Shows every reading of one ONU stick in a single card. The integration serves
 * this file and registers its dashboard resource automatically.
 * It has no build step and no external libraries.
 */

(() => {
  const CARD_TYPE = "xpon-onu-stick-card";
  const DOMAIN = "xpon_onu_stick";
  const HISTORY_HOURS = 24;
  const HISTORY_REFRESH_MS = 10 * 60 * 1000;
  const HISTORY_POINTS = 96;
  const DEFAULTS = { show_history: true, show_system: true, show_details: true, hide_mac: false };

  // Status sensor states mapped to a colour tone.
  const TONES = {
    good: "ok",
    connected: "ok",
    weak: "warn",
    strong: "warn",
    warm: "warn",
    initial: "warn",
    standby: "warn",
    serial_number: "warn",
    ranging: "warn",
    recovering: "warn",
    low: "bad",
    high: "bad",
    invalid: "bad",
    disabled: "bad",
    unrecognized: "bad",
    limits_not_set: "muted",
  };
  const TILES = [
    ["tx_power", "Tx power"],
    ["temperature", "Temperature"],
    ["voltage", "Voltage"],
    ["bias_current", "Bias current"],
  ];

  const isMissing = (stateObj) =>
    !stateObj || stateObj.state === "unavailable" || stateObj.state === "unknown";

  const escapeHtml = (value) =>
    String(value).replace(
      /[&<>"']/g,
      (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
    );

  const toneOf = (stateObj) => (isMissing(stateObj) ? "muted" : TONES[stateObj.state] || "muted");

  /** Find the stick devices that this integration created. */
  function stickDevices(hass) {
    const devices = new Set();
    for (const entry of Object.values(hass.entities || {})) {
      if (entry.platform === DOMAIN && entry.device_id) devices.add(entry.device_id);
    }
    return [...devices];
  }

  /** Map translation keys (rx_power, rx_power_status, ...) to the device's entity IDs. */
  function stickEntities(hass, deviceId) {
    const entities = {};
    for (const [entityId, entry] of Object.entries(hass.entities || {})) {
      if (entry.platform === DOMAIN && entry.device_id === deviceId && entry.translation_key) {
        entities[entry.translation_key] = entityId;
      }
    }
    return entities;
  }

  function historyTimestamp(row) {
    if (typeof row.lu === "number") return row.lu * 1000;
    return Date.parse(row.last_updated || row.last_changed);
  }

  /** Average readings into equal time buckets so the sparkline stays light. */
  function downsample(points, buckets) {
    if (points.length <= buckets) return points;
    const start = points[0][0];
    const span = points[points.length - 1][0] - start || 1;
    const sums = new Map();
    for (const [time, value] of points) {
      const bucket = Math.min(buckets - 1, Math.floor(((time - start) / span) * buckets));
      const sum = sums.get(bucket) || [0, 0, 0];
      sum[0] += time;
      sum[1] += value;
      sum[2] += 1;
      sums.set(bucket, sum);
    }
    return [...sums.values()].map(([times, values, count]) => [times / count, values / count]);
  }

  class XponOnuStickCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._states = {};
      this._history = null;
      this._historyLoaded = 0;
    }

    static getConfigElement() {
      return document.createElement(`${CARD_TYPE}-editor`);
    }

    static getStubConfig(hass) {
      const [deviceId] = stickDevices(hass);
      return deviceId ? { device_id: deviceId } : {};
    }

    setConfig(config) {
      if (!config || typeof config !== "object") throw new Error("Invalid configuration");
      this._config = { ...DEFAULTS, ...config };
      this._entities = null;
      this._history = null;
      this._historyLoaded = 0;
      this._render();
      if (this._hass) this._loadHistory();
    }

    set hass(hass) {
      const previous = this._hass;
      this._hass = hass;
      if (!this._config) return;
      const entitiesChanged = !previous || previous.entities !== hass.entities || !this._entities;
      if (entitiesChanged) {
        this._entities = null;
      }
      const entities = this._resolveEntities();
      const changed =
        entitiesChanged ||
        previous.locale !== hass.locale ||
        Object.values(entities).some((entityId) => hass.states[entityId] !== this._states[entityId]);
      if (changed) this._render();
      this._loadHistory();
    }

    getCardSize() {
      return 8;
    }

    getGridOptions() {
      return { columns: 12, min_columns: 6 };
    }

    _resolveEntities() {
      if (this._entities) return this._entities;
      const hass = this._hass;
      this._deviceId = this._config.device_id || stickDevices(hass)[0];
      this._entities = this._deviceId ? stickEntities(hass, this._deviceId) : {};
      return this._entities;
    }

    _stateOf(key) {
      const entityId = this._entities?.[key];
      return entityId ? this._hass.states[entityId] : undefined;
    }

    _format(key) {
      const stateObj = this._stateOf(key);
      if (isMissing(stateObj)) return "—";
      return this._hass.formatEntityState ? this._hass.formatEntityState(stateObj) : stateObj.state;
    }

    _number(value, digits = 2) {
      const locale = this._hass?.locale?.language || this._hass?.language || navigator.language;
      return new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value);
    }

    async _loadHistory() {
      const entityId = this._entities?.rx_power;
      const hass = this._hass;
      if (!this._config.show_history || !entityId || !hass?.callWS) return;
      if (Date.now() - this._historyLoaded < HISTORY_REFRESH_MS) return;
      this._historyLoaded = Date.now();
      const end = new Date();
      const start = new Date(end.getTime() - HISTORY_HOURS * 3600 * 1000);
      try {
        const result = await hass.callWS({
          type: "history/history_during_period",
          start_time: start.toISOString(),
          end_time: end.toISOString(),
          entity_ids: [entityId],
          minimal_response: true,
          no_attributes: true,
          significant_changes_only: false,
        });
        const points = (result?.[entityId] || [])
          .map((row) => [historyTimestamp(row), Number(row.s ?? row.state)])
          .filter(([time, value]) => Number.isFinite(time) && Number.isFinite(value));
        this._history = downsample(points, HISTORY_POINTS);
      } catch (_err) {
        this._history = null;
      }
      this._render();
    }

    _render() {
      if (!this._config || !this._hass) return;
      const entities = this._resolveEntities();
      this._states = Object.fromEntries(
        Object.values(entities).map((entityId) => [entityId, this._hass.states[entityId]]),
      );
      const body = entities.rx_power ? this._renderBody() : this._renderMissing();
      this.shadowRoot.innerHTML = `<style>${STYLES}</style><ha-card>${body}</ha-card>`;
      this.shadowRoot.querySelectorAll("[data-entity]").forEach((element) => {
        element.addEventListener("click", () => this._moreInfo(element.dataset.entity));
      });
    }

    _renderMissing() {
      const message = this._config.device_id
        ? "This device has no XPON ONU Stick sensors."
        : "No XPON ONU Stick device found. Add the integration first.";
      return `<div class="empty">${escapeHtml(message)}</div>`;
    }

    _renderBody() {
      const { show_history, show_system, show_details } = this._config;
      return [
        this._renderHeader(),
        this._renderRx(show_history),
        `<div class="grid">${TILES.map(([key, label]) => this._renderTile(key, label)).join("")}</div>`,
        show_system ? this._renderSystem() : "",
        show_details ? this._renderDetails() : "",
      ].join("");
    }

    _renderHeader() {
      const device = this._hass.devices?.[this._deviceId];
      const nameState = this._stateOf("device_name");
      const title =
        this._config.title ||
        device?.name_by_user ||
        device?.name ||
        (isMissing(nameState) ? "XPON ONU Stick" : nameState.state);
      const registration = this._stateOf("onu_registration_status");
      const onuState = this._stateOf("onu_state");
      const unavailable = Object.values(this._states).every(isMissing);
      const badge = unavailable
        ? `<span class="badge tone-muted">Unavailable</span>`
        : `<button class="badge tone-${toneOf(registration)}" data-entity="${this._entities.onu_registration_status || ""}"
            title="${escapeHtml(registration?.attributes?.description || "")}">
            <span class="dot"></span>${escapeHtml(this._format("onu_registration_status"))}
            ${isMissing(onuState) ? "" : `<span class="code">${escapeHtml(onuState.state)}</span>`}
          </button>`;
      const subtitle = [
        ["firmware_version", "Firmware"],
        ["uptime", "Up"],
      ]
        .filter(([key]) => !isMissing(this._stateOf(key)))
        .map(([key, label]) => `${label} ${escapeHtml(this._format(key))}`)
        .join(" · ");
      return `
        <div class="header">
          <ha-icon icon="mdi:access-point-network"></ha-icon>
          <div class="heading">
            <div class="title">${escapeHtml(title)}</div>
            ${subtitle ? `<div class="subtitle">${subtitle}</div>` : ""}
          </div>
          ${badge}
        </div>`;
    }

    _renderRx(showHistory) {
      const rx = this._stateOf("rx_power");
      const status = this._stateOf("rx_power_status");
      const attrs = status?.attributes || {};
      const tone = toneOf(status);
      const [value, unit] = this._splitUnit(this._format("rx_power"));
      const reading = isMissing(rx) ? NaN : Number(rx.state);
      return `
        <button class="hero" data-entity="${this._entities.rx_power}">
          <div class="hero-top">
            <div>
              <div class="label">Rx power</div>
              <div class="value-xl">${escapeHtml(value)}<span class="unit">${escapeHtml(unit)}</span></div>
            </div>
            <div class="chip tone-${tone}" title="${escapeHtml(attrs.description || "")}">
              <span class="dot"></span>${escapeHtml(this._format("rx_power_status"))}
            </div>
          </div>
          ${this._renderRange(reading, attrs)}
          ${this._renderMargins(attrs)}
          ${showHistory ? this._renderSparkline(tone) : ""}
        </button>`;
    }

    _renderRange(reading, attrs) {
      const min = Number(attrs.minimum);
      const max = Number(attrs.maximum);
      if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return "";
      const margin = Math.min(Math.max(0, Number(attrs.warning_margin) || 0), (max - min) / 2);
      const pad = Math.max(3, (max - min) * 0.25);
      const low = min - pad;
      const span = max + pad - low;
      const position = (value) => ((Math.min(max + pad, Math.max(low, value)) - low) / span) * 100;
      const segments = [
        [low, min, "bad"],
        [min, min + margin, "warn"],
        [min + margin, max - margin, "ok"],
        [max - margin, max, "warn"],
        [max, max + pad, "bad"],
      ]
        .map(([from, to, tone]) => `<span class="tone-${tone}" style="width:${position(to) - position(from)}%"></span>`)
        .join("");
      const marker = Number.isFinite(reading)
        ? `<span class="marker" style="left:${position(reading)}%"></span>`
        : "";
      return `
        <div class="range">
          <div class="track">${segments}</div>
          ${marker}
          <span class="tick" style="left:${position(min)}%">${this._number(min, 1)}</span>
          <span class="tick" style="left:${position(max)}%">${this._number(max, 1)}</span>
        </div>`;
    }

    _renderMargins(attrs) {
      const lower = Number(attrs.lower_margin_db);
      const upper = Number(attrs.upper_margin_db);
      if (!Number.isFinite(lower) || !Number.isFinite(upper)) return "";
      let text;
      if (lower < 0) text = `${this._number(-lower)} dB below the minimum`;
      else if (upper < 0) text = `${this._number(-upper)} dB above the maximum`;
      else text = `${this._number(lower)} dB above the minimum · ${this._number(upper)} dB below the maximum`;
      return `<div class="caption">${text}</div>`;
    }

    _renderSparkline(tone) {
      const points = this._history;
      if (!points || points.length < 2) return "";
      const values = points.map(([, value]) => value);
      const lowest = Math.min(...values);
      const highest = Math.max(...values);
      // Keep at least 1 dB of scale so normal jitter doesn't look dramatic.
      const middle = (lowest + highest) / 2;
      const bottom = Math.min(lowest, middle - 0.5);
      const top = Math.max(highest, middle + 0.5);
      const start = points[0][0];
      const duration = points[points.length - 1][0] - start || 1;
      const path = points
        .map(([time, value], index) => {
          const x = ((time - start) / duration) * 300;
          const y = 38 - ((value - bottom) / (top - bottom)) * 36;
          return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join("");
      return `
        <svg class="spark tone-${tone}" viewBox="0 0 300 40" preserveAspectRatio="none" aria-hidden="true">
          <path class="area" d="${path}L300,40L0,40Z"></path>
          <path class="line" d="${path}"></path>
        </svg>
        <div class="caption">Last ${HISTORY_HOURS} h: ${this._number(lowest)} to ${this._number(highest)} dBm</div>`;
    }

    _renderTile(key, label) {
      const entityId = this._entities[key];
      if (!entityId) return "";
      const status = this._stateOf(`${key}_status`);
      return `
        <button class="tile" data-entity="${entityId}">
          <span class="label">${label}</span>
          <span class="value">${escapeHtml(this._format(key))}</span>
          <span class="status tone-${toneOf(status)}" title="${escapeHtml(status?.attributes?.description || "")}">
            <span class="dot"></span>${escapeHtml(this._format(`${key}_status`))}
          </span>
        </button>`;
    }

    _renderSystem() {
      const bar = (key, label) => {
        const stateObj = this._stateOf(key);
        if (!this._entities[key]) return "";
        const percent = isMissing(stateObj) ? 0 : Math.min(100, Math.max(0, Number(stateObj.state) || 0));
        const tone = percent >= 90 ? "bad" : percent >= 75 ? "warn" : "primary";
        return `
          <button class="meter" data-entity="${this._entities[key]}">
            <span class="meter-head"><span>${label}</span><b>${escapeHtml(this._format(key))}</b></span>
            <span class="bar tone-${tone}"><span style="width:${percent}%"></span></span>
          </button>`;
      };
      return `<div class="meters">${bar("cpu_usage", "CPU")}${bar("memory_usage", "Memory")}</div>`;
    }

    _renderDetails() {
      const rows = [
        ["onu_state", "ONU state"],
        ["onu_id", "ONU ID"],
        ["loid_status", "LOID status"],
        ["ip_address", "IP address"],
        ["subnet_mask", "Subnet mask"],
        ...(this._config.hide_mac ? [] : [["mac_address", "MAC address"]]),
      ];
      const items = rows
        .filter(([key]) => this._entities[key])
        .map(([key, label]) => {
          let value = this._format(key);
          if (key === "mac_address" && /^[0-9a-f]{12}$/i.test(value)) {
            value = value.match(/../g).join(":");
          }
          return `
            <button class="detail" data-entity="${this._entities[key]}">
              <span class="key">${label}</span>
              <span class="val">${escapeHtml(value)}</span>
            </button>`;
        })
        .join("");
      return `<div class="details">${items}</div>`;
    }

    _splitUnit(text) {
      const index = text.lastIndexOf(" ");
      return index > 0 ? [text.slice(0, index), text.slice(index + 1)] : [text, ""];
    }

    _moreInfo(entityId) {
      if (!entityId) return;
      this.dispatchEvent(
        new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }),
      );
    }
  }

  const SCHEMA = [
    { name: "device_id", selector: { device: { filter: { integration: DOMAIN } } } },
    { name: "title", selector: { text: {} } },
    {
      type: "grid",
      name: "",
      schema: [
        { name: "show_history", selector: { boolean: {} } },
        { name: "show_system", selector: { boolean: {} } },
        { name: "show_details", selector: { boolean: {} } },
        { name: "hide_mac", selector: { boolean: {} } },
      ],
    },
  ];
  const LABELS = {
    device_id: "ONU stick",
    title: "Title (optional)",
    show_history: "Show 24-hour Rx history",
    show_system: "Show CPU and memory",
    show_details: "Show ONU and network details",
    hide_mac: "Hide MAC address",
  };

  class XponOnuStickCardEditor extends HTMLElement {
    setConfig(config) {
      this._config = config;
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      this._render();
    }

    _render() {
      if (!this._config || !this._hass) return;
      if (!this._form) {
        this._form = document.createElement("ha-form");
        this._form.computeLabel = (schema) => LABELS[schema.name] ?? schema.name;
        this._form.addEventListener("value-changed", (event) => this._changed(event.detail.value));
        this.appendChild(this._form);
      }
      this._form.hass = this._hass;
      this._form.schema = SCHEMA;
      this._form.data = { ...DEFAULTS, ...this._config };
    }

    _changed(value) {
      const config = { ...this._config, ...value };
      // Keep the YAML short: drop defaults and empty optional fields.
      for (const [key, fallback] of Object.entries(DEFAULTS)) {
        if (config[key] === fallback) delete config[key];
      }
      for (const key of ["device_id", "title"]) {
        if (!config[key]) delete config[key];
      }
      this._config = config;
      this.dispatchEvent(
        new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }),
      );
    }
  }

  const STYLES = `
    :host { display: block; }
    ha-card {
      container-type: inline-size;
      display: flex;
      flex-direction: column;
      gap: 16px;
      padding: 16px;
      height: 100%;
      box-sizing: border-box;
    }
    button {
      all: unset;
      box-sizing: border-box;
      cursor: pointer;
      min-width: 0;
    }
    button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; border-radius: 8px; }
    .tone-ok { --tone: var(--success-color, #43a047); }
    .tone-warn { --tone: var(--warning-color, #ffa600); }
    .tone-bad { --tone: var(--error-color, #db4437); }
    .tone-muted { --tone: var(--secondary-text-color, #727272); }
    .tone-primary { --tone: var(--primary-color, #03a9f4); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--tone); flex: none; }
    .label, .caption, .subtitle, .key, .meter-head { color: var(--secondary-text-color); }
    .label { font-size: 0.8125rem; }
    .caption { font-size: 0.75rem; }
    .empty { color: var(--secondary-text-color); }

    .header { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; min-width: 0; }
    .header ha-icon { color: var(--state-icon-color, var(--primary-color)); --mdc-icon-size: 28px; flex: none; }
    .heading { min-width: 0; flex: 1 1 140px; }
    .title { font-size: 1.125rem; font-weight: 500; line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .subtitle { font-size: 0.8125rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 0.8125rem;
      font-weight: 500;
      color: var(--tone);
      background: color-mix(in srgb, var(--tone) 14%, transparent);
      white-space: nowrap;
      flex: none;
      margin-left: auto;
    }
    .code {
      font-size: 0.6875rem;
      padding: 1px 6px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--tone) 22%, transparent);
    }

    .hero { display: flex; flex-direction: column; gap: 6px; width: 100%; }
    .hero-top { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; }
    .value-xl { font-size: 2rem; font-weight: 500; line-height: 1.15; font-variant-numeric: tabular-nums; }
    .unit { font-size: 1rem; font-weight: 400; color: var(--secondary-text-color); margin-left: 4px; }
    .chip { display: inline-flex; align-items: center; gap: 6px; color: var(--tone); font-size: 0.875rem; font-weight: 500; padding-bottom: 4px; }
    .range { position: relative; margin: 8px 0 18px; }
    .track { display: flex; height: 8px; border-radius: 4px; overflow: hidden; }
    .track > span { height: 100%; background: color-mix(in srgb, var(--tone) 70%, transparent); }
    .marker {
      position: absolute;
      top: -4px;
      width: 4px;
      height: 16px;
      border-radius: 2px;
      background: var(--primary-text-color);
      box-shadow: 0 0 0 2px var(--card-background-color, var(--ha-card-background, #fff));
      transform: translateX(-50%);
    }
    .tick {
      position: absolute;
      top: 12px;
      transform: translateX(-50%);
      font-size: 0.6875rem;
      color: var(--secondary-text-color);
      font-variant-numeric: tabular-nums;
    }
    .spark { width: 100%; height: 32px; display: block; margin-top: 4px; }
    .spark .area { fill: color-mix(in srgb, var(--tone) 14%, transparent); }
    .spark .line { fill: none; stroke: var(--tone); stroke-width: 2; vector-effect: non-scaling-stroke; stroke-linejoin: round; }

    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .tile {
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding: 10px 12px;
      border: 1px solid var(--divider-color);
      border-radius: 12px;
    }
    .tile .value { font-size: 1.125rem; font-weight: 500; font-variant-numeric: tabular-nums; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .status { display: flex; align-items: center; gap: 6px; font-size: 0.8125rem; color: var(--tone); min-width: 0; }

    .meters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .meter { display: flex; flex-direction: column; gap: 6px; }
    .meter-head { display: flex; justify-content: space-between; font-size: 0.8125rem; }
    .meter-head b { color: var(--primary-text-color); font-weight: 500; font-variant-numeric: tabular-nums; }
    .bar { display: block; height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; }
    .bar > span { display: block; height: 100%; border-radius: 3px; background: var(--tone); }

    .details { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px 16px; }
    .detail { display: flex; flex-direction: column; gap: 2px; }
    .key { font-size: 0.75rem; }
    .val { font-size: 0.9375rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-variant-numeric: tabular-nums; }

    @container (max-width: 420px) {
      .details { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @container (max-width: 300px) {
      .grid, .meters, .details { grid-template-columns: minmax(0, 1fr); }
      .hero-top { flex-direction: column; align-items: flex-start; }
    }
  `;

  if (!customElements.get(CARD_TYPE)) customElements.define(CARD_TYPE, XponOnuStickCard);
  if (!customElements.get(`${CARD_TYPE}-editor`)) {
    customElements.define(`${CARD_TYPE}-editor`, XponOnuStickCardEditor);
  }
  window.customCards = window.customCards || [];
  if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
    window.customCards.push({
      type: CARD_TYPE,
      name: "XPON ONU Stick",
      description: "Optical levels, connection state, and device details of an ONU stick in one card.",
      preview: true,
      documentationURL: "https://github.com/vineetchoudhary/ha-xpon-onu-stick/blob/master/docs/dashboard.md",
    });
  }
})();
