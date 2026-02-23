from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import uuid
import os
from collections import defaultdict, Counter

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dalmuti-secret-key-2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ── 전역 상태 ──────────────────────────────────────────────
rooms = {}
players = {}
room_players = defaultdict(list)

# ── 카드 정의 ──────────────────────────────────────────────
CARD_NAMES = {
    1:  ("달무티",   "👑"),
    2:  ("대주교",   "⛪"),
    3:  ("시종장",   "🎖️"),
    4:  ("남작부인", "💎"),
    5:  ("수녀원장", "🕊️"),
    6:  ("기사",     "⚔️"),
    7:  ("재봉사",   "🧵"),
    8:  ("석공",     "⚒️"),
    9:  ("요리사",   "🍳"),
    10: ("양치기",   "🐑"),
    11: ("광부",     "⛏️"),
    12: ("농노",     "🌾"),
    13: ("어릿광대", "🃏"),
}

MID_RANKS = [
    ("대주교",   "⛪"),
    ("시종장",   "🎖️"),
    ("남작부인", "💎"),
    ("수녀원장", "🕊️"),
    ("기사",     "⚔️"),
    ("재봉사",   "🧵"),
    ("석공",     "⚒️"),
    ("광부",     "⛏️"),
]

def get_rank_display(rank, total):
    if rank == 1:
        return ("달무티", "👑")
    if rank == total:
        return ("농노", "🌾")
    return MID_RANKS[min(rank - 2, len(MID_RANKS) - 1)]

def make_deck():
    deck = []
    for num in range(1, 13):
        for _ in range(num):
            deck.append(num)
    deck.append(13)
    deck.append(13)
    random.shuffle(deck)
    return deck

def card_info(num):
    name, emoji = CARD_NAMES[num]
    return {"num": num, "name": name, "emoji": emoji}

def new_room(room_id, title, rounds, host_sid):
    return {
        "id": room_id,
        "title": title,
        "rounds": rounds,
        "current_round": 0,
        "host": host_sid,
        "state": "lobby",
        "player_order": [],
        "ranks": {},
        "hands": {},
        "table_cards": [],
        "last_player": None,
        "current_turn": None,
        "turn_direction": 1,
        "pass_count": 0,
        "active_players": [],
        "finished_order": [],
        "exchange_state": {},
        "exchange_pairs": [],
        "draw_results": {},
        "win_counts": {},
        "can_revolution": False,
        "peasant_sid": None,
        "revolution": False,
        "_draw_remaining": None,
        "_draw_confirmed": [],
    }

# ── 상태 브로드캐스트 ────────────────────────────────────────
def emit_state_all(room_id):
    for sid in room_players.get(room_id, []):
        state = build_state(room_id, sid)
        socketio.emit("state_update", state, room=sid)

def build_state(room_id, viewer_sid):
    room = rooms.get(room_id)
    if not room:
        return {}
    sids = room_players[room_id]
    n = len(sids)
    pub_players = []
    for s in sids:
        p = players.get(s, {})
        rank = room["ranks"].get(s, 0)
        rname, remoji = get_rank_display(rank, n) if rank else ("?", "❓")
        finished_rank = None
        if s in room.get("finished_order", []):
            finished_rank = room["finished_order"].index(s) + 1
        pub_players.append({
            "sid": s,
            "nickname": p.get("nickname", "?"),
            "ready": p.get("ready", False),
            "rank": rank,
            "rank_name": rname,
            "rank_emoji": remoji,
            "hand_count": len(room["hands"].get(s, [])),
            "finished": s in room.get("finished_order", []),
            "finish_rank": finished_rank,
            "is_host": s == room["host"],
        })

    my_hand = [card_info(c) for c in room["hands"].get(viewer_sid, [])]
    table = [card_info(c) for c in room["table_cards"]]
    exch = room["exchange_state"].get(viewer_sid, {})
    my_exchange = {
        "selected": [card_info(c) for c in exch.get("selected", [])],
        "confirmed": exch.get("confirmed", False),
        "auto": exch.get("auto", False),
        "no_pair": exch.get("auto") is None,
    }

    exchange_state = room.get("exchange_state", {})
    exchange_confirmed_count = sum(1 for ex in exchange_state.values() if ex.get("confirmed"))
    exchange_total_count = len(exchange_state)

    my_pair_sid = None
    my_pair_role = None
    for (h, l) in room.get("exchange_pairs", []):
        if h == viewer_sid:
            my_pair_sid = l
            my_pair_role = "high"
        elif l == viewer_sid:
            my_pair_sid = h
            my_pair_role = "low"

    draw_res_public = {}
    for s, v in room.get("draw_results", {}).items():
        nick = players.get(s, {}).get("nickname", "?")
        draw_res_public[s] = {"nickname": nick, "value": v}

    return {
        "room_id": room_id,
        "title": room["title"],
        "rounds": room["rounds"],
        "current_round": room["current_round"],
        "host": room["host"],
        "state": room["state"],
        "players": pub_players,
        "my_hand": my_hand,
        "table_cards": table,
        "current_turn": room["current_turn"],
        "last_player": room["last_player"],
        "active_players": room["active_players"],
        "finished_order": room["finished_order"],
        "win_counts": room["win_counts"],
        "my_exchange": my_exchange,
        "my_pair_sid": my_pair_sid,
        "my_pair_role": my_pair_role,
        "pair_nickname": players.get(my_pair_sid, {}).get("nickname") if my_pair_sid else None,
        "draw_results": draw_res_public,
        "can_revolution": room.get("can_revolution") and viewer_sid == room.get("peasant_sid"),
        "revolution": room.get("revolution", False),
        "turn_direction": room.get("turn_direction", 1),
        "exchange_confirmed_count": exchange_confirmed_count,
        "exchange_total_count": exchange_total_count,
        "my_sid": viewer_sid,
    }

