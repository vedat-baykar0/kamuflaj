"""
Kamuflaj (Camouflage)
=====================

Gercek zamanli, tarayici tabanli "Spyfall / Imposter" tarzi parti oyunu.

Mimari
------
* FastAPI + tek bir WebSocket endpoint (`/ws`) uzerinden tum oyun trafigi.
* Butun oyun durumu sunucu tarafinda (bellekte) tutulur; istemci yalnizca
  kendisine ait kisisel bilgiyi (rol / gizli kelime) gorur. Kostebegin kimligi
  oyun bitmeden ASLA diger oyunculara gonderilmez.
* Her degisiklikten sonra her oyuncuya kisiselestirilmis bir tam durum
  anlik goruntusu (`state`) yayinlanir. Bu sayede istemcide karmasik
  "incremental update" mantigina ihtiyac kalmaz; yeniden baglanan oyuncu
  aninda dogru ekrani gorur.
* Oyuncular `player_id` + `token` ikilisiyle yeniden baglanabilir (sayfa
  yenileme, mobil ag kopmasi, tunel degisimi vs.).

Calistirma
----------
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from words import WORDS, pick_word, tr_lower

# ---------------------------------------------------------------------------
# Ayarlar
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

MIN_PLAYERS = 3                 # oyunu baslatmak icin gereken en az oyuncu
MAX_PLAYERS = 12                # bir odadaki en fazla oyuncu
MAX_NAME_LEN = 16
ROOM_CODE_LEN = 4
ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPRSTUVWXYZ23456789"  # I, O, Q gibi karisanlar yok
ALLOWED_ROUNDS = (1, 2, 3, 4)   # oyuncu basina kac kelime soylenecek
DEFAULT_ROUNDS = 2
GUESS_SECONDS = 45              # kostebegin kelimeyi tahmin suresi
ROOM_IDLE_TTL = 1800.0          # tamamen bos odalar 30 dk sonra silinir
MAX_LOG_ENTRIES = 60
MAX_ROOMS = 4000
RATE_WINDOW = 5.0
RATE_MAX_MESSAGES = 40
RECENT_SECRET_MEMORY = 80       # oda basina tekrar edilmeyecek son kelime sayisi

# Tek kelime kurali: yalnizca harf, 2-24 karakter (Turkce karakterler dahil)
WORD_PATTERN = re.compile(r"^[^\W\d_]{2,24}$", re.UNICODE)
# Normalizasyon: harf/rakam disindaki her sey atilir (bosluk, tire, noktalama)
NON_WORD_PATTERN = re.compile(r"[^\w]", re.UNICODE)
CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")

PHASE_LOBBY = "lobby"
PHASE_PLAYING = "playing"
PHASE_VOTING = "voting"
PHASE_GUESSING = "guessing"
PHASE_ENDED = "ended"


# ---------------------------------------------------------------------------
# Yardimcilar
# ---------------------------------------------------------------------------


def normalize_word(text: Any) -> str:
    """Kelime karsilastirmalari icin sadelestirilmis anahtar uretir."""
    if not isinstance(text, str):
        return ""
    return NON_WORD_PATTERN.sub("", tr_lower(text.strip()))


def clean_name(raw: Any) -> str:
    """Kullanici adini guvenli hale getirir (kontrol karakteri, uzunluk)."""
    if not isinstance(raw, str):
        return ""
    name = CONTROL_PATTERN.sub("", raw)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:MAX_NAME_LEN]


def clean_code(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    return re.sub(r"[^A-Z0-9]", "", raw.strip().upper())[:ROOM_CODE_LEN]


def error_payload(code: str, message: str) -> Dict[str, Any]:
    return {"type": "error", "code": code, "message": message}


# ---------------------------------------------------------------------------
# Veri modelleri
# ---------------------------------------------------------------------------


@dataclass
class Player:
    id: str
    name: str
    token: str
    ws: Optional[WebSocket] = None
    connected: bool = False
    in_game: bool = False          # bu el icinde oynuyor mu (sonradan gelen: False)
    score: int = 0
    joined_at: float = field(default_factory=time.time)


@dataclass
class Room:
    code: str
    host_id: Optional[str] = None
    players: Dict[str, Player] = field(default_factory=dict)
    seats: List[str] = field(default_factory=list)           # katilim sirasi
    phase: str = PHASE_LOBBY
    rounds_total: int = DEFAULT_ROUNDS
    order: List[str] = field(default_factory=list)            # tur sirasi (karisik)
    turn_counter: int = 0
    round_no: int = 0
    secret_word: str = ""
    imposter_id: Optional[str] = None
    words: List[Dict[str, Any]] = field(default_factory=list)
    used_words: Set[str] = field(default_factory=set)
    votes: Dict[str, str] = field(default_factory=dict)       # oy veren -> oylanan
    guess_text: Optional[str] = None
    guess_deadline: Optional[float] = None
    guess_task: Optional[asyncio.Task] = None
    result: Optional[Dict[str, Any]] = None
    recent_secrets: List[str] = field(default_factory=list)
    log: List[Dict[str, Any]] = field(default_factory=list)
    games_played: int = 0
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # -- yardimcilar ------------------------------------------------------
    def touch(self) -> None:
        self.last_active = time.time()

    def ordered_players(self) -> List[Player]:
        return [self.players[pid] for pid in self.seats if pid in self.players]

    def connected_players(self) -> List[Player]:
        return [p for p in self.ordered_players() if p.connected]

    def active_players(self) -> List[Player]:
        """Bu elde oynayan VE bagli olan oyuncular."""
        return [p for p in self.ordered_players() if p.in_game and p.connected]

    @property
    def total_turns(self) -> int:
        return len(self.order) * self.rounds_total

    def current_turn_id(self) -> Optional[str]:
        if self.phase != PHASE_PLAYING or not self.order:
            return None
        if self.turn_counter >= self.total_turns:
            return None
        return self.order[self.turn_counter % len(self.order)]

    def add_log(self, text: str, kind: str = "info") -> None:
        self.log.append({"t": int(time.time() * 1000), "kind": kind, "text": text})
        if len(self.log) > MAX_LOG_ENTRIES:
            del self.log[: len(self.log) - MAX_LOG_ENTRIES]

    def unique_name(self, desired: str) -> str:
        taken = {tr_lower(p.name) for p in self.players.values()}
        if tr_lower(desired) not in taken:
            return desired
        for i in range(2, MAX_PLAYERS + 50):
            candidate = f"{desired} ({i})"
            if tr_lower(candidate) not in taken:
                return candidate
        return f"{desired} ({secrets.randbelow(999)})"


ROOMS: Dict[str, Room] = {}
ROOMS_LOCK = asyncio.Lock()


class Connection:
    """Tek bir WebSocket baglantisinin durumu."""

    __slots__ = ("ws", "room_code", "player_id", "_stamps")

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.room_code: Optional[str] = None
        self.player_id: Optional[str] = None
        self._stamps: List[float] = []

    def allow(self) -> bool:
        now = time.monotonic()
        self._stamps = [t for t in self._stamps if now - t < RATE_WINDOW]
        if len(self._stamps) >= RATE_MAX_MESSAGES:
            return False
        self._stamps.append(now)
        return True

    async def send(self, payload: Dict[str, Any]) -> None:
        try:
            await self.ws.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Durum serilestirme (her oyuncuya kisisel goruntu)
# ---------------------------------------------------------------------------


def serialize_for(room: Room, viewer: Player) -> Dict[str, Any]:
    finished = room.phase == PHASE_ENDED
    in_round = room.phase in (PHASE_PLAYING, PHASE_VOTING, PHASE_GUESSING)
    turn_id = room.current_turn_id()

    word_counts: Dict[str, int] = {}
    for entry in room.words:
        word_counts[entry["player_id"]] = word_counts.get(entry["player_id"], 0) + 1

    players_payload: List[Dict[str, Any]] = []
    for p in room.ordered_players():
        players_payload.append({
            "id": p.id,
            "name": p.name,
            "connected": p.connected,
            "is_host": p.id == room.host_id,
            "in_game": p.in_game,
            "score": p.score,
            "words": word_counts.get(p.id, 0),
            "is_turn": p.id == turn_id,
            "has_voted": p.id in room.votes,
            # Kostebek kimligi yalnizca oyun bittiginde aciklanir.
            "is_imposter": finished and p.id == room.imposter_id,
            "is_you": p.id == viewer.id,
        })

    viewer_is_imposter = bool(
        room.imposter_id and viewer.id == room.imposter_id and room.phase != PHASE_LOBBY
    )
    secret_for_viewer: Optional[str] = None
    if finished:
        secret_for_viewer = room.secret_word or None
    elif in_round and viewer.in_game and not viewer_is_imposter:
        secret_for_viewer = room.secret_word or None

    guess_remaining: Optional[int] = None
    if room.phase == PHASE_GUESSING and room.guess_deadline:
        guess_remaining = max(0, int(round(room.guess_deadline - time.time())))

    state = {
        "code": room.code,
        "phase": room.phase,
        "host_id": room.host_id,
        "rounds_total": room.rounds_total,
        "round_no": room.round_no,
        "round_options": list(ALLOWED_ROUNDS),
        "min_players": MIN_PLAYERS,
        "max_players": MAX_PLAYERS,
        "players": players_payload,
        "words": room.words,
        "turn_player_id": turn_id,
        "turns_done": min(room.turn_counter, room.total_turns),
        "turns_total": room.total_turns,
        "votes_cast": sum(1 for pid in room.votes if pid in room.players),
        "votes_needed": len(room.active_players()),
        "guess_remaining": guess_remaining,
        "guess_seconds": GUESS_SECONDS,
        "log": room.log[-MAX_LOG_ENTRIES:],
        "games_played": room.games_played,
        "result": room.result if finished else None,
        "word_pool_size": len(WORDS),
    }

    you = {
        "id": viewer.id,
        "name": viewer.name,
        "is_host": viewer.id == room.host_id,
        "in_game": viewer.in_game,
        "is_imposter": viewer_is_imposter,
        "secret_word": secret_for_viewer,
        "is_turn": turn_id == viewer.id,
        "voted_for": room.votes.get(viewer.id),
        "score": viewer.score,
        "can_vote": room.phase == PHASE_VOTING and viewer.in_game and viewer.connected,
        "votable_ids": [p.id for p in room.active_players() if p.id != viewer.id],
    }

    return {"type": "state", "state": state, "you": you}


async def send_to(player: Player, payload: Dict[str, Any]) -> None:
    ws = player.ws
    if ws is None:
        return
    try:
        await ws.send_text(json.dumps(payload, ensure_ascii=False))
    except Exception:
        # Yalnizca hala bu sockete bagliysa dusur (coklu sekme durumu)
        if player.ws is ws:
            player.ws = None
            player.connected = False


async def broadcast_state(room: Room) -> None:
    targets = [p for p in room.players.values() if p.ws is not None]
    if not targets:
        return
    await asyncio.gather(
        *(send_to(p, serialize_for(room, p)) for p in targets),
        return_exceptions=True,
    )


# ---------------------------------------------------------------------------
# Oyun mantigi
# ---------------------------------------------------------------------------


def new_room_code() -> str:
    for _ in range(500):
        code = "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LEN))
        if code not in ROOMS:
            return code
    while True:  # son care: kodu uzat
        code = "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LEN + 2))
        if code not in ROOMS:
            return code


def cancel_guess_timer(room: Room) -> None:
    task = room.guess_task
    room.guess_task = None
    if task is not None and not task.done():
        task.cancel()


def reset_to_lobby(room: Room) -> None:
    cancel_guess_timer(room)
    room.phase = PHASE_LOBBY
    room.order = []
    room.turn_counter = 0
    room.round_no = 0
    room.secret_word = ""
    room.imposter_id = None
    room.words = []
    room.used_words = set()
    room.votes = {}
    room.guess_text = None
    room.guess_deadline = None
    room.result = None
    for p in room.players.values():
        p.in_game = False


def start_game(room: Room) -> Optional[str]:
    """Yeni bir el baslatir. Hata varsa kullaniciya gosterilecek metni dondurur."""
    candidates = room.connected_players()
    if len(candidates) < MIN_PLAYERS:
        return f"Oyunu baslatmak icin en az {MIN_PLAYERS} bagli oyuncu gerekli."

    cancel_guess_timer(room)
    for p in room.players.values():
        p.in_game = p.connected

    order = [p.id for p in candidates]
    random.shuffle(order)
    room.order = order
    room.imposter_id = random.choice(order)
    room.secret_word = pick_word(room.recent_secrets)
    room.recent_secrets.append(normalize_word(room.secret_word))
    if len(room.recent_secrets) > RECENT_SECRET_MEMORY:
        del room.recent_secrets[: len(room.recent_secrets) - RECENT_SECRET_MEMORY]

    room.words = []
    room.used_words = set()
    room.votes = {}
    room.guess_text = None
    room.guess_deadline = None
    room.result = None
    room.turn_counter = 0
    room.round_no = 1
    room.phase = PHASE_PLAYING
    room.games_played += 1
    room.log = []
    room.add_log(
        f"Yeni oyun basladi. {len(order)} oyuncu, kisi basi {room.rounds_total} kelime.",
        "start",
    )
    first = room.players.get(order[0])
    if first is not None:
        room.add_log(f"Ilk sira: {first.name}", "turn")
    return None


def advance_turn(room: Room) -> None:
    """Sirayi sonraki bagli oyuncuya gecirir; tum turlar bittiyse oylamaya gecer."""
    total = room.total_turns
    size = len(room.order)
    if size == 0:
        begin_voting(room)
        return
    idx = room.turn_counter + 1
    while idx < total:
        pid = room.order[idx % size]
        p = room.players.get(pid)
        if p is not None and p.connected and p.in_game:
            room.turn_counter = idx
            room.round_no = idx // size + 1
            room.add_log(f"Sira {p.name} oyuncusunda.", "turn")
            return
        idx += 1
    room.turn_counter = total
    begin_voting(room)


def begin_voting(room: Room) -> None:
    room.phase = PHASE_VOTING
    room.votes = {}
    room.add_log("Kelime turlari bitti, oylama basladi!", "vote")
    if len(room.active_players()) < 2 or room.imposter_id not in room.players:
        abort_game(room, "Yeterli oyuncu kalmadigi icin oyun iptal edildi.")


def check_votes_complete(room: Room) -> None:
    if room.phase != PHASE_VOTING:
        return
    actives = room.active_players()
    if not actives:
        return
    if all(p.id in room.votes for p in actives):
        begin_guess_phase(room)


def begin_guess_phase(room: Room) -> None:
    imposter = room.players.get(room.imposter_id or "")
    if imposter is None or not imposter.connected:
        finish_game(room, None)
        return
    room.phase = PHASE_GUESSING
    room.guess_deadline = time.time() + GUESS_SECONDS
    room.add_log(
        f"Oylar toplandi. Kamuflaj'in gizli kelimeyi tahmin etmesi icin {GUESS_SECONDS} saniyesi var.",
        "guess",
    )
    cancel_guess_timer(room)
    room.guess_task = asyncio.create_task(guess_timeout(room.code))


async def guess_timeout(room_code: str) -> None:
    try:
        await asyncio.sleep(GUESS_SECONDS + 0.5)
    except asyncio.CancelledError:
        return
    room = ROOMS.get(room_code)
    if room is None:
        return
    async with room.lock:
        if room.phase != PHASE_GUESSING:
            return
        room.add_log("Kamuflaj'in tahmin suresi doldu.", "guess")
        finish_game(room, None)
        await broadcast_state(room)


def finish_game(room: Room, guess: Optional[str]) -> None:
    """Oylari sayar, kazanani belirler, puanlari dagitir ve sonucu olusturur."""
    cancel_guess_timer(room)
    room.guess_deadline = None

    tally: Dict[str, int] = {}
    vote_details: List[Dict[str, Any]] = []
    for voter_id, target_id in room.votes.items():
        voter = room.players.get(voter_id)
        target = room.players.get(target_id)
        if voter is None or target is None:
            continue
        tally[target_id] = tally.get(target_id, 0) + 1
        vote_details.append({
            "voter_id": voter_id,
            "voter": voter.name,
            "target_id": target_id,
            "target": target.name,
            "correct": target_id == room.imposter_id,
        })

    total_votes = sum(tally.values())
    top_count = max(tally.values()) if tally else 0
    leaders = [pid for pid, count in tally.items() if count == top_count and count > 0]
    majority = total_votes > 0 and top_count * 2 > total_votes
    caught = bool(majority and len(leaders) == 1 and leaders[0] == room.imposter_id)

    guess_clean = (guess or "").strip()
    guess_norm = normalize_word(guess_clean)
    guess_correct = bool(guess_norm) and guess_norm == normalize_word(room.secret_word)
    room.guess_text = guess_clean or None

    # Kostebek dogru tahmin ederse her kosulda kazanir; aksi halde cogunluk
    # onu dogru bulduysa dedektifler kazanir.
    winner = "crew" if (caught and not guess_correct) else "imposter"

    imposter = room.players.get(room.imposter_id or "")
    crew_ids = [pid for pid in room.order if pid != room.imposter_id]

    if winner == "crew":
        for pid in crew_ids:
            p = room.players.get(pid)
            if p is not None:
                p.score += 2
    else:
        if imposter is not None:
            imposter.score += 3 if guess_correct else 2
        for pid in crew_ids:
            p = room.players.get(pid)
            if p is not None and room.votes.get(pid) == room.imposter_id:
                p.score += 1

    if guess_correct:
        reason = f"Kamuflaj gizli kelimeyi dogru tahmin etti: “{room.secret_word}”"
    elif caught:
        reason = "Oylamada kostebek dogru bulundu ve tahmini tutmadi."
    elif majority and len(leaders) == 1:
        wrong = room.players.get(leaders[0])
        wrong_name = wrong.name if wrong is not None else "bilinmeyen oyuncu"
        reason = f"Cogunluk {wrong_name} oyuncusunu sucladi ama kostebek o degildi."
    elif total_votes == 0:
        reason = "Hic oy kullanilmadi, kostebek rahatca kacti."
    else:
        reason = "Oylar bolundu, cogunluk saglanamadi ve kostebek yakalanamadi."

    vote_counts = [
        {
            "player_id": pid,
            "name": room.players[pid].name if pid in room.players else "?",
            "count": count,
            "is_imposter": pid == room.imposter_id,
        }
        for pid, count in sorted(tally.items(), key=lambda kv: -kv[1])
    ]

    room.result = {
        "winner": winner,
        "winner_label": "Kamuflaj kazandi!" if winner == "imposter" else "Dedektifler kazandi!",
        "imposter_id": room.imposter_id,
        "imposter_name": imposter.name if imposter is not None else "(ayrilmis oyuncu)",
        "secret_word": room.secret_word,
        "guess": room.guess_text,
        "guess_correct": guess_correct,
        "caught": caught,
        "reason": reason,
        "vote_counts": vote_counts,
        "votes": vote_details,
        "scores": [
            {"id": p.id, "name": p.name, "score": p.score}
            for p in sorted(room.ordered_players(), key=lambda x: -x.score)
        ],
    }
    room.phase = PHASE_ENDED
    room.add_log(f"{room.result['winner_label']} {reason}", "end")


def abort_game(room: Room, reason: str) -> None:
    reset_to_lobby(room)
    room.add_log(reason, "warn")


def remove_player(room: Room, player: Player) -> None:
    room.players.pop(player.id, None)
    if player.id in room.seats:
        room.seats.remove(player.id)
    room.votes.pop(player.id, None)
    for voter_id, target_id in list(room.votes.items()):
        if target_id == player.id:
            room.votes.pop(voter_id, None)


def repair_room(room: Room) -> None:
    """Oyuncu ayrilma / baglanti kopmasi sonrasi oda durumunu tutarli yapar."""
    if room.host_id not in room.players:
        new_host = next((p.id for p in room.ordered_players() if p.connected), None)
        if new_host is None and room.seats:
            new_host = room.seats[0]
        room.host_id = new_host
        host = room.players.get(new_host or "")
        if host is not None:
            room.add_log(f"{host.name} artik oda sahibi.", "info")

    if room.phase == PHASE_PLAYING:
        if len(room.active_players()) < 2 or room.imposter_id not in room.players:
            abort_game(room, "Oyuncu sayisi yetersiz kaldi, oyun lobiye dondu.")
            return
        current = room.players.get(room.current_turn_id() or "")
        if current is None or not current.connected or not current.in_game:
            advance_turn(room)
    elif room.phase == PHASE_VOTING:
        if len(room.active_players()) < 2 or room.imposter_id not in room.players:
            abort_game(room, "Oyuncu sayisi yetersiz kaldi, oyun lobiye dondu.")
            return
        for voter_id in list(room.votes.keys()):
            if voter_id not in room.players:
                room.votes.pop(voter_id, None)
        check_votes_complete(room)
    elif room.phase == PHASE_GUESSING:
        imposter = room.players.get(room.imposter_id or "")
        if imposter is None or not imposter.connected:
            room.add_log("Kamuflaj baglantisini kaybetti, tahmin hakki kullanilmadi.", "guess")
            finish_game(room, None)


# ---------------------------------------------------------------------------
# WebSocket komutlari
# ---------------------------------------------------------------------------


async def detach_connection(conn: Connection) -> None:
    """Bu baglanti bir odaya bagliysa oradan ayirir ve odayi onarir."""
    if conn.room_code is None or conn.player_id is None:
        return
    room = ROOMS.get(conn.room_code)
    old_player_id = conn.player_id
    conn.room_code = None
    conn.player_id = None
    if room is None:
        return
    async with room.lock:
        player = room.players.get(old_player_id)
        if player is None or player.ws is not conn.ws:
            return
        player.ws = None
        player.connected = False
        if room.phase == PHASE_LOBBY:
            remove_player(room, player)
            room.add_log(f"{player.name} ayrildi.", "warn")
        else:
            room.add_log(f"{player.name} baglantisi koptu.", "warn")
        repair_room(room)
        await broadcast_state(room)


async def handle_create_room(conn: Connection, data: Dict[str, Any]) -> None:
    name = clean_name(data.get("name"))
    if not name:
        await conn.send(error_payload("bad_name", "Gecerli bir kullanici adi gir."))
        return
    rounds = data.get("rounds", DEFAULT_ROUNDS)
    if not isinstance(rounds, int) or rounds not in ALLOWED_ROUNDS:
        rounds = DEFAULT_ROUNDS

    async with ROOMS_LOCK:
        if len(ROOMS) >= MAX_ROOMS:
            await conn.send(error_payload("server_busy", "Sunucu su an cok yogun, biraz sonra dene."))
            return
        code = new_room_code()
        room = Room(code=code, rounds_total=rounds)
        ROOMS[code] = room

    await detach_connection(conn)

    player = Player(
        id=secrets.token_urlsafe(9),
        name=name,
        token=secrets.token_urlsafe(16),
        ws=conn.ws,
        connected=True,
    )
    async with room.lock:
        room.players[player.id] = player
        room.seats.append(player.id)
        room.host_id = player.id
        room.add_log(f"{player.name} odayi kurdu.", "join")
        room.touch()
        conn.room_code = room.code
        conn.player_id = player.id
        await conn.send({
            "type": "joined",
            "code": room.code,
            "player_id": player.id,
            "token": player.token,
            "name": player.name,
        })
        await broadcast_state(room)


async def handle_join_room(conn: Connection, data: Dict[str, Any]) -> None:
    name = clean_name(data.get("name"))
    code = clean_code(data.get("code"))
    if not name:
        await conn.send(error_payload("bad_name", "Gecerli bir kullanici adi gir."))
        return
    if len(code) < ROOM_CODE_LEN:
        await conn.send(error_payload("bad_code", "Oda kodu 4 karakter olmali."))
        return
    room = ROOMS.get(code)
    if room is None:
        await conn.send(error_payload("room_not_found", f"'{code}' kodlu oda bulunamadi."))
        return

    await detach_connection(conn)

    async with room.lock:
        if len(room.players) >= MAX_PLAYERS:
            await conn.send(error_payload("room_full", f"Oda dolu (en fazla {MAX_PLAYERS} oyuncu)."))
            return
        player = Player(
            id=secrets.token_urlsafe(9),
            name=room.unique_name(name),
            token=secrets.token_urlsafe(16),
            ws=conn.ws,
            connected=True,
        )
        room.players[player.id] = player
        room.seats.append(player.id)
        if room.host_id is None:
            room.host_id = player.id
        if room.phase in (PHASE_PLAYING, PHASE_VOTING, PHASE_GUESSING):
            player.in_game = False
            room.add_log(f"{player.name} katildi (bu el izleyici, sonraki ele dahil).", "join")
        else:
            room.add_log(f"{player.name} odaya katildi.", "join")
        room.touch()
        conn.room_code = room.code
        conn.player_id = player.id
        await conn.send({
            "type": "joined",
            "code": room.code,
            "player_id": player.id,
            "token": player.token,
            "name": player.name,
        })
        await broadcast_state(room)


async def handle_rejoin(conn: Connection, data: Dict[str, Any]) -> None:
    code = clean_code(data.get("code"))
    player_id = data.get("player_id")
    token = data.get("token")
    room = ROOMS.get(code)
    if room is None or not isinstance(player_id, str) or not isinstance(token, str):
        await conn.send(error_payload("session_invalid", "Onceki oturum bulunamadi."))
        return

    await detach_connection(conn)

    async with room.lock:
        player = room.players.get(player_id)
        if player is None or not secrets.compare_digest(player.token, token):
            await conn.send(error_payload("session_invalid", "Onceki oturum artik gecerli degil."))
            return
        was_offline = not player.connected
        player.ws = conn.ws
        player.connected = True
        if room.host_id is None:
            room.host_id = player.id
        conn.room_code = room.code
        conn.player_id = player.id
        if was_offline:
            room.add_log(f"{player.name} yeniden baglandi.", "join")
        room.touch()
        await conn.send({
            "type": "joined",
            "code": room.code,
            "player_id": player.id,
            "token": player.token,
            "name": player.name,
            "rejoined": True,
        })
        if room.phase == PHASE_PLAYING and room.current_turn_id() not in room.players:
            advance_turn(room)
        await broadcast_state(room)


async def cmd_set_rounds(room: Room, player: Player, data: Dict[str, Any], conn: Connection) -> None:
    if player.id != room.host_id:
        await conn.send(error_payload("not_host", "Bu ayari sadece oda sahibi degistirebilir."))
        return
    if room.phase not in (PHASE_LOBBY, PHASE_ENDED):
        await conn.send(error_payload("bad_phase", "Tur sayisi sadece lobide degistirilebilir."))
        return
    value = data.get("rounds")
    if not isinstance(value, int) or value not in ALLOWED_ROUNDS:
        await conn.send(error_payload("bad_value", "Gecersiz tur sayisi."))
        return
    room.rounds_total = value
    room.add_log(f"Tur sayisi kisi basi {value} kelime olarak ayarlandi.", "info")


async def cmd_start_game(room: Room, player: Player, data: Dict[str, Any], conn: Connection) -> None:
    if player.id != room.host_id:
        await conn.send(error_payload("not_host", "Oyunu sadece oda sahibi baslatabilir."))
        return
    if room.phase not in (PHASE_LOBBY, PHASE_ENDED):
        await conn.send(error_payload("bad_phase", "Oyun zaten devam ediyor."))
        return
    problem = start_game(room)
    if problem:
        await conn.send(error_payload("not_enough_players", problem))


async def cmd_submit_word(room: Room, player: Player, data: Dict[str, Any], conn: Connection) -> None:
    if room.phase != PHASE_PLAYING:
        await conn.send(error_payload("bad_phase", "Su an kelime yazma sirasi degil."))
        return
    if room.current_turn_id() != player.id:
        await conn.send(error_payload("not_your_turn", "Sira sende degil."))
        return
    raw = data.get("word")
    if not isinstance(raw, str):
        await conn.send(error_payload("bad_word", "Bir kelime yaz."))
        return
    word = re.sub(r"\s+", " ", CONTROL_PATTERN.sub("", raw)).strip()
    if " " in word:
        await conn.send(error_payload("bad_word", "Sadece TEK kelime yazabilirsin."))
        return
    if not WORD_PATTERN.match(word):
        await conn.send(error_payload("bad_word", "Kelime 2-24 harf olmali ve sadece harf icermeli."))
        return
    key = normalize_word(word)
    if not key:
        await conn.send(error_payload("bad_word", "Gecerli bir kelime yaz."))
        return
    if key == normalize_word(room.secret_word):
        await conn.send(error_payload("secret_word", "Gizli kelimenin kendisini yazamazsin!"))
        return
    if key in room.used_words:
        await conn.send(error_payload("duplicate_word", "Bu kelime bu oyunda daha once kullanildi."))
        return

    room.used_words.add(key)
    size = len(room.order) or 1
    room.words.append({
        "player_id": player.id,
        "name": player.name,
        "word": word,
        "round": room.turn_counter // size + 1,
        "index": len(room.words) + 1,
    })
    room.add_log(f"{player.name}: {word}", "word")
    advance_turn(room)


async def cmd_vote(room: Room, player: Player, data: Dict[str, Any], conn: Connection) -> None:
    if room.phase != PHASE_VOTING:
        await conn.send(error_payload("bad_phase", "Oylama su an acik degil."))
        return
    if not player.in_game:
        await conn.send(error_payload("spectator", "Bu elde izleyicisin, oy kullanamazsin."))
        return
    target_id = data.get("target_id")
    if not isinstance(target_id, str) or target_id not in room.players:
        await conn.send(error_payload("bad_target", "Gecersiz oyuncu."))
        return
    if target_id == player.id:
        await conn.send(error_payload("self_vote", "Kendine oy veremezsin."))
        return
    if not room.players[target_id].in_game:
        await conn.send(error_payload("bad_target", "Bu oyuncu bu elde oynamiyor."))
        return
    previous = room.votes.get(player.id)
    room.votes[player.id] = target_id
    if previous != target_id:
        room.add_log(f"{player.name} oyunu kullandi.", "vote")
    check_votes_complete(room)


async def cmd_guess(room: Room, player: Player, data: Dict[str, Any], conn: Connection) -> None:
    if room.phase != PHASE_GUESSING:
        await conn.send(error_payload("bad_phase", "Tahmin zamani degil."))
        return
    if player.id != room.imposter_id:
        await conn.send(error_payload("not_imposter", "Tahmin hakki sadece Kamuflaj'a ait."))
        return
    raw = data.get("word")
    if not isinstance(raw, str) or not raw.strip():
        await conn.send(error_payload("bad_word", "Bir tahmin yaz."))
        return
    guess = re.sub(r"\s+", " ", CONTROL_PATTERN.sub("", raw)).strip()[:40]
    room.add_log(f"Kamuflaj tahminini yapti: {guess}", "guess")
    finish_game(room, guess)


async def cmd_skip_guess(room: Room, player: Player, data: Dict[str, Any], conn: Connection) -> None:
    if room.phase != PHASE_GUESSING:
        await conn.send(error_payload("bad_phase", "Tahmin zamani degil."))
        return
    if player.id != room.imposter_id:
        await conn.send(error_payload("not_imposter", "Bu islem sadece Kamuflaj icin."))
        return
    room.add_log("Kamuflaj tahmin etmekten vazgecti.", "guess")
    finish_game(room, None)


async def cmd_skip_turn(room: Room, player: Player, data: Dict[str, Any], conn: Connection) -> None:
    """Oda sahibi AFK oyuncunun sirasini atlayabilir."""
    if player.id != room.host_id:
        await conn.send(error_payload("not_host", "Sadece oda sahibi sirayi atlayabilir."))
        return
    if room.phase != PHASE_PLAYING:
        await conn.send(error_payload("bad_phase", "Su an oyun turu yok."))
        return
    skipped = room.players.get(room.current_turn_id() or "")
    if skipped is not None:
        room.add_log(f"{skipped.name} oyuncusunun sirasi atlandi.", "warn")
    advance_turn(room)


async def cmd_force_vote(room: Room, player: Player, data: Dict[str, Any], conn: Connection) -> None:
    """Oda sahibi kelime turlarini erken bitirip oylamaya gecebilir."""
    if player.id != room.host_id:
        await conn.send(error_payload("not_host", "Sadece oda sahibi oylamayi baslatabilir."))
        return
    if room.phase != PHASE_PLAYING:
        await conn.send(error_payload("bad_phase", "Su an oyun turu yok."))
        return
    room.turn_counter = room.total_turns
    room.add_log("Oda sahibi oylamayi erken baslatti.", "warn")
    begin_voting(room)


async def cmd_play_again(room: Room, player: Player, data: Dict[str, Any], conn: Connection) -> None:
    if player.id != room.host_id:
        await conn.send(error_payload("not_host", "Yeni oyunu sadece oda sahibi baslatabilir."))
        return
    reset_to_lobby(room)
    room.add_log("Oda lobiye dondu, yeni oyun icin hazir.", "info")


async def cmd_kick(room: Room, player: Player, data: Dict[str, Any], conn: Connection) -> None:
    if player.id != room.host_id:
        await conn.send(error_payload("not_host", "Sadece oda sahibi oyuncu atabilir."))
        return
    target_id = data.get("player_id")
    if not isinstance(target_id, str) or target_id not in room.players:
        await conn.send(error_payload("bad_target", "Oyuncu bulunamadi."))
        return
    if target_id == player.id:
        await conn.send(error_payload("bad_target", "Kendini atamazsin."))
        return
    target = room.players[target_id]
    if target.ws is not None:
        await send_to(target, {"type": "kicked", "message": "Oda sahibi seni odadan cikardi."})
    room.add_log(f"{target.name} odadan cikarildi.", "warn")
    remove_player(room, target)
    repair_room(room)


async def cmd_leave(room: Room, player: Player, data: Dict[str, Any], conn: Connection) -> None:
    room.add_log(f"{player.name} odadan ayrildi.", "warn")
    remove_player(room, player)
    conn.room_code = None
    conn.player_id = None
    repair_room(room)
    await conn.send({"type": "left"})


COMMANDS = {
    "set_rounds": cmd_set_rounds,
    "start_game": cmd_start_game,
    "submit_word": cmd_submit_word,
    "vote": cmd_vote,
    "guess": cmd_guess,
    "skip_guess": cmd_skip_guess,
    "skip_turn": cmd_skip_turn,
    "force_vote": cmd_force_vote,
    "play_again": cmd_play_again,
    "kick": cmd_kick,
    "leave": cmd_leave,
}


async def handle_message(conn: Connection, data: Dict[str, Any]) -> None:
    action = data.get("type")
    if not isinstance(action, str):
        await conn.send(error_payload("bad_message", "Gecersiz istek."))
        return

    if action == "create_room":
        await handle_create_room(conn, data)
        return
    if action == "join_room":
        await handle_join_room(conn, data)
        return
    if action == "rejoin":
        await handle_rejoin(conn, data)
        return
    if action == "ping":
        await conn.send({"type": "pong", "t": data.get("t")})
        return

    handler = COMMANDS.get(action)
    if handler is None:
        await conn.send(error_payload("unknown_command", "Bilinmeyen komut."))
        return

    room = ROOMS.get(conn.room_code or "")
    player = room.players.get(conn.player_id or "") if room is not None else None
    if room is None or player is None:
        conn.room_code = None
        conn.player_id = None
        await conn.send(error_payload("session_invalid", "Oturum bulunamadi, tekrar katil."))
        return

    async with room.lock:
        room.touch()
        await handler(room, player, data, conn)
        await broadcast_state(room)


# ---------------------------------------------------------------------------
# FastAPI uygulamasi
# ---------------------------------------------------------------------------


async def room_pruner() -> None:
    """Tamamen bos kalan odalari periyodik olarak temizler."""
    while True:
        try:
            await asyncio.sleep(60)
            now = time.time()
            async with ROOMS_LOCK:
                stale = [
                    code for code, room in ROOMS.items()
                    if not any(p.connected for p in room.players.values())
                    and now - room.last_active > ROOM_IDLE_TTL
                ]
                for code in stale:
                    room = ROOMS.pop(code, None)
                    if room is not None:
                        cancel_guess_timer(room)
        except asyncio.CancelledError:
            return
        except Exception:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(room_pruner())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Kamuflaj",
    description="Gercek zamanli Imposter/Spyfall tarzi parti oyunu",
    lifespan=lifespan,
)

STATIC_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "min_players": MIN_PLAYERS,
            "max_players": MAX_PLAYERS,
            "word_count": len(WORDS),
            "guess_seconds": GUESS_SECONDS,
        },
    )


@app.get("/healthz")
async def healthz():
    return JSONResponse({
        "status": "ok",
        "rooms": len(ROOMS),
        "players": sum(len(r.players) for r in ROOMS.values()),
        "words": len(WORDS),
    })


@app.get("/api/room/{code}")
async def room_info(code: str):
    room = ROOMS.get(clean_code(code))
    if room is None:
        return JSONResponse({"exists": False}, status_code=404)
    return JSONResponse({
        "exists": True,
        "code": room.code,
        "phase": room.phase,
        "players": len(room.players),
        "max_players": MAX_PLAYERS,
    })


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    conn = Connection(ws)
    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) > 4096:
                await conn.send(error_payload("too_long", "Istek fazla buyuk."))
                continue
            if not conn.allow():
                await conn.send(error_payload("rate_limited", "Cok hizli istek gonderiyorsun, biraz yavasla."))
                continue
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                await conn.send(error_payload("bad_json", "Gecersiz veri."))
                continue
            if not isinstance(data, dict):
                await conn.send(error_payload("bad_message", "Gecersiz veri."))
                continue
            try:
                await handle_message(conn, data)
            except WebSocketDisconnect:
                raise
            except Exception:
                await conn.send(error_payload("server_error", "Beklenmeyen bir hata olustu."))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await detach_connection(conn)


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=bool(os.environ.get("DEV")),
    )
