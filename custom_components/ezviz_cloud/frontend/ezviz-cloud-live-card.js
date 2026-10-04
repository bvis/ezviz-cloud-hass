// EZVIZ Cloud live card. Served and registered by the ezviz_cloud integration.
//
//   type: custom:ezviz-cloud-live-card
//   serial: ABC123456        # device serial
//   code: ABCDEF             # verification code on the device label
//   channel: 1               # optional
//   title: Front door        # optional
//   max_seconds: 60          # optional, stops the stream to save battery
//
// The stream is played by EZVIZ's own web player (ezuikit-js), which wakes
// battery cameras and decrypts encrypted video in the browser. The player
// looks up its DOM with document.getElementById, which cannot reach inside
// Home Assistant's shadow roots, so it runs in an iframe srcdoc.

const EZUIKIT = "https://cdn.jsdelivr.net/npm/ezuikit-js@9.0.23/ezuikit.js";

class EzvizCloudLiveCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        { name: "serial", required: true, selector: { text: {} } },
        { name: "code", required: true, selector: { text: { type: "password" } } },
        { name: "channel", selector: { number: { min: 1, max: 64, mode: "box" } } },
        { name: "title", selector: { text: {} } },
        { name: "max_seconds", selector: { number: { min: 10, max: 600, unit_of_measurement: "s", mode: "box" } } },
      ],
      computeLabel: (s) =>
        ({
          serial: "Device serial",
          code: "Verification code",
          channel: "Channel",
          title: "Title",
          max_seconds: "Stop after",
        })[s.name],
    };
  }

  static getStubConfig() {
    return { serial: "", code: "" };
  }

  setConfig(config) {
    if (!config.serial) throw new Error("serial is required");
    if (!config.code) throw new Error("code is required");
    this._config = { channel: 1, max_seconds: 60, ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  getCardSize() {
    return 5;
  }

  getGridOptions() {
    return { columns: 12, rows: 5, min_rows: 4 };
  }

  disconnectedCallback() {
    this._stop();
  }

  _render() {
    if (!this._card) {
      this._card = document.createElement("ha-card");
      this.appendChild(this._card);
    }
    this._card.header = this._config.title || "";
    this._card.innerHTML = `
      <div style="position:relative;aspect-ratio:16/9;background:#000;display:flex;align-items:center;justify-content:center;color:#fff">
        <button style="font:inherit;padding:10px 18px;border:0;border-radius:18px;cursor:pointer;background:var(--primary-color);color:var(--text-primary-color,#fff)">Watch live</button>
      </div>`;
    this._box = this._card.firstElementChild;
    this._box.querySelector("button").addEventListener("click", () => this._play());
  }

  async _play() {
    this._box.textContent = "Connecting…";
    let auth;
    try {
      auth = await this._hass.callWS({ type: "ezviz_cloud/token" });
    } catch (err) {
      this._box.textContent = `EZVIZ Cloud: ${err.message || err.code || err}`;
      return;
    }
    const { serial, code, channel, max_seconds } = this._config;
    const opts = JSON.stringify({
      accessToken: auth.access_token,
      url: `ezopen://${code}@open.ezviz.com/${serial}/${channel}.live`,
      env: { domain: auth.domain },
    }).replace(/</g, "\\u003c");
    const iframe = document.createElement("iframe");
    iframe.style.cssText = "border:0;width:100%;height:100%;position:absolute;inset:0";
    iframe.setAttribute("allow", "autoplay; fullscreen");
    iframe.srcdoc = `<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}#v,#v canvas{width:100%!important;height:100%!important}</style>
<script src="${EZUIKIT}"></script></head><body><div id="v"></div><script>
const o=${opts};
new EZUIKit.EZUIKitPlayer({id:'v',width:innerWidth,height:innerHeight,...o});
</script></body></html>`;
    this._box.textContent = "";
    this._box.appendChild(iframe);
    this._timer = setTimeout(() => this._stop(), max_seconds * 1000);
  }

  _stop() {
    clearTimeout(this._timer);
    if (this._config && this._box?.querySelector("iframe")) this._render();
  }
}

// The integration loads this file from the page head, so it often runs before
// the frontend swaps window.customElements for its scoped-registry polyfill.
// The polyfill does not carry over definitions made on the native registry
// ("Custom element doesn't exist"), and when the frontend comes from the
// network the swap lands well after this script. So define on the current
// registry now and again on any registry that replaces it while the page boots;
// the frontend re-renders the card as soon as the definition shows up.
const define = () => {
  if (!window.customElements.get("ezviz-cloud-live-card")) {
    window.customElements.define("ezviz-cloud-live-card", EzvizCloudLiveCard);
  }
};
define();
const watchRegistry = setInterval(define, 100);
setTimeout(() => clearInterval(watchRegistry), 30000);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ezviz-cloud-live-card",
  name: "EZVIZ Cloud live",
  description: "Live view of an EZVIZ camera through the EZVIZ Open Platform",
  documentationURL: "https://github.com/bvis/ezviz-cloud-hass",
});
