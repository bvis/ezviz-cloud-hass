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

// Card texts by Home Assistant language. Kept as a plain JSON literal between
// the markers so the repo tests can check every language has every key.
// prettier-ignore
const STRINGS = /* translations */ {
  "en": {
    "watch_live": "Watch live",
    "connecting": "Connecting…",
    "loading_player": "Loading player…",
    "loading_decoder": "Loading decoder…",
    "waking_camera": "Waking camera…",
    "starting_video": "Starting video…",
    "no_video": "No video from the camera after {s} s",
    "player_load_failed": "Couldn't load the EZVIZ player",
    "could_not_start": "Couldn't start the video: {msg}",
    "player_error": "Player error",
    "label_serial": "Camera",
    "label_code": "Verification code",
    "label_channel": "Channel",
    "label_title": "Title",
    "label_max_seconds": "Stop after",
    "code_helper": "Leave empty to use the code stored in the integration (Settings → Devices & services → EZVIZ Cloud → Configure).",
    "no_code_stored": "no code stored"
  },
  "es": {
    "watch_live": "Ver en directo",
    "connecting": "Conectando…",
    "loading_player": "Cargando reproductor…",
    "loading_decoder": "Cargando decodificador…",
    "waking_camera": "Despertando la cámara…",
    "starting_video": "Iniciando vídeo…",
    "no_video": "La cámara no ha enviado vídeo en {s} s",
    "player_load_failed": "No se ha podido cargar el reproductor de EZVIZ",
    "could_not_start": "No se ha podido iniciar el vídeo: {msg}",
    "player_error": "Error del reproductor",
    "label_serial": "Cámara",
    "label_code": "Código de verificación",
    "label_channel": "Canal",
    "label_title": "Título",
    "label_max_seconds": "Detener tras",
    "code_helper": "Déjalo vacío para usar el código guardado en la integración (Ajustes → Dispositivos y servicios → EZVIZ Cloud → Configurar).",
    "no_code_stored": "sin código guardado"
  },
  "ca": {
    "watch_live": "Veure en directe",
    "connecting": "Connectant…",
    "loading_player": "Carregant el reproductor…",
    "loading_decoder": "Carregant el descodificador…",
    "waking_camera": "Despertant la càmera…",
    "starting_video": "Iniciant el vídeo…",
    "no_video": "La càmera no ha enviat vídeo en {s} s",
    "player_load_failed": "No s'ha pogut carregar el reproductor d'EZVIZ",
    "could_not_start": "No s'ha pogut iniciar el vídeo: {msg}",
    "player_error": "Error del reproductor",
    "label_serial": "Càmera",
    "label_code": "Codi de verificació",
    "label_channel": "Canal",
    "label_title": "Títol",
    "label_max_seconds": "Atura després de",
    "code_helper": "Deixa-ho buit per fer servir el codi desat a la integració (Configuració → Dispositius i serveis → EZVIZ Cloud → Configura).",
    "no_code_stored": "sense codi desat"
  },
  "fr": {
    "watch_live": "Voir en direct",
    "connecting": "Connexion…",
    "loading_player": "Chargement du lecteur…",
    "loading_decoder": "Chargement du décodeur…",
    "waking_camera": "Réveil de la caméra…",
    "starting_video": "Démarrage de la vidéo…",
    "no_video": "Aucune vidéo de la caméra après {s} s",
    "player_load_failed": "Impossible de charger le lecteur EZVIZ",
    "could_not_start": "Impossible de démarrer la vidéo : {msg}",
    "player_error": "Erreur du lecteur",
    "label_serial": "Caméra",
    "label_code": "Code de vérification",
    "label_channel": "Canal",
    "label_title": "Titre",
    "label_max_seconds": "Arrêter après",
    "code_helper": "Laissez vide pour utiliser le code enregistré dans l'intégration (Paramètres → Appareils et services → EZVIZ Cloud → Configurer).",
    "no_code_stored": "aucun code enregistré"
  },
  "de": {
    "watch_live": "Live ansehen",
    "connecting": "Verbinde…",
    "loading_player": "Player wird geladen…",
    "loading_decoder": "Decoder wird geladen…",
    "waking_camera": "Kamera wird geweckt…",
    "starting_video": "Video wird gestartet…",
    "no_video": "Kein Video von der Kamera nach {s} s",
    "player_load_failed": "EZVIZ-Player konnte nicht geladen werden",
    "could_not_start": "Video konnte nicht gestartet werden: {msg}",
    "player_error": "Player-Fehler",
    "label_serial": "Kamera",
    "label_code": "Verifizierungscode",
    "label_channel": "Kanal",
    "label_title": "Titel",
    "label_max_seconds": "Stoppen nach",
    "code_helper": "Leer lassen, um den in der Integration gespeicherten Code zu verwenden (Einstellungen → Geräte & Dienste → EZVIZ Cloud → Konfigurieren).",
    "no_code_stored": "kein Code gespeichert"
  },
  "it": {
    "watch_live": "Guarda dal vivo",
    "connecting": "Connessione…",
    "loading_player": "Caricamento del player…",
    "loading_decoder": "Caricamento del decoder…",
    "waking_camera": "Risveglio della telecamera…",
    "starting_video": "Avvio del video…",
    "no_video": "Nessun video dalla telecamera dopo {s} s",
    "player_load_failed": "Impossibile caricare il player EZVIZ",
    "could_not_start": "Impossibile avviare il video: {msg}",
    "player_error": "Errore del player",
    "label_serial": "Telecamera",
    "label_code": "Codice di verifica",
    "label_channel": "Canale",
    "label_title": "Titolo",
    "label_max_seconds": "Ferma dopo",
    "code_helper": "Lascia vuoto per usare il codice salvato nell'integrazione (Impostazioni → Dispositivi e servizi → EZVIZ Cloud → Configura).",
    "no_code_stored": "nessun codice salvato"
  },
  "pt": {
    "watch_live": "Ver em direto",
    "connecting": "A ligar…",
    "loading_player": "A carregar o leitor…",
    "loading_decoder": "A carregar o descodificador…",
    "waking_camera": "A acordar a câmara…",
    "starting_video": "A iniciar o vídeo…",
    "no_video": "Sem vídeo da câmara após {s} s",
    "player_load_failed": "Não foi possível carregar o leitor EZVIZ",
    "could_not_start": "Não foi possível iniciar o vídeo: {msg}",
    "player_error": "Erro do leitor",
    "label_serial": "Câmara",
    "label_code": "Código de verificação",
    "label_channel": "Canal",
    "label_title": "Título",
    "label_max_seconds": "Parar após",
    "code_helper": "Deixe vazio para usar o código guardado na integração (Definições → Dispositivos e serviços → EZVIZ Cloud → Configurar).",
    "no_code_stored": "sem código guardado"
  },
  "pt-BR": {
    "watch_live": "Ver ao vivo",
    "connecting": "Conectando…",
    "loading_player": "Carregando o player…",
    "loading_decoder": "Carregando o decodificador…",
    "waking_camera": "Acordando a câmera…",
    "starting_video": "Iniciando o vídeo…",
    "no_video": "Nenhum vídeo da câmera após {s} s",
    "player_load_failed": "Não foi possível carregar o player EZVIZ",
    "could_not_start": "Não foi possível iniciar o vídeo: {msg}",
    "player_error": "Erro do player",
    "label_serial": "Câmera",
    "label_code": "Código de verificação",
    "label_channel": "Canal",
    "label_title": "Título",
    "label_max_seconds": "Parar após",
    "code_helper": "Deixe vazio para usar o código salvo na integração (Configurações → Dispositivos e serviços → EZVIZ Cloud → Configurar).",
    "no_code_stored": "sem código salvo"
  },
  "nl": {
    "watch_live": "Live bekijken",
    "connecting": "Verbinden…",
    "loading_player": "Speler laden…",
    "loading_decoder": "Decoder laden…",
    "waking_camera": "Camera wordt gewekt…",
    "starting_video": "Video starten…",
    "no_video": "Geen video van de camera na {s} s",
    "player_load_failed": "Kan de EZVIZ-speler niet laden",
    "could_not_start": "Kan de video niet starten: {msg}",
    "player_error": "Spelerfout",
    "label_serial": "Camera",
    "label_code": "Verificatiecode",
    "label_channel": "Kanaal",
    "label_title": "Titel",
    "label_max_seconds": "Stoppen na",
    "code_helper": "Laat leeg om de code te gebruiken die in de integratie is opgeslagen (Instellingen → Apparaten & diensten → EZVIZ Cloud → Configureren).",
    "no_code_stored": "geen code opgeslagen"
  }
} /* end translations */;

