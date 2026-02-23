diff --git a/app.py b/app.py
index ef64cfdd909533368f9fda2d2f4061fc35f81c81..4bd239f79d650854c22775448bc3c3c2e198a228 100644
--- a/app.py
+++ b/app.py
@@ -1,40 +1,43 @@
 from flask import Flask, render_template, request
 from flask_socketio import SocketIO, emit, join_room, leave_room
 import random
 import uuid
 import os
+import threading
 from collections import defaultdict, Counter
 
 app = Flask(__name__)
 app.config['SECRET_KEY'] = 'dalmuti-secret-key-2024'
 socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
 
 # ── 전역 상태 ──────────────────────────────────────────────
 rooms = {}
 players = {}
 room_players = defaultdict(list)
+sessions = {}
+disconnect_timers = {}
 
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
@@ -70,50 +73,103 @@ def new_room(room_id, title, rounds, host_sid):
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
 
+
+def _replace_sid_in_list(values, old_sid, new_sid):
+    return [new_sid if v == old_sid else v for v in values]
+
+
+def _replace_sid_in_room(room, old_sid, new_sid):
+    if room["host"] == old_sid:
+        room["host"] = new_sid
+    room["player_order"] = _replace_sid_in_list(room.get("player_order", []), old_sid, new_sid)
+    room["active_players"] = _replace_sid_in_list(room.get("active_players", []), old_sid, new_sid)
+    room["finished_order"] = _replace_sid_in_list(room.get("finished_order", []), old_sid, new_sid)
+    room["_draw_remaining"] = _replace_sid_in_list(room.get("_draw_remaining") or [], old_sid, new_sid) or None
+    room["_draw_confirmed"] = _replace_sid_in_list(room.get("_draw_confirmed", []), old_sid, new_sid)
+
+    if room.get("current_turn") == old_sid:
+        room["current_turn"] = new_sid
+    if room.get("last_player") == old_sid:
+        room["last_player"] = new_sid
+    if room.get("peasant_sid") == old_sid:
+        room["peasant_sid"] = new_sid
+
+    for key in ("ranks", "hands", "exchange_state", "draw_results", "win_counts"):
+        if old_sid in room.get(key, {}):
+            room[key][new_sid] = room[key].pop(old_sid)
+
+    pairs = []
+    for h, l in room.get("exchange_pairs", []):
+        h = new_sid if h == old_sid else h
+        l = new_sid if l == old_sid else l
+        pairs.append((h, l))
+    room["exchange_pairs"] = pairs
+
+
+def _migrate_player(old_sid, new_sid, token):
+    old = players.get(old_sid, {})
+    room_id = old.get("room")
+    players[new_sid] = {
+        "nickname": old.get("nickname"),
+        "room": room_id,
+        "ready": old.get("ready", False),
+        "token": token,
+    }
+
+    if room_id and room_id in room_players:
+        room_players[room_id] = [new_sid if s == old_sid else s for s in room_players[room_id]]
+        room = rooms.get(room_id)
+        if room:
+            _replace_sid_in_room(room, old_sid, new_sid)
+        join_room(room_id)
+        emit_state_all(room_id)
+
+    players.pop(old_sid, None)
+
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
@@ -130,51 +186,51 @@ def build_state(room_id, viewer_sid):
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
-        draw_res_public[s] = {"nickname": nick, "value": v}
+        draw_res_public[s] = {"nickname": nick, "value": v, "card": card_info(v)}
 
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
@@ -371,56 +427,92 @@ def end_round(room_id):
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
-def on_connect():
-    players[request.sid] = {"nickname": None, "room": None, "ready": False}
+def on_connect(auth):
+    sid = request.sid
+    token = None
+    if isinstance(auth, dict):
+        token = str(auth.get("session_token", "")).strip()
+
+    if token and token in disconnect_timers:
+        disconnect_timers[token].cancel()
+        disconnect_timers.pop(token, None)
+
+    prev_sid = sessions.get(token) if token else None
+    if token and prev_sid and prev_sid != sid and prev_sid in players:
+        _migrate_player(prev_sid, sid, token)
+    else:
+        players[sid] = {"nickname": None, "room": None, "ready": False, "token": token}
+
+    if token:
+        sessions[token] = sid
 
 @socketio.on('disconnect')
 def on_disconnect():
     sid = request.sid
+    token = players.get(sid, {}).get("token")
+
+    if token:
+        def delayed_cleanup():
+            latest_sid = sessions.get(token)
+            if latest_sid != sid:
+                return
+            room_id = players.get(sid, {}).get("room")
+            if room_id:
+                _handle_leave(sid, room_id)
+            players.pop(sid, None)
+            sessions.pop(token, None)
+            disconnect_timers.pop(token, None)
+
+        timer = threading.Timer(25.0, delayed_cleanup)
+        timer.daemon = True
+        disconnect_timers[token] = timer
+        timer.start()
+        return
+
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