def emit_lobby():
    data = []
    for rid, room in rooms.items():
        data.append({
            "id": rid,
            "title": room["title"],
            "rounds": room["rounds"],
            "player_count": len(room_players[rid]),
            "state": room["state"],
        })
    socketio.emit("lobby_update", data)

# ── 뽑기 로직 ───────────────────────────────────────────────
def start_draw(room_id):
    room = rooms[room_id]
    room["state"] = "draw"
    room["draw_results"] = {}
    room["_draw_remaining"] = None
    room["_draw_confirmed"] = []
    emit_state_all(room_id)

def process_draw(room_id):
    room = rooms[room_id]
    results = room["draw_results"]
    remaining = room.get("_draw_remaining")
    sids_drew = remaining if remaining else room_players[room_id]

    if not all(results.get(s) is not None for s in sids_drew):
        return

    counts = Counter(results.values())
    unique_sids = sorted([s for s in sids_drew if counts[results[s]] == 1], key=lambda s: results[s])
    dup_sids = [s for s in sids_drew if counts[results[s]] > 1]

    confirmed = room.get("_draw_confirmed", [])

    if not dup_sids:
        final_order = confirmed + unique_sids
        room["player_order"] = final_order
        room["ranks"] = {s: i + 1 for i, s in enumerate(final_order)}
        room["_draw_remaining"] = None
        room["_draw_confirmed"] = []
        room["state"] = "exchange"
        n = len(final_order)
        room["win_counts"] = {s: 0 for s in final_order}
        deal_cards(room_id)
        compute_exchange_pairs(room_id)
        check_revolution(room_id)
        emit_state_all(room_id)
    else:
        room["_draw_confirmed"] = confirmed + unique_sids
        room["_draw_remaining"] = dup_sids
        room["draw_results"] = {}
        socketio.emit("redraw_needed", {
            "redraw_players": [players[s]["nickname"] for s in dup_sids]
        }, room=room_id)
        emit_state_all(room_id)

# ── 카드 배분 ───────────────────────────────────────────────
def deal_cards(room_id):
    room = rooms[room_id]
    order = room["player_order"]
    deck = make_deck()
    n = len(order)
    base = len(deck) // n
    extra = len(deck) % n
    hands = {}
    idx = 0
    bonus_start = n - extra
    for i, s in enumerate(order):
        cnt = base + (1 if i >= bonus_start else 0)
        hands[s] = sorted(deck[idx:idx + cnt])
        idx += cnt
    room["hands"] = hands

