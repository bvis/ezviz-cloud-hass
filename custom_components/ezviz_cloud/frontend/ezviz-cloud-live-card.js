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
    "no_code_stored": "no code stored",
    "err_network": "The camera didn't answer: its connection is weak. Check its Wi-Fi and try again.",
    "err_offline": "The camera isn't connected to EZVIZ.",
    "err_token": "The EZVIZ session expired. Try again.",
    "err_viewers": "Too many people are watching this camera at once.",
    "err_permission": "This account isn't allowed to view the camera.",
    "err_device": "The camera reported an error. Try again.",
    "err_service": "EZVIZ returned an error. Try again in a while.",
    "recording": "● Recording",
    "recording_failed": "Couldn't save the recording",
    "stop": "Stop",
    "record": "● Record",
    "stop_recording": "■ Stop recording"
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
    "no_code_stored": "sin código guardado",
    "err_network": "La cámara no ha respondido: su conexión es débil. Comprueba su wifi y vuelve a intentarlo.",
    "err_offline": "La cámara no está conectada a EZVIZ.",
    "err_token": "La sesión con EZVIZ ha caducado. Vuelve a intentarlo.",
    "err_viewers": "Hay demasiadas personas viendo la cámara a la vez.",
    "err_permission": "Esta cuenta no tiene permiso para ver la cámara.",
    "err_device": "La cámara ha dado un error. Vuelve a intentarlo.",
    "err_service": "EZVIZ ha dado un error. Vuelve a intentarlo en un rato.",
    "recording": "● Grabando",
    "recording_failed": "No se ha podido guardar la grabación",
    "stop": "Detener",
    "record": "● Grabar",
    "stop_recording": "■ Dejar de grabar"
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
    "no_code_stored": "sense codi desat",
    "err_network": "La càmera no ha respost: la seva connexió és feble. Comprova'n el wifi i torna-ho a provar.",
    "err_offline": "La càmera no està connectada a EZVIZ.",
    "err_token": "La sessió amb EZVIZ ha caducat. Torna-ho a provar.",
    "err_viewers": "Hi ha massa gent mirant la càmera alhora.",
    "err_permission": "Aquest compte no té permís per veure la càmera.",
    "err_device": "La càmera ha donat un error. Torna-ho a provar.",
    "err_service": "EZVIZ ha donat un error. Torna-ho a provar d'aquí a una estona.",
    "recording": "● Gravant",
    "recording_failed": "No s'ha pogut desar l'enregistrament",
    "stop": "Atura",
    "record": "● Grava",
    "stop_recording": "■ Deixa de gravar"
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
    "no_code_stored": "aucun code enregistré",
    "err_network": "La caméra n'a pas répondu : sa connexion est faible. Vérifiez son Wi-Fi et réessayez.",
    "err_offline": "La caméra n'est pas connectée à EZVIZ.",
    "err_token": "La session EZVIZ a expiré. Réessayez.",
    "err_viewers": "Trop de personnes regardent cette caméra en même temps.",
    "err_permission": "Ce compte n'est pas autorisé à voir la caméra.",
    "err_device": "La caméra a signalé une erreur. Réessayez.",
    "err_service": "EZVIZ a renvoyé une erreur. Réessayez dans un moment.",
    "recording": "● Enregistrement",
    "recording_failed": "Impossible d'enregistrer la vidéo",
    "stop": "Arrêter",
    "record": "● Enregistrer",
    "stop_recording": "■ Arrêter l'enregistrement"
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
    "no_code_stored": "kein Code gespeichert",
    "err_network": "Die Kamera hat nicht geantwortet: Ihre Verbindung ist schwach. Prüfe ihr WLAN und versuche es erneut.",
    "err_offline": "Die Kamera ist nicht mit EZVIZ verbunden.",
    "err_token": "Die EZVIZ-Sitzung ist abgelaufen. Versuche es erneut.",
    "err_viewers": "Zu viele Personen sehen sich diese Kamera gleichzeitig an.",
    "err_permission": "Dieses Konto darf die Kamera nicht ansehen.",
    "err_device": "Die Kamera hat einen Fehler gemeldet. Versuche es erneut.",
    "err_service": "EZVIZ hat einen Fehler zurückgegeben. Versuche es später erneut.",
    "recording": "● Aufnahme",
    "recording_failed": "Aufnahme konnte nicht gespeichert werden",
    "stop": "Stoppen",
    "record": "● Aufnehmen",
    "stop_recording": "■ Aufnahme beenden"
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
    "no_code_stored": "nessun codice salvato",
    "err_network": "La telecamera non ha risposto: la sua connessione è debole. Controlla il Wi-Fi e riprova.",
    "err_offline": "La telecamera non è connessa a EZVIZ.",
    "err_token": "La sessione EZVIZ è scaduta. Riprova.",
    "err_viewers": "Troppe persone stanno guardando questa telecamera contemporaneamente.",
    "err_permission": "Questo account non ha il permesso di vedere la telecamera.",
    "err_device": "La telecamera ha segnalato un errore. Riprova.",
    "err_service": "EZVIZ ha restituito un errore. Riprova tra un po'.",
    "recording": "● Registrazione",
    "recording_failed": "Impossibile salvare la registrazione",
    "stop": "Ferma",
    "record": "● Registra",
    "stop_recording": "■ Ferma la registrazione"
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
    "no_code_stored": "sem código guardado",
    "err_network": "A câmara não respondeu: a ligação está fraca. Verifique o Wi-Fi e tente novamente.",
    "err_offline": "A câmara não está ligada à EZVIZ.",
    "err_token": "A sessão EZVIZ expirou. Tente novamente.",
    "err_viewers": "Há demasiadas pessoas a ver esta câmara ao mesmo tempo.",
    "err_permission": "Esta conta não tem permissão para ver a câmara.",
    "err_device": "A câmara reportou um erro. Tente novamente.",
    "err_service": "A EZVIZ devolveu um erro. Tente novamente daqui a pouco.",
    "recording": "● A gravar",
    "recording_failed": "Não foi possível guardar a gravação",
    "stop": "Parar",
    "record": "● Gravar",
    "stop_recording": "■ Parar de gravar"
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
    "no_code_stored": "sem código salvo",
    "err_network": "A câmera não respondeu: a conexão está fraca. Verifique o Wi-Fi e tente de novo.",
    "err_offline": "A câmera não está conectada à EZVIZ.",
    "err_token": "A sessão da EZVIZ expirou. Tente de novo.",
    "err_viewers": "Tem gente demais assistindo a esta câmera ao mesmo tempo.",
    "err_permission": "Esta conta não tem permissão para ver a câmera.",
    "err_device": "A câmera informou um erro. Tente de novo.",
    "err_service": "A EZVIZ retornou um erro. Tente de novo daqui a pouco.",
    "recording": "● Gravando",
    "recording_failed": "Não foi possível salvar a gravação",
    "stop": "Parar",
    "record": "● Gravar",
    "stop_recording": "■ Parar de gravar"
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
    "no_code_stored": "geen code opgeslagen",
    "err_network": "De camera reageerde niet: de verbinding is zwak. Controleer de wifi en probeer het opnieuw.",
    "err_offline": "De camera is niet verbonden met EZVIZ.",
    "err_token": "De EZVIZ-sessie is verlopen. Probeer het opnieuw.",
    "err_viewers": "Te veel mensen kijken tegelijk naar deze camera.",
    "err_permission": "Dit account mag de camera niet bekijken.",
    "err_device": "De camera meldde een fout. Probeer het opnieuw.",
    "err_service": "EZVIZ gaf een fout terug. Probeer het later opnieuw.",
    "recording": "● Opnemen",
    "recording_failed": "Kan de opname niet opslaan",
    "stop": "Stoppen",
    "record": "● Opnemen",
    "stop_recording": "■ Opname stoppen"
  }
} /* end translations */;

