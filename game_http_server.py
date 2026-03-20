#!/usr/bin/env python3
"""HTTP Game Server for Commander multiplayer.

Single persistent process. Agents call via HTTP (WebFetch).
No file locking needed — requests are serialized by the server.

Usage:
    python3 game_http_server.py [--port 8080]

Endpoints:
    POST /create         {decklists: [...], seed: N}
    POST /hand           {game_id, player}
    POST /mulligan       {game_id, player}
    POST /keep           {game_id, player, bottom_cards: [...]}
    POST /begin          {game_id, player}
    POST /action         {game_id, player, action: "play Forest"}
    POST /valid          {game_id, player}
    POST /state          {game_id, player}
    POST /end            {game_id, player}
    POST /respond        {game_id, player, action: "pass"}
    POST /damage         {game_id, player, target, amount: N}
    POST /destroy        {game_id, player, target_player, permanent}
    POST /wait           {game_id, player}  -- long-polls until your turn
    POST /judge          {game_id, player, question: "..."}
    POST /priority       {game_id}
"""
import json
import sys
import os
import random
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTP server that handles each request in a new thread."""
    daemon_threads = True

# Import game logic
from game_server import (
    cmd_create, cmd_hand, cmd_mulligan, cmd_keep,
    cmd_begin, cmd_draw, cmd_action, cmd_valid, cmd_state,
    cmd_end, cmd_respond, cmd_damage, cmd_destroy,
    cmd_modify, cmd_keyword, cmd_proliferate,
    cmd_equip, cmd_scry, cmd_mill, cmd_search, cmd_move, cmd_resolve_judge,
    cmd_judge, cmd_priority,
)

# Thread lock — serializes all game operations
_lock = threading.Lock()

# Active games for wait/long-polling
_wait_events = {}  # game_id -> threading.Event


def _notify_waiters(game_id):
    """Wake up any waiting agents."""
    if game_id in _wait_events:
        _wait_events[game_id].set()
        _wait_events[game_id] = threading.Event()


class GameHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Serve the game viewer HTML."""
        if self.path in ('/', '/viewer', '/viewer.html'):
            viewer_path = os.path.join(os.path.dirname(__file__), 'game_viewer.html')
            if os.path.exists(viewer_path):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                with open(viewer_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'game_viewer.html not found')
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._respond(400, {'error': 'Invalid JSON'})
            return

        path = self.path.strip('/')
        gid = data.get('game_id', '')
        player = data.get('player', '')

        try:
            if path == 'create':
                with _lock:
                    result = cmd_create(data.get('decklists', []), seed=data.get('seed'))
                    _wait_events[result['game_id']] = threading.Event()

            elif path == 'hand':
                with _lock:
                    result = cmd_hand(gid, player)

            elif path == 'mulligan':
                with _lock:
                    result = cmd_mulligan(gid, player)
                    _notify_waiters(gid)

            elif path == 'keep':
                with _lock:
                    result = cmd_keep(gid, player, data.get('bottom_cards'))
                    _notify_waiters(gid)

            elif path == 'begin':
                with _lock:
                    result = cmd_begin(gid, player)

            elif path == 'draw':
                with _lock:
                    result = cmd_draw(gid, player, data.get('count', 1))

            elif path == 'action':
                with _lock:
                    result = cmd_action(gid, player, data.get('action', ''))
                    _notify_waiters(gid)

            elif path == 'valid':
                with _lock:
                    result = cmd_valid(gid, player)

            elif path == 'state':
                with _lock:
                    result = cmd_state(gid, player)

            elif path == 'end':
                with _lock:
                    result = cmd_end(gid, player)
                    _notify_waiters(gid)

            elif path == 'respond':
                with _lock:
                    result = cmd_respond(gid, player, data.get('action', 'pass'))
                    _notify_waiters(gid)

            elif path == 'damage':
                with _lock:
                    result = cmd_damage(gid, player, data.get('target', ''), data.get('amount', 0))
                    _notify_waiters(gid)

            elif path == 'destroy':
                with _lock:
                    result = cmd_destroy(gid, player, data.get('target_player', ''), data.get('permanent', ''), exile=data.get('exile', False))
                    _notify_waiters(gid)

            elif path == 'modify':
                with _lock:
                    result = cmd_modify(gid, player, data.get('target_player', player),
                                        data.get('permanent', ''),
                                        data.get('counter_type', '+1/+1'),
                                        data.get('amount', 1))
                    _notify_waiters(gid)

            elif path == 'keyword':
                with _lock:
                    result = cmd_keyword(gid, player, data.get('target_player', player),
                                         data.get('permanent', ''),
                                         data.get('keyword', ''),
                                         data.get('remove', False))
                    _notify_waiters(gid)

            elif path == 'proliferate':
                with _lock:
                    result = cmd_proliferate(gid, player, data.get('targets', []))
                    _notify_waiters(gid)

            elif path == 'equip':
                with _lock:
                    result = cmd_equip(gid, player, data.get('equipment', ''), data.get('creature', ''))
                    _notify_waiters(gid)

            elif path == 'scry':
                with _lock:
                    result = cmd_scry(gid, player, data.get('count', 1), data.get('bottom'))

            elif path == 'mill':
                with _lock:
                    result = cmd_mill(gid, player, data.get('count', 1))
                    _notify_waiters(gid)

            elif path == 'search':
                with _lock:
                    result = cmd_search(gid, player, data.get('card_name', ''),
                                        data.get('destination', 'battlefield'),
                                        data.get('tapped', True))
                    _notify_waiters(gid)

            elif path == 'move':
                with _lock:
                    result = cmd_move(gid, player, data.get('card_name', ''),
                                      data.get('from_zone', ''),
                                      data.get('to_zone', ''))
                    _notify_waiters(gid)

            elif path == 'resolve_judge':
                with _lock:
                    result = cmd_resolve_judge(gid, data.get('ruling', ''))
                    _notify_waiters(gid)

            elif path == 'judge':
                with _lock:
                    result = cmd_judge(gid, player, data.get('question', ''))
                    _notify_waiters(gid)

            elif path == 'priority':
                with _lock:
                    result = cmd_priority(gid)

            elif path == 'events':
                with _lock:
                    import pickle as _pkl
                    pkl_path = f'/tmp/mtg_games/{gid}.pkl'
                    if os.path.exists(pkl_path):
                        with open(pkl_path, 'rb') as _f:
                            _data = _pkl.load(_f)
                        engine = _data.get('engine') or _data
                        result = {'events': engine.events, 'count': len(engine.events)}
                    else:
                        result = {'error': 'Game not found'}

            elif path == 'games':
                result = self._list_games()

            elif path == 'wait':
                result = self._handle_wait(gid, player, data.get('timeout', 120))

            else:
                result = {'error': f'Unknown endpoint: {path}'}

            self._respond(200, result)

        except Exception as e:
            self._respond(500, {'error': str(e)})

    def _handle_wait(self, game_id, player_name, timeout=120):
        """Long-poll until it's the player's turn."""
        start = time.time()

        while time.time() - start < timeout:
            with _lock:
                try:
                    result = cmd_priority(game_id)
                except Exception:
                    return {'error': 'Game not found'}

                phase = result.get('phase', '')

                if phase == 'done':
                    return {'status': 'game_over'}

                if phase == 'mulligan':
                    pending = result.get('mulligan_pending', [])
                    # Sequential mulligans: only the current player in order gets prompted
                    mulligan_order = result.get('mulligan_order', pending)
                    mulligan_current = result.get('mulligan_current', 0)
                    if mulligan_current < len(mulligan_order):
                        current_mulligan_player = mulligan_order[mulligan_current]
                        if player_name.lower() in current_mulligan_player.lower() or current_mulligan_player.lower() in player_name.lower():
                            hand = cmd_hand(game_id, player_name)
                            return {'status': 'mulligan', 'message': f'Your turn to mulligan ({mulligan_current+1}/{len(mulligan_order)})', 'hand': hand}

                if phase == 'playing':
                    active = result.get('active_player', '')
                    pq = result.get('priority_queue', [])

                    # Judge pause — tell players to wait
                    if 'JUDGE' in pq:
                        return {'status': 'judge_pause', 'message': 'Judge is resolving a rules question. Please wait.'}

                    # Is it our turn?
                    if player_name.lower() in active.lower() or active.lower() in player_name.lower():
                        if not pq:
                            return {'status': 'your_turn', 'turn': result.get('turn', 0)}

                    # Do we have priority?
                    for name in pq:
                        if player_name.lower() in name.lower() or name.lower() in player_name.lower():
                            return {'status': 'priority', 'last_action': ''}

            # Wait for a state change notification, or timeout after 3s
            evt = _wait_events.get(game_id)
            if evt:
                evt.wait(timeout=3)
            else:
                time.sleep(3)

        return {'status': 'timeout'}

    def _list_games(self):
        """List all active games."""
        import glob
        games = []
        for pkl_path in glob.glob('/tmp/mtg_games/*.pkl'):
            gid = os.path.basename(pkl_path).replace('.pkl', '')
            try:
                with _lock:
                    p = cmd_priority(gid)
                if 'error' not in p:
                    players = ', '.join(n.split(',')[0][:15] for n in p.get('mulligan_order', []))
                    games.append({
                        'game_id': gid,
                        'turn': p.get('turn', 0),
                        'phase': p.get('phase', '?'),
                        'active_player': p.get('active_player', '?'),
                        'players': players,
                        'priority_queue': p.get('priority_queue', []),
                    })
            except Exception:
                pass
        games.sort(key=lambda g: g['game_id'])
        return {'games': games}

    def _respond(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def log_message(self, format, *args):
        # Compact logging
        msg = format % args
        if '/wait' not in msg:  # Don't spam wait polls
            print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def main():
    port = 8080
    if '--port' in sys.argv:
        idx = sys.argv.index('--port')
        port = int(sys.argv[idx + 1])

    server = ThreadingHTTPServer(('127.0.0.1', port), GameHandler)
    server.socket.settimeout(1)  # Allow clean shutdown

    print(f"Game server running on http://127.0.0.1:{port}", file=sys.stderr)
    print(f"Endpoints: create, hand, mulligan, keep, begin, action, valid, state, end, respond, damage, destroy, wait, judge, priority", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
        server.server_close()


if __name__ == '__main__':
    main()
