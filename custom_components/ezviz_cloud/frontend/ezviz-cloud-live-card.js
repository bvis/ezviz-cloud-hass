// EZVIZ Cloud live card. Served and registered by the ezviz_cloud integration.
//
//   type: custom:ezviz-cloud-live-card
//   serial: ABC123456        # device serial (the editor lists the account's cameras)
//   code: ABCDEF             # optional: verification code; better stored in the
//                            # integration options (Configure), out of the dashboard
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
  // Async: the frontend awaits it, so the serial field can list the account's
  // cameras. Falls back to a text field when the list can't be fetched.
  static async getConfigForm() {
    let serial = { text: {} };
    try {
      const devices = await document
        .querySelector("home-assistant")
        .hass.callWS({ type: "ezviz_cloud/devices" });
      if (devices.length) {
        serial = {
          select: {
            mode: "dropdown",
            custom_value: true,
            options: devices.map((d) => ({
              value: d.serial,
              label: `${d.name} (${d.serial})${d.encrypted && !d.has_code ? " · no code stored" : ""}`,
            })),
          },
        };
      }
    } catch (err) {
      // Keep the text field.
    }
    return {
      schema: [
        { name: "serial", required: true, selector: serial },
        { name: "code", selector: { text: { type: "password" } } },
        { name: "channel", selector: { number: { min: 1, max: 64, mode: "box" } } },
        { name: "title", selector: { text: {} } },
        { name: "max_seconds", selector: { number: { min: 10, max: 600, unit_of_measurement: "s", mode: "box" } } },
      ],
      computeLabel: (s) =>
        ({
          serial: "Camera",
          code: "Verification code",
          channel: "Channel",
          title: "Title",
          max_seconds: "Stop after",
        })[s.name],
      computeHelper: (s) =>
        s.name === "code"
          ? "Leave empty to use the code stored in the integration (Settings → Devices & services → EZVIZ Cloud → Configure)."
          : undefined,
    };
  }

  static getStubConfig() {
    return { serial: "" };
  }

  setConfig(config) {
    if (!config.serial) throw new Error("serial is required");
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
    // No fixed rows: the card's height follows the 16:9 video plus its title.
    return { columns: 12, min_columns: 6 };
  }

  disconnectedCallback() {
    this._stop();
  }

  _render(message = "") {
    if (!this._card) {
      this._card = document.createElement("ha-card");
      this._card.style.overflow = "hidden";
      this.appendChild(this._card);
    }
    this._card.header = this._config.title || "";
    this._card.innerHTML = `
      <div style="position:relative;aspect-ratio:16/9;background:#000;display:flex;flex-direction:column;gap:12px;align-items:center;justify-content:center;color:#fff;text-align:center">
        <div style="padding:0 16px"></div>
        <button style="font:inherit;padding:10px 18px;border:0;border-radius:18px;cursor:pointer;background:var(--primary-color);color:var(--text-primary-color,#fff)">Watch live</button>
      </div>`;
    this._box = this._card.firstElementChild;
    this._box.firstElementChild.textContent = message;
    this._box.querySelector("button").addEventListener("click", () => this._play());
  }

  // Loading overlay with a percentage, shown until the first frame. The player
  // reports stages (decoder downloaded, video info...), not bytes, so each
  // stage sets a floor and the number creeps towards the next one meanwhile.
  _showProgress(percent, label) {
    if (!this._overlay) {
      this._overlay = document.createElement("div");
      this._overlay.style.cssText =
        "position:absolute;inset:0;display:flex;flex-direction:column;gap:10px;align-items:center;justify-content:center;background:#000;color:#fff;pointer-events:none";
      this._overlay.innerHTML = `<div></div>
        <div style="width:50%;height:4px;border-radius:2px;background:rgba(255,255,255,.25)"><div style="height:100%;width:0;border-radius:2px;background:var(--primary-color);transition:width .2s"></div></div>`;
      this._box.appendChild(this._overlay);
      this._progress = { value: 0, cap: 0 };
      this._creep = setInterval(() => {
        const p = this._progress;
        p.value += (p.cap - p.value) * 0.02;
        this._paintProgress();
      }, 200);
    }
    const p = this._progress;
    p.value = Math.max(p.value, percent);
    p.cap = Math.max(p.cap, percent + 20 > 99 ? 99 : percent + 20);
    if (label) p.label = label;
    this._paintProgress();
  }

  _paintProgress() {
    const p = this._progress;
    this._overlay.firstElementChild.textContent = `${p.label} ${Math.floor(p.value)}%`;
    this._overlay.lastElementChild.firstElementChild.style.width = `${p.value}%`;
  }

  _hideProgress() {
    clearInterval(this._creep);
    this._overlay?.remove();
    this._overlay = null;
  }

  async _play() {
    this._box.textContent = "";
    this._showProgress(2, "Connecting…");
    let auth;
    try {
      auth = await this._hass.callWS({ type: "ezviz_cloud/token", serial: this._config.serial });
    } catch (err) {
      this._fail(`EZVIZ Cloud: ${err.message || err.code || err}`);
      return;
    }
    this._showProgress(10, "Loading player…");
    const { serial, channel, max_seconds } = this._config;
    // Cameras with encryption off play without a code.
    const code = this._config.code || auth.code;
    const opts = JSON.stringify({
      accessToken: auth.access_token,
      url: `ezopen://${code ? `${code}@` : ""}open.ezviz.com/${serial}/${channel}.live`,
      env: { domain: auth.domain },
      language: "en",
    }).replace(/</g, "\\u003c");
    const iframe = document.createElement("iframe");
    iframe.style.cssText = "border:0;width:100%;height:100%;position:absolute;inset:0";
    iframe.setAttribute("allow", "autoplay; fullscreen");
    // The player runs inside the iframe; it reports back with postMessage.
    iframe.srcdoc = `<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}#v,#v canvas{width:100%!important;height:100%!important}</style>
<script>const send=(m)=>parent.postMessage({ezvizCloud:m},"*");</script>
<script src="${EZUIKIT}" onerror="send({error:'Could not load the EZVIZ player'})"></script></head><body><div id="v"></div><script>
if(window.EZUIKit){
const o=${opts};
const E=EZUIKit.EZUIKitPlayer.EVENTS;
send({stage:25,label:"Loading decoder…"});
const player=new EZUIKit.EZUIKitPlayer({id:'v',width:innerWidth,height:innerHeight,...o,
  handleError:(e)=>send({error:(e&&(e.msg||e.data&&e.data.msg||e.type))||"Player error"})});
player.eventEmitter.on(E.decoderLoaded,()=>send({stage:60,label:"Waking camera…"}));
player.eventEmitter.on(E.videoInfo,()=>send({stage:90,label:"Starting video…"}));
player.eventEmitter.on(E.firstFrameDisplay,()=>send({ready:true}));
// Stream failures (camera did not answer, bad code...) only arrive as messages.
player.eventEmitter.on('message',(msg,type)=>{if(type==='fetchError')send({error:msg||'Could not start the video'})});
}
</script></body></html>`;
    this._onMessage = (ev) => {
      const m = ev.source === iframe.contentWindow && ev.data?.ezvizCloud;
      if (!m) return;
      if (m.error) this._fail(m.error);
      else if (m.ready) this._hideProgress();
      else this._showProgress(m.stage, m.label);
    };
    window.addEventListener("message", this._onMessage);
    this._box.insertBefore(iframe, this._overlay);
    this._timer = setTimeout(
      () => (this._overlay ? this._fail(`No video from the camera after ${max_seconds} s`) : this._stop()),
      max_seconds * 1000,
    );
  }

  _fail(message) {
    this._stop();
    this._render(message);
  }

  _stop() {
    clearTimeout(this._timer);
    window.removeEventListener("message", this._onMessage);
    this._hideProgress();
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