// The player reports stream failures as English text only, from a fixed table in
// the pinned ezuikit-js version. Known texts map to translated messages; anything
// else is shown as the player wrote it.
// ponytail: matches the 9.0.23 texts; after bumping EZUIKIT, check the table still matches.
const PLAYER_ERRORS = [
  [/network (is poor|on the device side is poor|abnormality)|streaming connection is disconnected|client network timeout/i, "err_network"],
  [/not online|device does not exist/i, "err_offline"],
  [/token (expired|invalid)/i, "err_token"],
  [/simultaneous viewers|number of viewing channels/i, "err_viewers"],
  [/no permission to view/i, "err_permission"],
  [/device (channel )?abnormal|channel is abnormal|device channel error/i, "err_device"],
  [/service exception|stream retrieval failed/i, "err_service"],
];

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
    this._recButton = null;
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
    // Record mode lives in the integration; an older integration just answers an error.
    this._session = null;
    try {
      ({ session_id: this._session } = await this._hass.callWS({
        type: "ezviz_cloud/recording/start",
        serial: this._config.serial,
      }));
    } catch (err) {
      this._session = null;
    }
    // Left the view while asking: release the camera now instead of after the timeout.
    if (!this.isConnected) {
      this._finishRecording();
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
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}#v,#v canvas{width:100%!important;height:100%!important}#v{width:1280px!important;height:720px!important;transform-origin:0 0}</style>
<script>const send=(m)=>parent.postMessage({ezvizCloud:m},"*");</script>
<script src="${EZUIKIT}" onerror="send({errorKey:'player_load_failed'})"></script></head><body><div id="v"></div><script>
if(window.EZUIKit){
const o=${opts};
const E=EZUIKit.EZUIKitPlayer.EVENTS;
send({stage:25,key:"loading_decoder"});
const R=${this._session ? "true" : "false"};
// The player sizes its canvas to its box: a fixed 720p box, scaled down to the
// card, keeps recordings at 720p whatever the card's size.
const fit=()=>{document.getElementById('v').style.transform='scale('+Math.min(innerWidth/1280,innerHeight/720)+')';};
fit();addEventListener('resize',fit);
const player=new EZUIKit.EZUIKitPlayer({id:'v',width:1280,height:720,...o,
  handleError:(e)=>send({error:e&&(e.msg||e.data&&e.data.msg||e.type)})});
player.eventEmitter.on(E.decoderLoaded,()=>send({stage:60,key:"waking_camera"}));
player.eventEmitter.on(E.videoInfo,()=>send({stage:90,key:"starting_video"}));
let rec=null;
const startRec=()=>{
  const c=document.querySelector('#v canvas');
  const type=['video/mp4;codecs=avc1','video/webm;codecs=vp9','video/webm'].find(t=>window.MediaRecorder&&MediaRecorder.isTypeSupported(t));
  if(!c||!type)return send({recError:true});
  rec=new MediaRecorder(c.captureStream(15),{mimeType:type,videoBitsPerSecond:1500000});
  rec.ondataavailable=(e)=>{if(e.data.size)send({chunk:e.data,type});};
  rec.onstop=()=>send({recStopped:true});
  rec.start(2000);
  send({recording:true});
};
// Record / Stop recording pressed on the card during the live view.
addEventListener('message',(e)=>{
  if(e.source!==parent)return;
  if(e.data==='start-recording'&&!(rec&&rec.state!=='inactive'))startRec();
  if(e.data==='stop-recording'&&rec&&rec.state!=='inactive')rec.stop();
});
player.eventEmitter.on(E.firstFrameDisplay,()=>{send({ready:true});if(R)startRec();});
// Stream failures (camera did not answer, bad code...) only arrive as messages.
player.eventEmitter.on('message',(msg,type)=>{if(type==='fetchError')send({error:msg})});
}
</script></body></html>`;
    this._onMessage = (ev) => {
      const m = ev.source === iframe.contentWindow && ev.data?.ezvizCloud;
      if (!m) return;
      if (m.recording) {
        this._setBadge(t(this._lang, "recording"));
        this._hass
          .callWS({ type: "ezviz_cloud/recording/first_frame", session_id: this._session })
          .catch(() => {});
        return;
      }
      if (m.chunk) return this._upload(m.chunk, m.type);
      // The recorder flushed its last chunk after Stop recording: close the file.
      if (m.recStopped) {
        this._finishRecording();
        this._setBadge(null);
        return this._paintRecordButton();
      }
      if (m.recError) return this._recordingFailed();
      if (m.errorKey) this._fail(t(this._lang, m.errorKey));
      // The player's own messages exist only in English and Chinese.
      else if ("error" in m) {
        const known = PLAYER_ERRORS.find(([re]) => re.test(m.error || ""));
        this._fail(
          known
            ? t(this._lang, known[1])
            : t(this._lang, "could_not_start", { msg: m.error || t(this._lang, "player_error") }),
        );
      }
      else if (m.ready) {
        this._hideProgress();
        this._paintRecordButton();
      }
      else this._showProgress(m.stage, m.key);
    };
    window.addEventListener("message", this._onMessage);
    this._box.insertBefore(iframe, this._overlay);
    const stop = document.createElement("button");
    stop.textContent = `■ ${t(this._lang, "stop")}`;
    stop.style.cssText =
      "position:absolute;right:8px;bottom:8px;z-index:1;font:inherit;font-size:12px;padding:4px 10px;border:0;border-radius:12px;cursor:pointer;background:rgba(0,0,0,.6);color:#fff";
    stop.addEventListener("click", () => this._stop());
    this._box.appendChild(stop);
    this._timer = setTimeout(
      () => (this._overlay ? this._fail(t(this._lang, "no_video", { s: max_seconds })) : this._stop()),
      max_seconds * 1000,
    );
  }

  // Record / Stop recording during the live view, whatever the camera's mode.
  _paintRecordButton() {
    if (!this._box?.querySelector("iframe")) return;
    if (!this._recButton) {
      this._recButton = document.createElement("button");
      this._recButton.style.cssText =
        "position:absolute;left:8px;bottom:8px;z-index:1;font:inherit;font-size:12px;padding:4px 10px;border:0;border-radius:12px;cursor:pointer;background:rgba(0,0,0,.6);color:#fff";
      this._recButton.addEventListener("click", () => this._toggleRecording());
    }
    this._recButton.disabled = false;
    this._recButton.textContent = this._session
      ? t(this._lang, "stop_recording")
      : t(this._lang, "record");
    this._box.appendChild(this._recButton);
  }

  async _toggleRecording() {
    const frame = this._box?.querySelector("iframe")?.contentWindow;
    if (!frame) return;
    if (this._session) {
      // The iframe answers with recStopped once the last chunk is out.
      this._recButton.disabled = true;
      frame.postMessage("stop-recording", "*");
      return;
    }
    let session = null;
    try {
      ({ session_id: session } = await this._hass.callWS({
        type: "ezviz_cloud/recording/start",
        serial: this._config.serial,
        manual: true,
      }));
    } catch (err) {
      session = null;
    }
    if (!session) {
      this._setBadge(t(this._lang, "recording_failed"));
      setTimeout(() => this._setBadge(null), 5000);
      return;
    }
    this._session = session;
    this._paintRecordButton();
    frame.postMessage("start-recording", "*");
  }

  // Chunks go up in order, one at a time, with the user's own session.
  _upload(blob, type) {
    const sid = this._session;
    if (!sid) return;
    this._uploads = (this._uploads || Promise.resolve())
      .then(async () => {
        const res = await this._hass.fetchWithAuth(`/api/ezviz_cloud/recording/${sid}`, {
          method: "POST",
          body: blob,
          headers: { "Content-Type": type },
        });
        if (!res.ok) throw new Error(`upload ${res.status}`);
      })
      .catch(() => this._recordingFailed());
  }

  // ponytail: the iframe goes away with the stream, so up to the last 2 s of
  // video are lost; keep the iframe alive until the recorder flushes if that matters.
  _finishRecording() {
    const sid = this._session;
    if (!sid) return;
    this._session = null;
    const uploads = this._uploads || Promise.resolve();
    this._uploads = null;
    uploads.finally(() =>
      this._hass.callWS({ type: "ezviz_cloud/recording/stop", session_id: sid }).catch(() => {}),
    );
  }

  _recordingFailed() {
    if (!this._session) return;
    this._finishRecording();
    this._paintRecordButton();
    this._setBadge(t(this._lang, "recording_failed"));
    setTimeout(() => this._setBadge(null), 5000);
  }

  _setBadge(text) {
    this._badge?.remove();
    this._badge = null;
    if (!text || !this._box) return;
    this._badge = document.createElement("div");
    this._badge.style.cssText =
      "position:absolute;top:8px;left:8px;padding:2px 8px;border-radius:10px;background:rgba(0,0,0,.6);color:#fff;font-size:12px;pointer-events:none";
    this._badge.textContent = text;
    this._box.appendChild(this._badge);
  }

  _fail(message) {
    this._stop();
    this._render(message);
  }

  _stop() {
    clearTimeout(this._timer);
    this._finishRecording();
    window.removeEventListener("message", this._onMessage);
    this._hideProgress();
    this._setBadge(null);
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
