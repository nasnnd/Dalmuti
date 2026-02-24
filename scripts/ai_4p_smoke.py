import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as game


def reset_globals():
    game.rooms.clear()
    game.players.clear()
    game.room_players.clear()
    game.sessions.clear()
    game.disconnect_timers.clear()


def choose_play_cards(hand, table_cards):
    counts = Counter(hand)
    if not table_cards:
        non_j = [n for n in sorted(counts.keys()) if n != 13]
        return [non_j[0]] if non_j else [13]

    need = len(table_cards)
    table_val = game.resolve_jester(table_cards)

    for num, cnt in sorted((n, c) for n, c in counts.items() if n != 13):
        if num < table_val and cnt >= need:
            return [num] * need

    j = counts.get(13, 0)
    for num, cnt in sorted((n, c) for n, c in counts.items() if n != 13):
        if num < table_val and cnt + j >= need:
            use = min(cnt, need)
            return [num] * use + [13] * (need - use)

    return None


def run_simulation(rounds=3):
    reset_globals()

    nicks = ["AI-1", "AI-2", "AI-3", "AI-4"]
    clients = [game.socketio.test_client(game.app) for _ in nicks]

    for c, nick in zip(clients, nicks):
        c.emit("set_nickname", {"nickname": nick})

    host = clients[0]
    host.emit("create_room", {"title": "AI Smoke", "rounds": rounds})
    room_joined = [x for x in host.get_received() if x["name"] == "room_joined"]
    room_id = room_joined[-1]["args"][0]["room_id"]

    for c in clients[1:]:
        c.emit("join_room_req", {"room_id": room_id})

    for c in clients:
        c.emit("set_ready", {"ready": True})

    host.emit("start_game")

    nick_to_sid = {v["nickname"]: k for k, v in game.players.items()}
    sid_to_client = {nick_to_sid[nick]: client for nick, client in zip(nicks, clients)}

    for step in range(1, 120000):
        room = game.rooms[room_id]
        state = room["state"]

        if state == "draw":
            eligible = room.get("_draw_remaining")
            if eligible is None:
                eligible = list(game.room_players[room_id])
            for sid in eligible:
                if room["draw_results"].get(sid) is None:
                    sid_to_client[sid].emit("draw_card")

        elif state == "exchange":
            for sid in list(room["player_order"]):
                exch = room["exchange_state"].get(sid, {})
                if exch.get("confirmed"):
                    continue
                if exch.get("auto") is False and len(exch.get("selected", [])) != 2:
                    hand = room["hands"][sid]
                    sid_to_client[sid].emit("exchange_select", {"selected": sorted(hand, reverse=True)[:2]})
                sid_to_client[sid].emit("exchange_confirm")

        elif state == "playing":
            sid = room["current_turn"]
            hand = list(room["hands"][sid])
            play = choose_play_cards(hand, room["table_cards"])
            if play:
                sid_to_client[sid].emit("play_cards", {"cards": play})
            else:
                sid_to_client[sid].emit("pass_turn")

        elif state == "round_end":
            print(f"round {room['current_round']} ended, order={[game.players[s]['nickname'] for s in room['player_order']]}")
            host.emit("next_round_ack")

        elif state == "game_end":
            print("game_end", room["current_round"], [game.players[s]["nickname"] for s in room["player_order"]])
            break

        else:
            raise RuntimeError(f"Unexpected state: {state}")
    else:
        raise RuntimeError("Simulation loop exceeded max steps")

    for c in clients:
        c.disconnect()


if __name__ == "__main__":
    run_simulation(rounds=3)