# ── 교환 쌍 ─────────────────────────────────────────────────
def compute_exchange_pairs(room_id):
    room = rooms[room_id]
    order = room["player_order"]
    n = len(order)
    pairs = []
    for i in range(n // 2):
        h = order[i]
        l = order[n - 1 - i]
        pairs.append((h, l))
    room["exchange_pairs"] = pairs
    room["exchange_state"] = {}
    for (h, l) in pairs:
        low_hand = sorted(room["hands"][l])
        auto_sel = low_hand[:2]
        room["exchange_state"][l] = {"selected": auto_sel, "confirmed": False, "auto": True}
        room["exchange_state"][h] = {"selected": [], "confirmed": False, "auto": False}
    if n % 2 == 1:
        mid = order[n // 2]
        room["exchange_state"][mid] = {"selected": [], "confirmed": True, "auto": None}

def check_revolution(room_id):
    room = rooms[room_id]
    if not room["player_order"]:
        return
    peasant = room["player_order"][-1]
    has_rev = room["hands"].get(peasant, []).count(13) >= 2
    room["can_revolution"] = has_rev
    room["peasant_sid"] = peasant

def do_exchange(room_id, h, l):
    room = rooms[room_id]
    h_sel = room["exchange_state"][h]["selected"]
    l_sel = room["exchange_state"][l]["selected"]
    for c in h_sel:
        room["hands"][h].remove(c)
        room["hands"][l].append(c)
    for c in l_sel:
        room["hands"][l].remove(c)
        room["hands"][h].append(c)
    room["hands"][h] = sorted(room["hands"][h])
    room["hands"][l] = sorted(room["hands"][l])

def all_exchanged(room_id):
    room = rooms[room_id]
    for (h, l) in room["exchange_pairs"]:
        if not room["exchange_state"].get(h, {}).get("confirmed"):
            return False
        if not room["exchange_state"].get(l, {}).get("confirmed"):
            return False
    order = room["player_order"]
    n = len(order)
    if n % 2 == 1:
        mid = order[n // 2]
        if not room["exchange_state"].get(mid, {}).get("confirmed"):
            return False
    return True

# ── 게임 진행 ───────────────────────────────────────────────
def resolve_jester(cards):
    non_j = [c for c in cards if c != 13]
    if not non_j:
        return 13
    return non_j[0]


def is_single_rank_set(cards):
    if not cards:
        return False
    non_j = [c for c in cards if c != 13]
    if not non_j:
        return True
    target = non_j[0]
    return all(c == target for c in non_j)

def can_play_cards(cards, table_cards):
    if not is_single_rank_set(cards):
        return False
    if not table_cards:
        return len(cards) > 0
    if len(cards) != len(table_cards):
        return False
    play_val = resolve_jester(cards)
    table_val = resolve_jester(table_cards)
    return play_val < table_val

def start_playing(room_id):
    room = rooms[room_id]
    room["state"] = "playing"
    room["table_cards"] = []
    room["last_player"] = None
    room["pass_count"] = 0
    room["active_players"] = list(room["player_order"])
    room["finished_order"] = []
    room["current_turn"] = room["player_order"][0]
    emit_state_all(room_id)

def get_next_active(room_id, from_sid):
    room = rooms[room_id]
    active = room["active_players"]
    if not active:
        return None
    if from_sid not in active:
        return active[0]
    idx = active.index(from_sid)
    d = room["turn_direction"]
    return active[(idx + d) % len(active)]

def end_round(room_id):
    room = rooms[room_id]
    active = room["active_players"]
    if active:
        room["finished_order"].append(active[0])
        active.clear()
    new_order = room["finished_order"][:]
    room["player_order"] = new_order
    room["ranks"] = {s: i + 1 for i, s in enumerate(new_order)}
    if new_order:
        winner = new_order[0]
        room["win_counts"][winner] = room["win_counts"].get(winner, 0) + 1
    room["current_round"] += 1
    if room["current_round"] >= room["rounds"]:
        room["state"] = "game_end"
    else:
        room["state"] = "round_end"
    emit_state_all(room_id)

# ═══════════════════════════════════════════════════════════
# SocketIO 핸들러
# ═══════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def on_connect():
    players[request.sid] = {"nickname": None, "room": None, "ready": False}

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    if room_id:
        _handle_leave(sid, room_id)
    players.pop(sid, None)

def _handle_leave(sid, room_id):
    room = rooms.get(room_id)
    if not room:
        return
    room_players[room_id] = [s for s in room_players[room_id] if s != sid]
    if room["host"] == sid and room_players[room_id]:
        room["host"] = room_players[room_id][0]
    if room["state"] not in ("lobby", "game_end"):
        room["state"] = "lobby"
        room["hands"] = {}
        room["active_players"] = []
        room["finished_order"] = []
        room["table_cards"] = []
        room["current_turn"] = None
        for s in room_players[room_id]:
            players[s]["ready"] = False
        socketio.emit("game_interrupted", {
            "message": f"'{players.get(sid,{}).get('nickname','?')}' 님이 나가서 게임이 중단되었습니다."
        }, room=room_id)
    leave_room(room_id)
    if not room_players[room_id]:
        rooms.pop(room_id, None)
        room_players.pop(room_id, None)
    else:
        emit_state_all(room_id)
    emit_lobby()

@socketio.on('set_nickname')
def on_set_nickname(data):
    sid = request.sid
    nick = str(data.get('nickname', '')).strip()
    if 2 <= len(nick) <= 10:
        players[sid]['nickname'] = nick
        emit('nickname_ok', {'nickname': nick})
    else:
        emit('error_msg', {'message': '닉네임은 2~10글자여야 합니다.'})

@socketio.on('get_lobby')
def on_get_lobby():
    emit_lobby()

@socketio.on('create_room')
def on_create_room(data):
    sid = request.sid
    if not players.get(sid, {}).get('nickname'):
        emit('error_msg', {'message': '닉네임을 설정하세요.'})
        return
    title = str(data.get('title', '달무티')).strip() or '달무티'
    rounds = max(1, min(20, int(data.get('rounds', 3))))
    room_id = str(uuid.uuid4())[:8]
    rooms[room_id] = new_room(room_id, title, rounds, sid)
    room_players[room_id] = []
    _do_join(sid, room_id)
    emit('room_joined', {'room_id': room_id})
    emit_lobby()

@socketio.on('join_room_req')
def on_join_room(data):
    sid = request.sid
    if not players.get(sid, {}).get('nickname'):
        emit('error_msg', {'message': '닉네임을 설정하세요.'})
        return
    room_id = data.get('room_id')
    room = rooms.get(room_id)
    if not room:
        emit('error_msg', {'message': '방을 찾을 수 없습니다.'})
        return
    if room["state"] != "lobby":
        emit('error_msg', {'message': '게임이 이미 시작되었습니다.'})
        return
    if len(room_players[room_id]) >= 9:
        emit('error_msg', {'message': '방이 꽉 찼습니다. (최대 9명)'})
        return
    _do_join(sid, room_id)
    emit('room_joined', {'room_id': room_id})
    emit_lobby()

def _do_join(sid, room_id):
    players[sid]["room"] = room_id
    players[sid]["ready"] = False
    room_players[room_id].append(sid)
    join_room(room_id)
    rooms[room_id]["win_counts"][sid] = 0
    emit_state_all(room_id)

@socketio.on('leave_room_req')
def on_leave_room():
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    if room_id:
        _handle_leave(sid, room_id)
        players[sid]["room"] = None
    emit('left_room')

@socketio.on('update_room')
def on_update_room(data):
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    room = rooms.get(room_id)
    if not room or room["host"] != sid:
        return
    if "title" in data:
        t = str(data["title"]).strip()
        if t:
            room["title"] = t
    if "rounds" in data:
        room["rounds"] = max(1, min(20, int(data["rounds"])))
    emit_state_all(room_id)
    emit_lobby()

@socketio.on('set_ready')
def on_ready(data):
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    if not room_id:
        return
    players[sid]["ready"] = bool(data.get("ready"))
    emit_state_all(room_id)

@socketio.on('start_game')
def on_start_game():
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    room = rooms.get(room_id)
    if not room or room["host"] != sid or room["state"] != "lobby":
        return
    sids = room_players[room_id]
    if len(sids) < 3:
        emit('error_msg', {'message': '최소 3명이 필요합니다.'})
        return
    if not all(players.get(s, {}).get("ready") for s in sids):
        emit('error_msg', {'message': '모든 플레이어가 준비해야 합니다.'})
        return
    room["win_counts"] = {s: 0 for s in sids}
    room["current_round"] = 0
    start_draw(room_id)

@socketio.on('draw_card')
def on_draw_card():
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    room = rooms.get(room_id)
    if not room or room["state"] != "draw":
        return
    remaining = room.get("_draw_remaining")
    eligible = remaining if remaining is not None else room_players[room_id]
    if sid not in eligible:
        return
    if room["draw_results"].get(sid) is not None:
        return
    room["draw_results"][sid] = random.randint(1, 13)
    emit_state_all(room_id)
    if all(room["draw_results"].get(s) is not None for s in eligible):
        process_draw(room_id)

@socketio.on('exchange_select')
def on_exchange_select(data):
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    room = rooms.get(room_id)
    if not room or room["state"] != "exchange":
        return
    exch = room["exchange_state"].get(sid, {})
    if exch.get("auto") is not False:
        return
    selected = data.get("selected", [])
    if len(selected) != 2:
        return
    hand = list(room["hands"].get(sid, []))
    tmp = hand[:]
    for c in selected:
        if c in tmp:
            tmp.remove(c)
        else:
            emit('error_msg', {'message': '손패에 없는 카드입니다.'})
            return
    exch["selected"] = selected
    emit_state_all(room_id)

@socketio.on('exchange_confirm')
def on_exchange_confirm():
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    room = rooms.get(room_id)
    if not room or room["state"] != "exchange":
        return
    exch = room["exchange_state"].get(sid, {})
    if exch.get("auto") is True:
        auto_sel = sorted(room["hands"].get(sid, []))[:2]
        if len(auto_sel) != 2:
            emit('error_msg', {'message': '교환 가능한 카드가 부족합니다.'})
            return
        exch["selected"] = auto_sel
    elif exch.get("auto") is False and len(exch.get("selected", [])) != 2:
        emit('error_msg', {'message': '카드 2장을 선택하세요.'})
        return
    exch["confirmed"] = True
    # 짝 모두 확인 시 실제 교환
    for (h, l) in room["exchange_pairs"]:
        if h == sid or l == sid:
            hc = room["exchange_state"].get(h, {}).get("confirmed")
            lc = room["exchange_state"].get(l, {}).get("confirmed")
            if hc and lc:
                do_exchange(room_id, h, l)
    if all_exchanged(room_id):
        start_playing(room_id)
    else:
        emit_state_all(room_id)

@socketio.on('revolution')
def on_revolution():
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    room = rooms.get(room_id)
    if not room or room["state"] != "exchange":
        return
    if not room.get("can_revolution") or room.get("peasant_sid") != sid:
        emit('error_msg', {'message': '혁명 조건 미충족.'})
        return
    order = room["player_order"]
    order.reverse()
    room["player_order"] = order
    room["ranks"] = {s: i + 1 for i, s in enumerate(order)}
    room["turn_direction"] = -room.get("turn_direction", 1)
    room["revolution"] = True
    room["can_revolution"] = False
    compute_exchange_pairs(room_id)
    check_revolution(room_id)
    socketio.emit("revolution_alert", {"message": "🔥 혁명 발생! 계급이 역전됩니다!"}, room=room_id)
    emit_state_all(room_id)

@socketio.on('play_cards')
def on_play_cards(data):
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    room = rooms.get(room_id)
    if not room or room["state"] != "playing":
        return
    if room["current_turn"] != sid:
        emit('error_msg', {'message': '당신의 차례가 아닙니다.'})
        return
    cards = data.get("cards", [])
    if not cards:
        return
    if not can_play_cards(cards, room["table_cards"]):
        emit('error_msg', {'message': '낼 수 없는 카드입니다.'})
        return
    hand = list(room["hands"][sid])
    for c in cards:
        if c in hand:
            hand.remove(c)
        else:
            emit('error_msg', {'message': '손패에 없는 카드입니다.'})
            return
    room["hands"][sid] = hand
    room["table_cards"] = cards
    room["last_player"] = sid
    room["pass_count"] = 0
    if not hand:
        room["finished_order"].append(sid)
        room["active_players"].remove(sid)
        if len(room["active_players"]) <= 1:
            end_round(room_id)
            return
    room["current_turn"] = get_next_active(room_id, sid)
    emit_state_all(room_id)

@socketio.on('pass_turn')
def on_pass_turn():
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    room = rooms.get(room_id)
    if not room or room["state"] != "playing":
        return
    if room["current_turn"] != sid:
        return
    next_sid = get_next_active(room_id, sid)
    room["current_turn"] = next_sid
    last = room["last_player"]
    # 마지막으로 낸 사람 차례로 돌아오면 테이블 초기화
    if last and next_sid == last:
        room["table_cards"] = []
        room["last_player"] = None
        room["pass_count"] = 0
        socketio.emit('info_msg', {
            'message': '모든 플레이어가 패스했습니다. 새로운 규칙을 정하세요.'
        }, room=next_sid)
    elif not last:
        # 아무도 안 냈고 한바퀴 돈 경우
        room["pass_count"] = room.get("pass_count", 0) + 1
        if room["pass_count"] >= len(room["active_players"]):
            room["pass_count"] = 0
    emit_state_all(room_id)

@socketio.on('next_round_ack')
def on_next_round_ack():
    sid = request.sid
    room_id = players.get(sid, {}).get("room")
    room = rooms.get(room_id)
    if not room or room["host"] != sid:
        return
    if room["state"] == "round_end":
        room["turn_direction"] = 1
        room["revolution"] = False
        deal_cards(room_id)
        compute_exchange_pairs(room_id)
        check_revolution(room_id)
        room["state"] = "exchange"
        emit_state_all(room_id)
    elif room["state"] == "game_end":
        room["state"] = "lobby"
        for s in room_players[room_id]:
            players[s]["ready"] = False
        emit_state_all(room_id)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    socketio.run(
        app,
        debug=debug,
        host='0.0.0.0',
        port=port,
        allow_unsafe_werkzeug=True,
    )