// The user's language: exact tag (pt-BR), then its base (pt), then English.
const pickLang = (hass) => {
  const tag = hass?.locale?.language || hass?.language || "en";
  return STRINGS[tag] ? tag : STRINGS[tag.split("-")[0]] ? tag.split("-")[0] : "en";
};
const t = (lang, key, vars = {}) =>
  STRINGS[lang][key].replace(/\{(\w+)\}/g, (_, k) => vars[k]);

class EzvizCloudLiveCard extends HTMLElement {
  // Async: the frontend awaits it, so the serial field can list the account's
  // cameras. Falls back to a text field when the list can't be fetched.
  static async getConfigForm() {
    const hass = document.querySelector("home-assistant")?.hass;
    const lang = pickLang(hass);
    let serial = { text: {} };
    try {
      const devices = await hass.callWS({ type: "ezviz_cloud/devices" });
      if (devices.length) {
        serial = {
          select: {
            mode: "dropdown",
            custom_value: true,
            options: devices.map((d) => ({
              value: d.serial,
              label: `${d.name} (${d.serial})${d.encrypted && !d.has_code ? ` · ${t(lang, "no_code_stored")}` : ""}`,
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
      computeLabel: (s) => t(lang, `label_${s.name}`),
      computeHelper: (s) => (s.name === "code" ? t(lang, "code_helper") : undefined),
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
    // setConfig renders before hass arrives; redraw once the language is known,
    // unless a stream is on screen.
    const lang = pickLang(hass);
    if (lang !== this._lang && this._config && !this._overlay && !this._box?.querySelector("iframe")) {
      this._render(this._message);
    }
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
    this._lang = pickLang(this._hass);
    this._message = message;
    if (!this._card) {
      this._card = document.createElement("ha-card");
      this._card.style.overflow = "hidden";
      this.appendChild(this._card);
    }
    this._card.header = this._config.title || "";
    this._card.innerHTML = `
      <div style="position:relative;aspect-ratio:16/9;background:#000;display:flex;flex-direction:column;gap:12px;align-items:center;justify-content:center;color:#fff;text-align:center">
        <div style="padding:0 16px"></div>
        <button style="font:inherit;padding:10px 18px;border:0;border-radius:18px;cursor:pointer;background:var(--primary-color);color:var(--text-primary-color,#fff)"></button>
      </div>`;
    this._box = this._card.firstElementChild;
    this._box.firstElementChild.textContent = message;
    this._box.querySelector("button").textContent = t(this._lang, "watch_live");
    this._box.querySelector("button").addEventListener("click", () => this._play());
  }

  // Loading overlay with a percentage, shown until the first frame. The player
  // reports stages (decoder downloaded, video info...), not bytes, so each
  // stage sets a floor and the number creeps towards the next one meanwhile.
  _showProgress(percent, key) {
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
    if (key) p.label = t(this._lang, key);
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
    this._showProgress(2, "connecting");
    let auth;
    try {
      auth = await this._hass.callWS({ type: "ezviz_cloud/token", serial: this._config.serial });
    } catch (err) {
      this._fail(`EZVIZ Cloud: ${err.message || err.code || err}`);
      return;
    }
    this._showProgress(10, "loading_player");
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
<script src="${EZUIKIT}" onerror="send({errorKey:'player_load_failed'})"></script></head><body><div id="v"></div><script>
if(window.EZUIKit){
const o=${opts};
const E=EZUIKit.EZUIKitPlayer.EVENTS;
send({stage:25,key:"loading_decoder"});
const player=new EZUIKit.EZUIKitPlayer({id:'v',width:innerWidth,height:innerHeight,...o,
  handleError:(e)=>send({error:e&&(e.msg||e.data&&e.data.msg||e.type)})});
player.eventEmitter.on(E.decoderLoaded,()=>send({stage:60,key:"waking_camera"}));
player.eventEmitter.on(E.videoInfo,()=>send({stage:90,key:"starting_video"}));
player.eventEmitter.on(E.firstFrameDisplay,()=>send({ready:true}));
// Stream failures (camera did not answer, bad code...) only arrive as messages.
player.eventEmitter.on('message',(msg,type)=>{if(type==='fetchError')send({error:msg})});
}
</script></body></html>`;
    this._onMessage = (ev) => {
      const m = ev.source === iframe.contentWindow && ev.data?.ezvizCloud;
      if (!m) return;
      // The player's own messages exist only in English and Chinese.
      if (m.errorKey) this._fail(t(this._lang, m.errorKey));
      else if ("error" in m) this._fail(t(this._lang, "could_not_start", { msg: m.error || t(this._lang, "player_error") }));
      else if (m.ready) this._hideProgress();
      else this._showProgress(m.stage, m.key);
    };
    window.addEventListener("message", this._onMessage);
    this._box.insertBefore(iframe, this._overlay);
    this._timer = setTimeout(
      () => (this._overlay ? this._fail(t(this._lang, "no_video", { s: max_seconds })) : this._stop()),
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
