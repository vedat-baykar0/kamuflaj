/*
 * Kamuflaj — istemci.
 *
 * 3 mod:
 *   online : WebSocket, ipucu kelimeleri ekrandan yazilir
 *   local  : WebSocket, roller telefonlarda gorunur, kelimeler yuz yuze soylenir
 *   single : tek telefon, tamamen istemci tarafinda (WebSocket kullanmaz)
 */
(function () {
  "use strict";

  var SESSION_KEY = "kamuflaj.session.v1";
  var NAME_KEY = "kamuflaj.name.v1";
  var MODE_KEY = "kamuflaj.mode.v1";
  var MIN_PLAYERS = 3;
  var MAX_PLAYERS = 12;

  var S = {
    ws: null, open: false, state: null, you: null,
    queue: [], attempts: 0, reconnectTimer: null, suppressReconnect: false,
    session: null, name: "", homeMode: "online",
    wordHidden: false, countdown: 0, countdownTimer: null,
    lastPhase: null, lastWordCount: 0
  };

  var SM = {
    active: false, step: "setup", names: ["", "", "", ""],
    players: [], word: "", imposter: -1,
    revealIndex: 0, revealed: false,
    voteIndex: 0, voteReady: false, votes: [],
    guessReady: false, result: null, recent: [], busy: false
  };

  /* ------------------------------------------------------------- yardimcilar */

  function el(id) { return document.getElementById(id); }

  function esc(value) {
    return String(value === undefined || value === null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function store(key, value) {
    try {
      if (value === null) { localStorage.removeItem(key); } else { localStorage.setItem(key, value); }
    } catch (e) { /* private mode */ }
  }

  function read(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  function loadSession() {
    var raw = read(SESSION_KEY);
    if (!raw) { return null; }
    try {
      var obj = JSON.parse(raw);
      if (obj && obj.code && obj.player_id && obj.token) { return obj; }
    } catch (e) { /* bozuk */ }
    return null;
  }

  function saveSession(session) {
    S.session = session;
    store(SESSION_KEY, session ? JSON.stringify(session) : null);
  }

  function trLower(text) {
    return String(text === undefined || text === null ? "" : text)
      .replace(/I/g, "ı").replace(/İ/g, "i").toLowerCase();
  }

  function normWord(text) {
    return trLower(text).trim().replace(/[^\p{L}\p{N}]/gu, "");
  }

  var TOAST_STYLES = {
    error: "border-rose-500/50 bg-rose-500/15 text-rose-200",
    ok: "border-emerald-500/50 bg-emerald-500/15 text-emerald-200",
    info: "border-slate-600 bg-panel text-slate-200"
  };

  function toast(message, kind) {
    var wrap = el("toasts");
    if (!wrap) { return; }
    var node = document.createElement("div");
    node.className = "animate-slide pointer-events-auto max-w-sm rounded-xl border px-4 py-2.5 text-sm font-semibold shadow-2xl backdrop-blur " +
      (TOAST_STYLES[kind] || TOAST_STYLES.info);
    node.textContent = message;
    wrap.appendChild(node);
    setTimeout(function () {
      node.style.transition = "opacity .3s, transform .3s";
      node.style.opacity = "0";
      node.style.transform = "translateY(8px)";
      setTimeout(function () { if (node.parentNode) { node.parentNode.removeChild(node); } }, 320);
    }, 3200);
  }

  function copyText(text, okMessage) {
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); toast(okMessage, "ok"); }
      catch (e) { toast("Kopyalanamadı: " + text, "info"); }
      document.body.removeChild(ta);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { toast(okMessage, "ok"); }, fallback);
    } else { fallback(); }
  }

  function modeLabel(mode) {
    if (mode === "local") { return "YAN YANA"; }
    if (mode === "single") { return "TEK TELEFON"; }
    return "ONLINE";
  }

  /* ---------------------------------------------------------------- baglanti */

  function setConn(status) {
    var dot = el("conn-dot");
    var text = el("conn-text");
    if (!dot || !text) { return; }
    var map = {
      online: ["bg-emerald-400", "bağlı"],
      connecting: ["bg-amber-400 animate-pulse", "bağlanıyor"],
      offline: ["bg-rose-500 animate-pulse", "bağlantı yok"]
    };
    var conf = map[status] || map.connecting;
    dot.className = "h-2 w-2 rounded-full " + conf[0];
    text.textContent = conf[1];
  }

  function send(payload) {
    if (S.open && S.ws && S.ws.readyState === 1) {
      S.ws.send(JSON.stringify(payload));
    } else {
      S.queue.push(payload);
      connect();
    }
  }

  function flushQueue() {
    while (S.queue.length && S.open && S.ws && S.ws.readyState === 1) {
      S.ws.send(JSON.stringify(S.queue.shift()));
    }
  }

  function connect() {
    if (S.ws && (S.ws.readyState === 0 || S.ws.readyState === 1)) { return; }
    if (S.reconnectTimer) { clearTimeout(S.reconnectTimer); S.reconnectTimer = null; }
    setConn("connecting");
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var ws;
    try { ws = new WebSocket(proto + "//" + location.host + "/ws"); }
    catch (e) { scheduleReconnect(); return; }
    S.ws = ws;

    ws.onopen = function () {
      S.open = true;
      S.attempts = 0;
      setConn("online");
      if (S.session) {
        ws.send(JSON.stringify({
          type: "rejoin", code: S.session.code,
          player_id: S.session.player_id, token: S.session.token
        }));
      }
      flushQueue();
    };

    ws.onmessage = function (event) {
      var msg;
      try { msg = JSON.parse(event.data); } catch (e) { return; }
      handleMessage(msg);
    };

    ws.onclose = function () {
      S.open = false;
      setConn("offline");
      if (!S.suppressReconnect) { scheduleReconnect(); }
    };

    ws.onerror = function () { /* onclose yeterli */ };
  }

  function scheduleReconnect() {
    if (S.reconnectTimer) { return; }
    S.attempts += 1;
    var delay = Math.min(800 * Math.pow(1.6, Math.min(S.attempts, 6)), 8000);
    S.reconnectTimer = setTimeout(function () { S.reconnectTimer = null; connect(); }, delay);
  }

  function closeSocket() {
    S.suppressReconnect = true;
    try { if (S.ws) { S.ws.close(); } } catch (e) { /* yok */ }
    S.ws = null;
    S.open = false;
    setTimeout(function () { S.suppressReconnect = false; connect(); }, 400);
  }

  /* -------------------------------------------------------------- mesajlar */

  function handleMessage(msg) {
    switch (msg.type) {
      case "joined":
        saveSession({ code: msg.code, player_id: msg.player_id, token: msg.token });
        S.name = msg.name || S.name;
        store(NAME_KEY, S.name);
        if (!msg.rejoined) { toast("Odaya girdin: " + msg.code, "ok"); }
        updateUrlRoom(msg.code);
        break;
      case "state":
        S.state = msg.state;
        S.you = msg.you;
        render();
        break;
      case "error":
        handleError(msg);
        break;
      case "room_closed":
        resetRoomLocal();
        toast(msg.message || "Oda kapatıldı.", "error");
        render();
        break;
      case "kicked":
        resetRoomLocal();
        toast(msg.message || "Odadan çıkarıldın.", "error");
        render();
        break;
      case "left":
        resetRoomLocal();
        render();
        break;
      default:
        break;
    }
  }

  function resetRoomLocal() {
    saveSession(null);
    S.state = null;
    S.you = null;
    S.lastPhase = null;
    S.lastWordCount = 0;
    stopCountdown();
    updateUrlRoom(null);
  }

  function handleError(msg) {
    var code = msg.code || "";
    if (code === "session_invalid" || code === "room_not_found") {
      var old = S.session;
      resetRoomLocal();
      render();
      if (old && S.name && code === "session_invalid") {
        send({ type: "join_room", code: old.code, name: S.name });
        return;
      }
      toast(msg.message || "Oda bulunamadı.", "error");
      return;
    }
    toast(msg.message || "Bir hata oluştu.", "error");
  }

  function updateUrlRoom(code) {
    try {
      var url = new URL(location.href);
      if (code) { url.searchParams.set("room", code); } else { url.searchParams.delete("room"); }
      history.replaceState(null, "", url.toString());
    } catch (e) { /* onemsiz */ }
  }

  /* ---------------------------------------------------------------- cizim */

  function showScreen(name) {
    ["home", "single", "lobby", "room"].forEach(function (key) {
      var node = el("screen-" + key);
      if (node) { node.classList.toggle("hidden", key !== name); }
    });
  }

  function render() {
    if (SM.active) {
      el("room-chip").classList.add("hidden");
      el("btn-copy-link").classList.add("hidden");
      el("conn-wrap").classList.add("hidden");
      showScreen("single");
      renderSingle();
      return;
    }
    el("conn-wrap").classList.remove("hidden");

    var st = S.state;
    var inRoom = !!(st && S.you);
    el("room-chip").classList.toggle("hidden", !inRoom);
    el("room-chip").classList.toggle("flex", inRoom);
    el("btn-copy-link").classList.toggle("hidden", !inRoom);

    if (!inRoom) {
      stopCountdown();
      S.lastPhase = null;
      showScreen("home");
      syncHomeMode();
      var nameInput = el("input-name");
      if (nameInput && !nameInput.value && S.name) { nameInput.value = S.name; }
      return;
    }

    el("room-chip-code").textContent = st.code;
    el("room-chip-mode").textContent = modeLabel(st.mode);

    if (st.phase !== S.lastPhase) {
      S.wordHidden = st.mode === "local";
      announcePhase(st.phase, st.mode);
      S.lastPhase = st.phase;
    }

    if (st.phase === "lobby") {
      stopCountdown();
      showScreen("lobby");
      renderLobby(st);
    } else {
      showScreen("room");
      renderRoom(st);
    }
  }

  function announcePhase(phase, mode) {
    if (phase === "playing") { toast("Oyun başladı! Rolünü kontrol et.", "ok"); }
    else if (phase === "talking") { toast("Roller dağıtıldı. Rolüne bak ve sesli oynayın.", "ok"); }
    else if (phase === "voting") { toast("Oylama başladı.", "info"); }
    else if (phase === "guessing") { toast("Kamuflaj tahmin ediyor...", "info"); }
  }

  /* ----- lobi ----- */

  function renderLobby(st) {
    el("lobby-code").textContent = st.code;
    el("lobby-mode-info").textContent = st.mode === "local"
      ? "Yan yana modu: herkes rolünü kendi telefonunda görür, kelimeler sesli söylenir. Tur bitince oda sahibi oylamayı başlatır."
      : "Online mod: sırası gelen oyuncu ipucu kelimesini ekrana yazar.";

    el("lobby-rounds-wrap").classList.toggle("hidden", st.mode !== "online");
    var select = el("select-rounds");
    if (document.activeElement !== select) { select.value = String(st.rounds_total); }
    select.disabled = !S.you.is_host;
    el("rounds-hint").textContent = S.you.is_host
      ? "Toplam " + (st.players.length * st.rounds_total) + " kelime söylenecek."
      : "Ayarı sadece oda sahibi değiştirebilir.";

    var connectedCount = st.players.filter(function (p) { return p.connected; }).length;
    var startBtn = el("btn-start");
    var hint = el("start-hint");
    if (!S.you.is_host) {
      startBtn.disabled = true;
      startBtn.textContent = "Oda sahibi bekleniyor...";
      hint.textContent = "Oyunu oda sahibi başlatacak.";
    } else if (connectedCount < st.min_players) {
      startBtn.disabled = true;
      startBtn.textContent = "Oyunu Başlat";
      hint.textContent = "En az " + st.min_players + " oyuncu gerekli (şu an " + connectedCount + ").";
    } else {
      startBtn.disabled = false;
      startBtn.textContent = "Oyunu Başlat (" + connectedCount + " oyuncu)";
      hint.textContent = "Havuzda " + st.word_pool_size + " kelime var.";
    }

    el("lobby-players").innerHTML = playersPanelHtml(st, "Oyuncular");
    el("lobby-log").innerHTML = logHtml(st);
    bindPlayerButtons();
  }

  /* ----- oyun ekrani ----- */

  function renderRoom(st) {
    var draftWord = el("input-word") ? el("input-word").value : null;
    var draftGuess = el("input-guess") ? el("input-guess").value : null;

    el("role-card").innerHTML = roleCardHtml(st);
    el("turn-banner").innerHTML = turnBannerHtml(st);
    el("action-panel").innerHTML = actionPanelHtml(st);
    el("words-feed").innerHTML = (st.mode === "online" || st.words.length) ? wordsFeedHtml(st) : "";
    el("room-players").innerHTML = playersPanelHtml(st, st.phase === "ended" ? "Sonuç tablosu" : "Oyuncular");
    el("room-log").innerHTML = logHtml(st);

    if (draftWord && el("input-word")) { el("input-word").value = draftWord; }
    if (draftGuess && el("input-guess")) { el("input-guess").value = draftGuess; }

    bindPlayerButtons();
    bindRoleCard();
    bindActionPanel();

    if (st.phase === "guessing" && typeof st.guess_remaining === "number") {
      startCountdown(st.guess_remaining);
    } else {
      stopCountdown();
    }

    if (st.words.length !== S.lastWordCount) {
      S.lastWordCount = st.words.length;
      var feed = el("words-scroll");
      if (feed) { feed.scrollTop = feed.scrollHeight; }
    }
  }

  function roleCardHtml(st) {
    var you = S.you;
    if (st.phase === "ended" && st.result) { return resultCardHtml(st.result, you.id); }

    if (!you.in_game) {
      return '<div class="rounded-2xl border border-slate-600/60 bg-panel/80 p-6 text-center">' +
        '<p class="text-xs font-bold uppercase tracking-[.2em] text-slate-400">Rolün</p>' +
        '<h2 class="mt-2 text-2xl font-black text-slate-200">İzleyici</h2>' +
        '<p class="mt-2 text-sm text-slate-400">Bu ele sonradan katıldın, sonraki oyunda dahil olacaksın.</p></div>';
    }

    var hidden = S.wordHidden;
    var toggle = '<div class="mt-4 flex flex-wrap items-center justify-center gap-3">' +
      '<button id="btn-toggle-word" class="tap rounded-lg border border-white/20 bg-white/10 px-4 py-2 text-xs font-bold text-white transition hover:bg-white/20">' +
        (hidden ? "👁️ Göster" : "🙈 Gizle") +
      '</button></div>';

    if (you.is_imposter) {
      return '<div class="animate-pop rounded-2xl border border-rose-500/50 bg-gradient-to-br from-rose-500/15 to-rose-900/10 p-6 text-center glow-red">' +
        '<p class="text-xs font-bold uppercase tracking-[.2em] text-rose-300">Rolün</p>' +
        '<h2 id="secret-word" class="mt-2 text-3xl font-black text-rose-200 sm:text-4xl' + (hidden ? ' blurred' : '') + '">SEN KAMUFLAJSIN 🥸</h2>' +
        '<p class="mx-auto mt-3 max-w-xl text-sm text-rose-100/80' + (hidden ? ' blurred' : '') + '" id="secret-hint">' +
          'Gizli kelimeyi bilmiyorsun. Söylenen kelimelerden anlamaya çalış, uyumlu görün ve yakalanma. ' +
          'Sonda kelimeyi tek seferde doğru tahmin edersen yakalansan bile kazanırsın.' +
        '</p>' + toggle + '</div>';
    }

    return '<div class="animate-pop rounded-2xl border border-emerald-500/50 bg-gradient-to-br from-emerald-500/15 to-emerald-900/10 p-6 text-center glow-green">' +
      '<p class="text-xs font-bold uppercase tracking-[.2em] text-emerald-300">Gizli kelime</p>' +
      '<h2 id="secret-word" class="mt-2 break-words text-3xl font-black text-emerald-100 sm:text-4xl' + (hidden ? ' blurred' : '') + '">' +
        esc(you.secret_word || "—") + '</h2>' +
      '<p class="mt-3 text-sm text-emerald-100/70">Kelimeyi çağrıştıran ama çok açık etmeyen tek bir kelime söyle.</p>' +
      toggle + '</div>';
  }

  function resultCardHtml(r, youId) {
    var crewWin = r.winner === "crew";
    var youWin = crewWin ? (youId !== r.imposter_id) : (youId === r.imposter_id);
    return '<div class="animate-pop rounded-2xl border p-6 text-center ' +
      (crewWin ? 'border-emerald-500/50 bg-emerald-500/10 glow-green' : 'border-rose-500/50 bg-rose-500/10 glow-red') + '">' +
      '<p class="text-xs font-bold uppercase tracking-[.2em] ' + (crewWin ? 'text-emerald-300' : 'text-rose-300') + '">Oyun bitti</p>' +
      '<h2 class="mt-2 text-3xl font-black sm:text-4xl">' + esc(r.winner_label) + '</h2>' +
      '<p class="mt-2 text-sm text-slate-300">' + esc(r.reason) + '</p>' +
      '<div class="mt-5 grid gap-3 sm:grid-cols-3">' +
        resultTile("Gizli kelime", esc(r.secret_word), "text-emerald-300") +
        resultTile("Kamuflaj", esc(r.imposter_name), "text-rose-300") +
        resultTile("Kamuflaj tahmini", r.guess ? esc(r.guess) + (r.guess_correct ? " ✅" : " ❌") : "— yok —",
                   r.guess_correct ? "text-emerald-300" : "text-slate-300") +
      '</div>' +
      (youId ? '<p class="mt-4 text-sm font-bold ' + (youWin ? 'text-emerald-300' : 'text-slate-400') + '">' +
        (youWin ? "Bu eli sen kazandın! 🎉" : "Bu eli kaybettin.") + '</p>' : "") +
      '</div>';
  }

  function resultTile(label, value, valueClass) {
    return '<div class="rounded-xl border border-edge bg-ink/50 p-3">' +
      '<p class="text-[11px] font-bold uppercase tracking-wider text-slate-500">' + label + '</p>' +
      '<p class="mt-1 break-words text-lg font-black ' + valueClass + '">' + value + '</p></div>';
  }

  function turnBannerHtml(st) {
    if (st.phase === "playing") {
      var current = findPlayer(st, st.turn_player_id);
      var mine = S.you.is_turn;
      var progress = st.turns_total ? Math.round((st.turns_done / st.turns_total) * 100) : 0;
      return '<div class="rounded-2xl border ' + (mine ? 'border-amber-400/60 bg-amber-400/10' : 'border-edge bg-panel/80') + ' p-4">' +
        '<div class="flex flex-wrap items-center justify-between gap-2">' +
          '<p class="text-sm font-bold ' + (mine ? 'text-amber-200' : 'text-slate-200') + '">' +
            (mine ? "🎯 Sıra sende — tek kelime yaz!" : "⏳ Sıra: " + esc(current ? current.name : "—")) + '</p>' +
          '<p class="text-xs font-bold text-slate-400">Tur ' + st.round_no + " / " + st.rounds_total +
            ' · ' + st.turns_done + "/" + st.turns_total + ' kelime</p>' +
        '</div>' +
        '<div class="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-ink">' +
          '<div class="h-full rounded-full bg-emerald-500 transition-all" style="width:' + progress + '%"></div>' +
        '</div></div>';
    }
    if (st.phase === "talking") {
      return '<div class="rounded-2xl border border-amber-400/50 bg-amber-400/10 p-4">' +
        '<p class="text-sm font-bold text-amber-200">🗣️ Konuşma turu</p>' +
        '<p class="mt-1 text-xs text-amber-100/70">Sırayla yüz yüze birer kelime söyleyin. Telefona yazmak yok.</p></div>';
    }
    if (st.phase === "voting") {
      return '<div class="rounded-2xl border border-indigo-500/50 bg-indigo-500/10 p-4">' +
        '<p class="text-sm font-bold text-indigo-200">🗳️ Oylama zamanı</p>' +
        '<p class="mt-1 text-xs text-indigo-100/70">' + st.votes_cast + " / " + st.votes_needed +
        ' oy kullanıldı. Herkes oy verince sonuç açılır.</p></div>';
    }
    if (st.phase === "guessing") {
      return '<div class="rounded-2xl border border-rose-500/50 bg-rose-500/10 p-4">' +
        '<p class="text-sm font-bold text-rose-200">🥸 Kamuflaj son tahminini yapıyor</p>' +
        '<p class="mt-1 text-xs text-rose-100/70">Doğru tahmin ederse yakalansa bile kazanır.</p></div>';
    }
    return "";
  }

  function hostToolsHtml(st) {
    if (!S.you.is_host) { return ""; }
    var tools = "";
    if (st.phase === "playing") {
      tools += '<button id="btn-skip-turn" class="tap rounded-lg border border-edge bg-ink px-3 py-2 text-xs font-bold text-slate-300 transition hover:border-amber-500/60">Sırayı atla</button>';
    }
    tools += '<button id="btn-start-voting" class="tap rounded-lg bg-indigo-500 px-4 py-2 text-xs font-black text-white transition hover:bg-indigo-400">Oylamaya Geç</button>';
    return '<div class="mt-3 flex flex-wrap gap-2 border-t border-edge pt-3">' + tools +
      '<span class="self-center text-[11px] text-slate-500">(oda sahibi)</span></div>';
  }

  function actionPanelHtml(st) {
    if (st.phase === "playing") {
      if (!S.you.in_game) {
        return '<div class="rounded-2xl border border-edge bg-panel/80 p-5 text-sm text-slate-400">İzleyici olarak bekliyorsun.' + hostToolsHtml(st) + '</div>';
      }
      if (!S.you.can_write_words) {
        return '<div class="rounded-2xl border border-edge bg-panel/80 p-5">' +
          '<p class="text-sm text-slate-400">Sıranı bekliyorsun. Diğerlerinin kelimelerini dikkatle izle.</p>' +
          hostToolsHtml(st) + '</div>';
      }
      return '<div class="rounded-2xl border border-amber-400/50 bg-panel/80 p-5">' +
        '<label class="block text-xs font-bold uppercase tracking-wider text-slate-400">Tek kelimen</label>' +
        '<div class="mt-2 flex gap-2">' +
          '<input id="input-word" type="text" maxlength="24" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="örn. soğuk"' +
            ' class="w-full rounded-xl border border-edge bg-ink/70 px-4 py-3 text-base font-semibold placeholder:text-slate-600 focus:border-amber-400/70" />' +
          '<button id="btn-send-word" class="tap shrink-0 rounded-xl bg-amber-400 px-5 py-3 text-sm font-black text-amber-950 transition hover:bg-amber-300 active:scale-[.98]">Gönder</button>' +
        '</div>' +
        '<p class="mt-2 text-xs text-slate-500">Sadece harf, 2-24 karakter, tek kelime. Tekrar eden kelime ve gizli kelimenin kendisi yasak.</p>' +
        hostToolsHtml(st) + '</div>';
    }

    if (st.phase === "talking") {
      if (S.you.is_host) {
        return '<div class="rounded-2xl border border-indigo-500/50 bg-panel/80 p-5">' +
          '<p class="text-sm font-bold text-slate-200">Konuşma turu devam ediyor</p>' +
          '<p class="mt-1 text-xs text-slate-500">Herkes kelimesini söyledikten sonra oylamayı başlat.</p>' +
          '<button id="btn-start-voting" class="tap mt-4 w-full rounded-xl bg-indigo-500 px-4 py-4 text-base font-black text-white transition hover:bg-indigo-400 active:scale-[.98]">🗳️ Oylamaya Geç</button>' +
          '</div>';
      }
      return '<div class="rounded-2xl border border-edge bg-panel/80 p-5">' +
        '<p class="text-sm text-slate-400">Kelimeleri sesli söyleyin. Oda sahibi oylamayı başlattığında bu ekran değişecek.</p></div>';
    }

    if (st.phase === "voting") { return votePanelHtml(st); }
    if (st.phase === "guessing") { return guessPanelHtml(st); }
    if (st.phase === "ended") { return endPanelHtml(st); }
    return "";
  }

  function votePanelHtml(st) {
    if (!S.you.can_vote) {
      return '<div class="rounded-2xl border border-edge bg-panel/80 p-5 text-sm text-slate-400">Bu elde izleyici olduğun için oy kullanamıyorsun.</div>';
    }
    var buttons = st.players.filter(function (p) {
      return p.in_game && p.connected && !p.is_you;
    }).map(function (p) {
      var chosen = S.you.voted_for === p.id;
      return '<button data-vote="' + esc(p.id) + '" class="tap flex items-center justify-between rounded-xl border px-4 py-3 text-left transition ' +
        (chosen ? 'border-rose-500/70 bg-rose-500/15' : 'border-edge bg-ink/50 hover:border-rose-500/50 hover:bg-rose-500/10') + '">' +
        '<span class="font-bold ' + (chosen ? 'text-rose-200' : 'text-slate-200') + '">' + esc(p.name) + '</span>' +
        '<span class="text-xs font-bold ' + (chosen ? 'text-rose-300' : 'text-slate-500') + '">' + (chosen ? "oyun ✓" : "şüpheli") + '</span>' +
        '</button>';
    }).join("");
    return '<div class="rounded-2xl border border-edge bg-panel/80 p-5">' +
      '<p class="text-sm font-bold text-slate-200">Köstebek sence kim?</p>' +
      '<p class="mt-1 text-xs text-slate-500">Herkes oy verene kadar seçimini değiştirebilirsin.</p>' +
      '<div class="mt-3 grid gap-2 sm:grid-cols-2">' + buttons + '</div></div>';
  }

  function guessPanelHtml(st) {
    var timer = '<span id="guess-timer" class="code-font text-2xl font-black text-rose-300">' +
      (typeof st.guess_remaining === "number" ? st.guess_remaining : st.guess_seconds) + '</span>';
    if (S.you.is_imposter) {
      return '<div class="rounded-2xl border border-rose-500/50 bg-panel/80 p-5">' +
        '<div class="flex items-center justify-between gap-3">' +
          '<p class="text-sm font-bold text-rose-200">Gizli kelimeyi tahmin et — tek hakkın var!</p>' + timer +
        '</div>' +
        '<div class="mt-3 flex gap-2">' +
          '<input id="input-guess" type="text" maxlength="40" autocomplete="off" spellcheck="false" placeholder="gizli kelime"' +
            ' class="w-full rounded-xl border border-edge bg-ink/70 px-4 py-3 text-base font-semibold placeholder:text-slate-600 focus:border-rose-500/70" />' +
          '<button id="btn-send-guess" class="tap shrink-0 rounded-xl bg-rose-500 px-5 py-3 text-sm font-black text-white transition hover:bg-rose-400 active:scale-[.98]">Tahmin Et</button>' +
        '</div>' +
        '<button id="btn-skip-guess" class="tap mt-3 text-xs font-bold text-slate-400 underline decoration-dotted hover:text-slate-200">Tahmin etmeden sonuca geç</button>' +
        '</div>';
    }
    return '<div class="rounded-2xl border border-edge bg-panel/80 p-5">' +
      '<div class="flex items-center justify-between gap-3"><div>' +
      '<p class="text-sm font-bold text-slate-200">Oylar kilitlendi.</p>' +
      '<p class="mt-1 text-xs text-slate-500">Kamuflaj gizli kelimeyi tahmin etmeye çalışıyor...</p>' +
      '</div>' + timer + '</div></div>';
  }

  function endPanelHtml(st) {
    var r = st.result || {};
    var counts = (r.vote_counts || []).map(function (row) {
      return '<li class="flex items-center justify-between rounded-lg border border-edge bg-ink/40 px-3 py-2">' +
        '<span class="font-bold ' + (row.is_imposter ? 'text-rose-300' : 'text-slate-200') + '">' +
        esc(row.name) + (row.is_imposter ? " 🥸" : "") + '</span>' +
        '<span class="text-xs font-bold text-slate-400">' + row.count + ' oy</span></li>';
    }).join("") || '<li class="rounded-lg border border-edge bg-ink/40 px-3 py-2 text-xs text-slate-500">Hiç oy kullanılmadı.</li>';

    var detail = (r.votes || []).map(function (v) {
      return '<li class="flex items-center gap-2 text-xs">' +
        '<span class="text-slate-300">' + esc(v.voter) + '</span><span class="text-slate-600">→</span>' +
        '<span class="' + (v.correct ? 'text-emerald-300' : 'text-slate-400') + '">' + esc(v.target) + '</span>' +
        (v.correct ? '<span class="text-emerald-400">✓</span>' : '') + '</li>';
    }).join("");

    var hostBtn = S.you.is_host
      ? '<button id="btn-play-again" class="tap mt-5 w-full rounded-xl bg-emerald-500 px-4 py-4 text-base font-black text-emerald-950 transition hover:bg-emerald-400 active:scale-[.98]">Yeni Oyun (lobiye dön)</button>'
      : '<p class="mt-5 rounded-xl border border-edge bg-ink/40 px-4 py-3 text-center text-sm text-slate-400">Oda sahibinin yeni oyunu başlatması bekleniyor...</p>';

    return '<div class="rounded-2xl border border-edge bg-panel/80 p-5">' +
      '<p class="text-sm font-bold text-slate-200">Oylama dökümü</p>' +
      '<ul class="mt-3 space-y-2">' + counts + '</ul>' +
      (detail ? '<ul class="mt-4 space-y-1 border-t border-edge pt-3">' + detail + '</ul>' : "") +
      hostBtn + '</div>';
  }

  function wordsFeedHtml(st) {
    if (!st.words.length) {
      return '<div class="rounded-2xl border border-edge bg-panel/60 p-5">' +
        '<p class="text-sm font-bold text-slate-200">Söylenen kelimeler</p>' +
        '<p class="mt-2 text-xs text-slate-500">Henüz kelime söylenmedi.</p></div>';
    }
    var rows = st.words.map(function (w) {
      var isYou = w.player_id === S.you.id;
      var isImposter = st.phase === "ended" && st.result && w.player_id === st.result.imposter_id;
      return '<li class="flex items-center gap-3 rounded-xl border px-3 py-2.5 ' +
        (isImposter ? 'border-rose-500/40 bg-rose-500/10' : 'border-edge bg-ink/40') + '">' +
        '<span class="code-font w-6 shrink-0 text-center text-[11px] text-slate-500">' + w.index + '</span>' +
        '<span class="min-w-0 flex-1">' +
          '<span class="block truncate text-[11px] font-bold ' + (isImposter ? 'text-rose-300' : 'text-slate-400') + '">' +
            esc(w.name) + (isYou ? " (sen)" : "") + (isImposter ? " 🥸" : "") + '</span>' +
          '<span class="block break-words text-base font-bold text-slate-100">' + esc(w.word) + '</span>' +
        '</span>' +
        '<span class="shrink-0 rounded-md bg-panel px-2 py-0.5 text-[10px] font-bold text-slate-400">T' + w.round + '</span></li>';
    }).join("");
    return '<div class="rounded-2xl border border-edge bg-panel/60 p-5">' +
      '<div class="flex items-center justify-between">' +
        '<p class="text-sm font-bold text-slate-200">Söylenen kelimeler</p>' +
        '<span class="text-xs text-slate-500">' + st.words.length + ' kelime</span>' +
      '</div>' +
      '<ul id="words-scroll" class="scroll-thin mt-3 max-h-[22rem] space-y-2 overflow-y-auto pr-1">' + rows + '</ul></div>';
  }

  function playersPanelHtml(st, title) {
    var rows = st.players.map(function (p) {
      var badges = "";
      if (p.is_host) { badges += '<span class="rounded bg-amber-400/20 px-1.5 py-0.5 text-[10px] font-bold text-amber-300">SAHİP</span>'; }
      if (!p.connected) { badges += '<span class="rounded bg-slate-700 px-1.5 py-0.5 text-[10px] font-bold text-slate-400">ÇEVRİMDIŞI</span>'; }
      if (p.connected && !p.in_game && st.phase !== "lobby") { badges += '<span class="rounded bg-slate-700 px-1.5 py-0.5 text-[10px] font-bold text-slate-300">İZLEYİCİ</span>'; }
      if (p.is_imposter) { badges += '<span class="rounded bg-rose-500/25 px-1.5 py-0.5 text-[10px] font-bold text-rose-300">KAMUFLAJ</span>'; }
      if (st.phase === "voting" && p.has_voted) { badges += '<span class="rounded bg-indigo-500/25 px-1.5 py-0.5 text-[10px] font-bold text-indigo-300">OY ✓</span>'; }

      var kick = (S.you.is_host && !p.is_you)
        ? '<button data-kick="' + esc(p.id) + '" title="Odadan çıkar" class="tap shrink-0 rounded-md border border-edge px-1.5 py-0.5 text-[10px] font-bold text-slate-500 transition hover:border-rose-500/60 hover:text-rose-300">AT</button>'
        : "";

      return '<li class="flex items-center gap-2 rounded-xl border px-3 py-2.5 ' +
        (p.is_turn ? 'border-amber-400/60 bg-amber-400/10' : 'border-edge bg-ink/40') +
        (p.connected ? '' : ' opacity-60') + '">' +
        '<span class="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-panel text-sm font-black text-slate-300">' +
          esc(initials(p.name)) +
          '<span class="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-panel ' +
            (p.connected ? 'bg-emerald-400' : 'bg-slate-500') + '"></span>' +
        '</span>' +
        '<span class="min-w-0 flex-1">' +
          '<span class="block truncate text-sm font-bold ' + (p.is_you ? 'text-emerald-300' : 'text-slate-200') + '">' +
            esc(p.name) + (p.is_you ? " (sen)" : "") + '</span>' +
          (badges ? '<span class="mt-1 flex flex-wrap gap-1">' + badges + '</span>' : "") +
        '</span>' +
        '<span class="shrink-0 text-right"><span class="block text-sm font-black text-slate-200">' + p.score + '</span>' +
        '<span class="block text-[10px] text-slate-500">puan</span></span>' + kick + '</li>';
    }).join("");

    return '<div class="flex items-center justify-between">' +
      '<p class="text-sm font-bold text-slate-200">' + esc(title) + '</p>' +
      '<span class="text-xs text-slate-500">' + st.players.length + "/" + st.max_players + '</span></div>' +
      '<ul class="mt-3 space-y-2">' + rows + '</ul>';
  }

  function logHtml(st) {
    var rows = (st.log || []).slice().reverse().map(function (entry) {
      var color = {
        word: "text-slate-200", turn: "text-amber-300", vote: "text-indigo-300",
        guess: "text-rose-300", start: "text-emerald-300", end: "text-emerald-300",
        warn: "text-amber-400", join: "text-slate-400"
      }[entry.kind] || "text-slate-400";
      return '<li class="' + color + '">· ' + esc(entry.text) + "</li>";
    }).join("");
    return '<p class="text-xs font-bold uppercase tracking-wider text-slate-500">Olay akışı</p>' +
      '<ul class="scroll-thin mt-2 max-h-56 space-y-1 overflow-y-auto pr-1 text-xs">' +
      (rows || '<li class="text-slate-600">Henüz bir şey olmadı.</li>') + '</ul>';
  }

  function initials(name) {
    var parts = String(name || "?").trim().split(/\s+/);
    if (parts.length === 1) { return parts[0].slice(0, 2).toUpperCase(); }
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  function findPlayer(st, id) {
    for (var i = 0; i < st.players.length; i += 1) {
      if (st.players[i].id === id) { return st.players[i]; }
    }
    return null;
  }

  /* ------------------------------------------------------------ geri sayim */

  function startCountdown(seconds) {
    S.countdown = Math.max(0, seconds);
    paintCountdown();
    if (S.countdownTimer) { return; }
    S.countdownTimer = setInterval(function () {
      S.countdown = Math.max(0, S.countdown - 1);
      paintCountdown();
    }, 1000);
  }

  function paintCountdown() {
    var node = el("guess-timer");
    if (node) { node.textContent = String(S.countdown); }
  }

  function stopCountdown() {
    if (S.countdownTimer) { clearInterval(S.countdownTimer); S.countdownTimer = null; }
  }

  /* ----------------------------------------------------------- olay baglar */

  function bindPlayerButtons() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-kick]"), function (btn) {
      btn.onclick = function () { send({ type: "kick", player_id: btn.getAttribute("data-kick") }); };
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-vote]"), function (btn) {
      btn.onclick = function () { send({ type: "vote", target_id: btn.getAttribute("data-vote") }); };
    });
  }

  function bindRoleCard() {
    var toggle = el("btn-toggle-word");
    if (!toggle) { return; }
    toggle.onclick = function () {
      S.wordHidden = !S.wordHidden;
      ["secret-word", "secret-hint"].forEach(function (id) {
        var node = el(id);
        if (node) { node.classList.toggle("blurred", S.wordHidden); }
      });
      toggle.textContent = S.wordHidden ? "👁️ Göster" : "🙈 Gizle";
    };
  }

  function bindActionPanel() {
    var wordInput = el("input-word");
    var sendWordBtn = el("btn-send-word");
    if (wordInput && sendWordBtn) {
      var submitWord = function () {
        var value = wordInput.value.trim();
        if (!value) { toast("Bir kelime yaz.", "error"); return; }
        if (/\s/.test(value)) { toast("Sadece TEK kelime yazabilirsin.", "error"); return; }
        if (value.length < 2 || value.length > 24) { toast("Kelime 2-24 karakter olmalı.", "error"); return; }
        if (/[0-9_]/.test(value)) { toast("Kelime sadece harf içermeli.", "error"); return; }
        send({ type: "submit_word", word: value });
        wordInput.value = "";
      };
      sendWordBtn.onclick = submitWord;
      wordInput.onkeydown = function (e) { if (e.key === "Enter") { e.preventDefault(); submitWord(); } };
      wordInput.focus();
    }

    var guessInput = el("input-guess");
    var guessBtn = el("btn-send-guess");
    if (guessInput && guessBtn) {
      var submitGuess = function () {
        var value = guessInput.value.trim();
        if (!value) { toast("Bir tahmin yaz.", "error"); return; }
        guessBtn.disabled = true;
        send({ type: "guess", word: value });
      };
      guessBtn.onclick = submitGuess;
      guessInput.onkeydown = function (e) { if (e.key === "Enter") { e.preventDefault(); submitGuess(); } };
      guessInput.focus();
    }

    var skipGuess = el("btn-skip-guess");
    if (skipGuess) { skipGuess.onclick = function () { send({ type: "skip_guess" }); }; }

    var skipTurn = el("btn-skip-turn");
    if (skipTurn) { skipTurn.onclick = function () { send({ type: "skip_turn" }); }; }

    var startVoting = el("btn-start-voting");
    if (startVoting) {
      startVoting.onclick = function () {
        if (S.state && S.state.phase === "playing" &&
            !confirm("Kelime turlarını bitirip oylamaya geçilsin mi?")) { return; }
        send({ type: "start_voting" });
      };
    }

    var again = el("btn-play-again");
    if (again) { again.onclick = function () { send({ type: "play_again" }); }; }
  }

  /* =========================================================================
     TEK TELEFON (ELDEN ELE) MODU — sunucu kullanmaz
     ========================================================================= */

  function singleReset(keepNames) {
    var names = keepNames ? SM.names.slice() : ["", "", "", ""];
    var players = keepNames ? SM.players.slice() : [];
    var recent = SM.recent.slice();
    SM.step = "setup";
    SM.names = names;
    SM.players = players;
    SM.word = "";
    SM.imposter = -1;
    SM.revealIndex = 0;
    SM.revealed = false;
    SM.voteIndex = 0;
    SM.voteReady = false;
    SM.votes = [];
    SM.guessReady = false;
    SM.result = null;
    SM.recent = recent;
    SM.busy = false;
  }

  function singleOpen() {
    SM.active = true;
    if (!SM.players.length) { singleReset(false); }
    resetRoomLocal();
    render();
  }

  function singleExit() {
    SM.active = false;
    singleReset(false);
    render();
  }

  function singleReadNames() {
    var inputs = document.querySelectorAll("[data-sname]");
    var list = [];
    Array.prototype.forEach.call(inputs, function (input) {
      list.push(input.value.replace(/\s+/g, " ").trim().slice(0, 16));
    });
    if (list.length) { SM.names = list; }
  }

  function singleStartRound(keepPlayers) {
    singleReadNames();
    var names = SM.names.map(function (n) { return (n || "").trim(); }).filter(function (n) { return n.length > 0; });
    if (!keepPlayers) {
      if (names.length < MIN_PLAYERS) {
        toast("En az " + MIN_PLAYERS + " oyuncu ismi gir.", "error");
        return;
      }
      var seen = {};
      for (var i = 0; i < names.length; i += 1) {
        var key = trLower(names[i]);
        if (seen[key]) { toast("Aynı isim iki kez var: " + names[i], "error"); return; }
        seen[key] = true;
      }
      SM.players = names.map(function (n) { return { name: n, score: 0 }; });
    }
    if (SM.players.length < MIN_PLAYERS) { toast("Yeterli oyuncu yok.", "error"); return; }
    if (SM.busy) { return; }
    SM.busy = true;

    var url = "/api/word";
    if (SM.recent.length) { url += "?exclude=" + encodeURIComponent(SM.recent.join(",")); }
    fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) { throw new Error("http " + r.status); }
      return r.json();
    }).then(function (data) {
      SM.busy = false;
      if (!data || !data.word) { throw new Error("bos cevap"); }
      SM.word = data.word;
      SM.recent.push(data.word);
      if (SM.recent.length > 60) { SM.recent.shift(); }
      SM.imposter = Math.floor(Math.random() * SM.players.length);
      SM.votes = new Array(SM.players.length);
      SM.revealIndex = 0;
      SM.revealed = false;
      SM.voteIndex = 0;
      SM.voteReady = false;
      SM.guessReady = false;
      SM.result = null;
      SM.step = "reveal";
      renderSingle();
    }).catch(function () {
      SM.busy = false;
      toast("Kelime alınamadı, bağlantını kontrol et.", "error");
    });
  }

  function singleFinish(guessText) {
    var tally = {};
    var i;
    for (i = 0; i < SM.votes.length; i += 1) {
      var target = SM.votes[i];
      if (typeof target === "number") { tally[target] = (tally[target] || 0) + 1; }
    }
    var totalVotes = 0;
    var topCount = 0;
    var leaders = [];
    Object.keys(tally).forEach(function (key) {
      totalVotes += tally[key];
      if (tally[key] > topCount) { topCount = tally[key]; }
    });
    Object.keys(tally).forEach(function (key) {
      if (tally[key] === topCount && topCount > 0) { leaders.push(parseInt(key, 10)); }
    });

    var majority = totalVotes > 0 && topCount * 2 > totalVotes;
    var caught = majority && leaders.length === 1 && leaders[0] === SM.imposter;
    var guess = (guessText || "").trim();
    var guessCorrect = !!guess && normWord(guess) === normWord(SM.word);
    var winner = (caught && !guessCorrect) ? "crew" : "imposter";

    if (winner === "crew") {
      for (i = 0; i < SM.players.length; i += 1) {
        if (i !== SM.imposter) { SM.players[i].score += 2; }
      }
    } else {
      SM.players[SM.imposter].score += guessCorrect ? 3 : 2;
      for (i = 0; i < SM.players.length; i += 1) {
        if (i !== SM.imposter && SM.votes[i] === SM.imposter) { SM.players[i].score += 1; }
      }
    }

    var reason;
    if (guessCorrect) { reason = "Kamuflaj gizli kelimeyi doğru tahmin etti: “" + SM.word + "”"; }
    else if (caught) { reason = "Oylamada köstebek doğru bulundu ve tahmini tutmadı."; }
    else if (majority && leaders.length === 1) {
      reason = "Çoğunluk " + SM.players[leaders[0]].name + " oyuncusunu suçladı ama köstebek o değildi.";
    } else if (totalVotes === 0) { reason = "Hiç oy kullanılmadı, köstebek rahatça kaçtı."; }
    else { reason = "Oylar bölündü, çoğunluk sağlanamadı ve köstebek yakalanamadı."; }

    var counts = leaders.length ? null : null;
    var voteCounts = Object.keys(tally).map(function (key) {
      var idx = parseInt(key, 10);
      return { name: SM.players[idx].name, count: tally[key], is_imposter: idx === SM.imposter };
    }).sort(function (a, b) { return b.count - a.count; });

    SM.result = {
      winner: winner,
      winner_label: winner === "imposter" ? "Kamuflaj kazandı!" : "Dedektifler kazandı!",
      imposter_name: SM.players[SM.imposter].name,
      imposter_id: "imposter",
      secret_word: SM.word,
      guess: guess || null,
      guess_correct: guessCorrect,
      caught: caught,
      reason: reason,
      vote_counts: voteCounts,
      votes: SM.players.map(function (p, idx) {
        var t = SM.votes[idx];
        return {
          voter: p.name,
          target: typeof t === "number" ? SM.players[t].name : "—",
          correct: t === SM.imposter
        };
      })
    };
    SM.step = "result";
    renderSingle();
  }

  function singleCardBig(title, subtitle, buttonId, buttonText, tone) {
    var toneClass = tone === "red" ? "border-rose-500/50 bg-rose-500/10 glow-red"
      : (tone === "green" ? "border-emerald-500/50 bg-emerald-500/10 glow-green" : "border-edge bg-panel/80");
    return '<div class="animate-pop rounded-2xl border p-6 text-center ' + toneClass + '">' +
      '<h2 class="text-2xl font-black sm:text-3xl">' + title + '</h2>' +
      (subtitle ? '<p class="mx-auto mt-3 max-w-sm text-sm text-slate-300">' + subtitle + '</p>' : "") +
      '<button id="' + buttonId + '" class="tap mt-6 w-full rounded-xl bg-emerald-500 px-4 py-4 text-base font-black text-emerald-950 transition hover:bg-emerald-400 active:scale-[.98]">' +
      buttonText + '</button></div>';
  }

  function renderSingle() {
    var panel = el("single-panel");
    if (!panel) { return; }

    if (SM.step === "setup") {
      var rows = SM.names.map(function (name, idx) {
        return '<div class="flex gap-2">' +
          '<input data-sname="' + idx + '" type="text" maxlength="16" value="' + esc(name) + '" placeholder="' + (idx + 1) + '. oyuncu"' +
            ' class="w-full rounded-xl border border-edge bg-ink/70 px-4 py-3 text-base font-semibold placeholder:text-slate-600 focus:border-emerald-500/70" />' +
          (SM.names.length > MIN_PLAYERS
            ? '<button data-sremove="' + idx + '" class="tap shrink-0 rounded-xl border border-edge px-3 text-sm font-bold text-slate-500 transition hover:border-rose-500/60 hover:text-rose-300">✕</button>'
            : "") +
          '</div>';
      }).join("");

      panel.innerHTML = '<div class="animate-pop rounded-2xl border border-edge bg-panel/80 p-5">' +
        '<h2 class="text-xl font-black">Elden Ele · Oyuncular</h2>' +
        '<p class="mt-1 text-sm text-slate-400">İsimleri gir. Telefon sırayla elden ele dolaşacak.</p>' +
        '<div class="mt-4 space-y-2">' + rows + '</div>' +
        (SM.names.length < MAX_PLAYERS
          ? '<button id="btn-sadd" class="tap mt-3 w-full rounded-xl border border-dashed border-edge px-4 py-3 text-sm font-bold text-slate-400 transition hover:border-emerald-500/60 hover:text-emerald-300">+ Oyuncu Ekle</button>'
          : "") +
        '<button id="btn-sgo" class="tap mt-4 w-full rounded-xl bg-emerald-500 px-4 py-4 text-base font-black text-emerald-950 transition hover:bg-emerald-400 active:scale-[.98]">Oyunu Başlat</button>' +
        '<button id="btn-sback" class="tap mt-2 w-full rounded-xl border border-edge px-4 py-3 text-sm font-bold text-slate-400 transition hover:text-slate-200">Ana sayfaya dön</button>' +
        '</div>';

      Array.prototype.forEach.call(panel.querySelectorAll("[data-sname]"), function (input) {
        input.oninput = function () {
          SM.names[parseInt(input.getAttribute("data-sname"), 10)] = input.value;
        };
      });
      Array.prototype.forEach.call(panel.querySelectorAll("[data-sremove]"), function (btn) {
        btn.onclick = function () {
          singleReadNames();
          SM.names.splice(parseInt(btn.getAttribute("data-sremove"), 10), 1);
          renderSingle();
        };
      });
      if (el("btn-sadd")) {
        el("btn-sadd").onclick = function () { singleReadNames(); SM.names.push(""); renderSingle(); };
      }
      el("btn-sgo").onclick = function () { singleStartRound(false); };
      el("btn-sback").onclick = function () { singleExit(); };
      return;
    }

    if (SM.step === "reveal") {
      var player = SM.players[SM.revealIndex];
      var isLast = SM.revealIndex === SM.players.length - 1;
      var next = isLast ? null : SM.players[SM.revealIndex + 1];

      if (!SM.revealed) {
        panel.innerHTML = singleCardBig(
          esc(player.name) + ", telefonu al 📱",
          "Hazır olduğunda <b>Göster</b>'e bas. Başkası ekrana bakmasın!",
          "btn-sreveal", "Göster", "neutral"
        ) + '<p class="mt-3 text-center text-xs text-slate-500">' + (SM.revealIndex + 1) + " / " + SM.players.length + ' oyuncu</p>';
        el("btn-sreveal").onclick = function () { SM.revealed = true; renderSingle(); };
        return;
      }

      var isImposter = SM.revealIndex === SM.imposter;
      var body = isImposter
        ? '<div class="animate-pop rounded-2xl border border-rose-500/50 bg-gradient-to-br from-rose-500/15 to-rose-900/10 p-6 text-center glow-red">' +
          '<p class="text-xs font-bold uppercase tracking-[.2em] text-rose-300">' + esc(player.name) + '</p>' +
          '<h2 class="mt-2 text-3xl font-black text-rose-200 sm:text-4xl">SEN KAMUFLAJSIN 🥸</h2>' +
          '<p class="mx-auto mt-3 max-w-sm text-sm text-rose-100/80">Gizli kelimeyi bilmiyorsun. Diğerlerinin söylediği kelimelerden anlamaya çalış ve yakalanma.</p></div>'
        : '<div class="animate-pop rounded-2xl border border-emerald-500/50 bg-gradient-to-br from-emerald-500/15 to-emerald-900/10 p-6 text-center glow-green">' +
          '<p class="text-xs font-bold uppercase tracking-[.2em] text-emerald-300">' + esc(player.name) + ' · gizli kelime</p>' +
          '<h2 class="mt-2 break-words text-3xl font-black text-emerald-100 sm:text-4xl">' + esc(SM.word) + '</h2>' +
          '<p class="mt-3 text-sm text-emerald-100/70">Kelimeyi çağrıştıran ama çok açık etmeyen tek bir kelime söyleyeceksin.</p></div>';

      panel.innerHTML = body +
        '<button id="btn-shide" class="tap mt-4 w-full rounded-xl bg-slate-700 px-4 py-4 text-base font-black text-white transition hover:bg-slate-600 active:scale-[.98]">' +
        (isLast ? "🙈 Gizle ve Konuşmayı Başlat" : "🙈 Gizle ve " + esc(next.name) + "'e Ver") + '</button>';

      el("btn-shide").onclick = function () {
        SM.revealed = false;
        if (isLast) { SM.step = "talking"; } else { SM.revealIndex += 1; }
        renderSingle();
      };
      return;
    }

    if (SM.step === "talking") {
      panel.innerHTML = '<div class="animate-pop rounded-2xl border border-amber-400/50 bg-amber-400/10 p-6 text-center">' +
        '<h2 class="text-3xl font-black text-amber-200">Konuşma Başladı! 🗣️</h2>' +
        '<p class="mx-auto mt-3 max-w-sm text-sm text-amber-100/80">' +
        'Sırayla herkes gizli kelimeyi çağrıştıran <b>tek bir kelime</b> söylesin. ' +
        'İstediğiniz kadar tur yapın, sonra oylamaya geçin.</p>' +
        '<div class="mt-4 flex flex-wrap justify-center gap-2">' +
        SM.players.map(function (p) {
          return '<span class="rounded-lg border border-edge bg-ink/50 px-3 py-1.5 text-sm font-bold text-slate-200">' + esc(p.name) + '</span>';
        }).join("") +
        '</div>' +
        '<button id="btn-svote" class="tap mt-6 w-full rounded-xl bg-indigo-500 px-4 py-4 text-base font-black text-white transition hover:bg-indigo-400 active:scale-[.98]">🗳️ Oylamaya Geç</button>' +
        '</div>';
      el("btn-svote").onclick = function () {
        SM.step = "vote";
        SM.voteIndex = 0;
        SM.voteReady = false;
        renderSingle();
      };
      return;
    }

    if (SM.step === "vote") {
      var voter = SM.players[SM.voteIndex];
      if (!SM.voteReady) {
        panel.innerHTML = singleCardBig(
          esc(voter.name) + ", oy sırası sende 🗳️",
          "Telefonu al, <b>Hazırım</b>'a bas ve köstebek olduğunu düşündüğün kişiyi seç.",
          "btn-svready", "Hazırım", "neutral"
        ) + '<p class="mt-3 text-center text-xs text-slate-500">' + (SM.voteIndex + 1) + " / " + SM.players.length + ' oy</p>';
        el("btn-svready").onclick = function () { SM.voteReady = true; renderSingle(); };
        return;
      }

      var options = SM.players.map(function (p, idx) {
        if (idx === SM.voteIndex) { return ""; }
        return '<button data-svote="' + idx + '" class="tap flex items-center justify-between rounded-xl border border-edge bg-ink/50 px-4 py-3.5 text-left transition hover:border-rose-500/50 hover:bg-rose-500/10">' +
          '<span class="font-bold text-slate-200">' + esc(p.name) + '</span>' +
          '<span class="text-xs font-bold text-slate-500">şüpheli</span></button>';
      }).join("");

      panel.innerHTML = '<div class="animate-pop rounded-2xl border border-edge bg-panel/80 p-5">' +
        '<h2 class="text-xl font-black">' + esc(voter.name) + ' · köstebek kim?</h2>' +
        '<p class="mt-1 text-sm text-slate-400">Seçimini yap, telefon bir sonraki oyuncuya geçecek.</p>' +
        '<div class="mt-4 grid gap-2">' + options + '</div></div>';

      Array.prototype.forEach.call(panel.querySelectorAll("[data-svote]"), function (btn) {
        btn.onclick = function () {
          SM.votes[SM.voteIndex] = parseInt(btn.getAttribute("data-svote"), 10);
          SM.voteReady = false;
          if (SM.voteIndex === SM.players.length - 1) {
            SM.step = "guess";
          } else {
            SM.voteIndex += 1;
          }
          renderSingle();
        };
      });
      return;
    }

    if (SM.step === "guess") {
      var imposterName = SM.players[SM.imposter].name;
      if (!SM.guessReady) {
        panel.innerHTML = singleCardBig(
          "Oylar tamam! 🥸",
          "<b>" + esc(imposterName) + "</b> (Kamuflaj) telefonu alsın. Gizli kelimeyi tek seferde doğru tahmin ederse yakalansa bile kazanır.",
          "btn-sgready", esc(imposterName) + ", hazırım", "red"
        );
        el("btn-sgready").onclick = function () { SM.guessReady = true; renderSingle(); };
        return;
      }
      panel.innerHTML = '<div class="animate-pop rounded-2xl border border-rose-500/50 bg-panel/80 p-5">' +
        '<h2 class="text-xl font-black text-rose-200">' + esc(imposterName) + ', gizli kelime ne?</h2>' +
        '<p class="mt-1 text-sm text-slate-400">Tek hakkın var.</p>' +
        '<input id="input-sguess" type="text" maxlength="40" autocomplete="off" spellcheck="false" placeholder="gizli kelime"' +
          ' class="mt-3 w-full rounded-xl border border-edge bg-ink/70 px-4 py-3 text-base font-semibold placeholder:text-slate-600 focus:border-rose-500/70" />' +
        '<button id="btn-sguess" class="tap mt-3 w-full rounded-xl bg-rose-500 px-4 py-4 text-base font-black text-white transition hover:bg-rose-400 active:scale-[.98]">Tahmin Et</button>' +
        '<button id="btn-sskip" class="tap mt-2 w-full rounded-xl border border-edge px-4 py-3 text-sm font-bold text-slate-400 transition hover:text-slate-200">Tahmin etmeden sonucu gör</button>' +
        '</div>';
      var input = el("input-sguess");
      input.focus();
      el("btn-sguess").onclick = function () {
        var value = input.value.trim();
        if (!value) { toast("Bir tahmin yaz.", "error"); return; }
        singleFinish(value);
      };
      input.onkeydown = function (e) { if (e.key === "Enter") { e.preventDefault(); el("btn-sguess").click(); } };
      el("btn-sskip").onclick = function () { singleFinish(""); };
      return;
    }

    if (SM.step === "result") {
      var r = SM.result;
      var counts = r.vote_counts.map(function (row) {
        return '<li class="flex items-center justify-between rounded-lg border border-edge bg-ink/40 px-3 py-2">' +
          '<span class="font-bold ' + (row.is_imposter ? 'text-rose-300' : 'text-slate-200') + '">' +
          esc(row.name) + (row.is_imposter ? " 🥸" : "") + '</span>' +
          '<span class="text-xs font-bold text-slate-400">' + row.count + ' oy</span></li>';
      }).join("") || '<li class="rounded-lg border border-edge bg-ink/40 px-3 py-2 text-xs text-slate-500">Hiç oy kullanılmadı.</li>';

      var detail = r.votes.map(function (v) {
        return '<li class="flex items-center gap-2 text-xs"><span class="text-slate-300">' + esc(v.voter) + '</span>' +
          '<span class="text-slate-600">→</span><span class="' + (v.correct ? 'text-emerald-300' : 'text-slate-400') + '">' +
          esc(v.target) + '</span>' + (v.correct ? '<span class="text-emerald-400">✓</span>' : '') + '</li>';
      }).join("");

      var scores = SM.players.slice().sort(function (a, b) { return b.score - a.score; }).map(function (p) {
        return '<li class="flex items-center justify-between rounded-lg border border-edge bg-ink/40 px-3 py-2">' +
          '<span class="text-sm font-bold text-slate-200">' + esc(p.name) + '</span>' +
          '<span class="text-sm font-black text-emerald-300">' + p.score + '</span></li>';
      }).join("");

      panel.innerHTML = resultCardHtml(r, "") +
        '<div class="mt-4 rounded-2xl border border-edge bg-panel/80 p-5">' +
          '<p class="text-sm font-bold text-slate-200">Oylama dökümü</p>' +
          '<ul class="mt-3 space-y-2">' + counts + '</ul>' +
          '<ul class="mt-4 space-y-1 border-t border-edge pt-3">' + detail + '</ul>' +
          '<p class="mt-5 text-sm font-bold text-slate-200">Puan tablosu</p>' +
          '<ul class="mt-2 space-y-2">' + scores + '</ul>' +
          '<button id="btn-snew" class="tap mt-5 w-full rounded-xl bg-emerald-500 px-4 py-4 text-base font-black text-emerald-950 transition hover:bg-emerald-400 active:scale-[.98]">Yeni Oyun (aynı oyuncular)</button>' +
          '<button id="btn-splayers" class="tap mt-2 w-full rounded-xl border border-edge px-4 py-3 text-sm font-bold text-slate-400 transition hover:text-slate-200">Oyuncuları Değiştir</button>' +
        '</div>';

      el("btn-snew").onclick = function () { singleStartRound(true); };
      el("btn-splayers").onclick = function () {
        SM.names = SM.players.map(function (p) { return p.name; });
        SM.step = "setup";
        renderSingle();
      };
      return;
    }
  }

  /* ------------------------------------------------------- sabit arayuz */

  function syncHomeMode() {
    Array.prototype.forEach.call(document.querySelectorAll(".mode-card"), function (card) {
      if (card.getAttribute("data-mode") === S.homeMode) { card.setAttribute("data-selected", "1"); }
      else { card.removeAttribute("data-selected"); }
    });
    var single = S.homeMode === "single";
    el("home-ws").classList.toggle("hidden", single);
    el("home-single").classList.toggle("hidden", !single);
    el("home-name-wrap").classList.toggle("hidden", single);
    el("home-rounds-wrap").classList.toggle("hidden", S.homeMode !== "online");
  }

  function inviteLink() {
    return location.origin + "/?room=" + (S.state ? S.state.code : "");
  }

  function leaveRoom() {
    if (S.state) { send({ type: "leave" }); }
    resetRoomLocal();
    closeSocket();
    render();
  }

  function bindStaticUi() {
    var nameInput = el("input-name");
    var codeInput = el("input-code");
    if (S.name && nameInput) { nameInput.value = S.name; }

    Array.prototype.forEach.call(document.querySelectorAll(".mode-card"), function (card) {
      card.onclick = function () {
        S.homeMode = card.getAttribute("data-mode") || "online";
        store(MODE_KEY, S.homeMode);
        syncHomeMode();
      };
    });

    codeInput.addEventListener("input", function () {
      codeInput.value = codeInput.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 4);
    });

    function currentName() {
      var value = (nameInput.value || "").trim().replace(/\s+/g, " ").slice(0, 16);
      if (!value) { toast("Önce bir kullanıcı adı gir.", "error"); nameInput.focus(); return null; }
      S.name = value;
      store(NAME_KEY, value);
      return value;
    }

    el("btn-create").onclick = function () {
      var name = currentName();
      if (!name) { return; }
      send({
        type: "create_room",
        name: name,
        mode: S.homeMode === "local" ? "local" : "online",
        rounds: parseInt(el("select-rounds-home").value, 10) || 2
      });
    };

    el("btn-join").onclick = function () {
      var name = currentName();
      if (!name) { return; }
      var code = (codeInput.value || "").trim().toUpperCase();
      if (code.length !== 4) { toast("Oda kodu 4 karakter olmalı.", "error"); codeInput.focus(); return; }
      send({ type: "join_room", code: code, name: name });
    };

    el("btn-single-start").onclick = function () { singleOpen(); };

    nameInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        if ((codeInput.value || "").length === 4) { el("btn-join").click(); } else { el("btn-create").click(); }
      }
    });
    codeInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); el("btn-join").click(); }
    });

    el("select-rounds").onchange = function () {
      send({ type: "set_rounds", rounds: parseInt(el("select-rounds").value, 10) });
    };
    el("btn-start").onclick = function () { send({ type: "start_game" }); };
    el("btn-copy-code").onclick = function () { copyText(S.state ? S.state.code : "", "Oda kodu kopyalandı."); };
    el("btn-copy-link2").onclick = function () { copyText(inviteLink(), "Davet linki kopyalandı."); };
    el("btn-copy-link").onclick = function () { copyText(inviteLink(), "Davet linki kopyalandı."); };

    // Logo = odadan cik / ana sayfa
    el("btn-home").onclick = function () {
      if (SM.active) {
        if (SM.step !== "setup" && !confirm("Devam eden oyun silinsin ve ana sayfaya dönülsün mü?")) { return; }
        singleExit();
        return;
      }
      if (S.state) { leaveRoom(); return; }
      showScreen("home");
      syncHomeMode();
    };

    // Sekme kapanirken sunucuya haber ver (host ise oda silinir)
    window.addEventListener("pagehide", function () {
      if (S.state && S.ws && S.ws.readyState === 1) {
        try { S.ws.send(JSON.stringify({ type: "leave" })); } catch (e) { /* yok */ }
      }
    });

    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && !SM.active && (!S.ws || S.ws.readyState > 1)) { connect(); }
    });
    window.addEventListener("online", function () { if (!SM.active) { connect(); } });

    setInterval(function () {
      if (S.open && S.ws && S.ws.readyState === 1) {
        S.ws.send(JSON.stringify({ type: "ping", t: Date.now() }));
      }
    }, 25000);
  }

  /* ---------------------------------------------------------- baslangic */

  function boot() {
    S.session = loadSession();
    S.name = read(NAME_KEY) || "";
    var savedMode = read(MODE_KEY);
    if (savedMode === "online" || savedMode === "local" || savedMode === "single") { S.homeMode = savedMode; }

    bindStaticUi();
    showScreen("home");
    syncHomeMode();

    var params = new URLSearchParams(location.search);
    var roomParam = (params.get("room") || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 4);
    if (roomParam) {
      el("input-code").value = roomParam;
      if (S.homeMode === "single") { S.homeMode = "online"; syncHomeMode(); }
    }

    connect();

    if (!S.session && roomParam && S.name) {
      send({ type: "join_room", code: roomParam, name: S.name });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
