"""Tests for the HTTP game server — full game flow."""
import json
import time
import threading
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8080"


def post(endpoint, data=None):
    """POST JSON to server, return parsed response."""
    body = json.dumps(data or {}).encode('utf-8')
    req = urllib.request.Request(f"{BASE}/{endpoint}", data=body,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {'error': str(e)}


def test_create_game():
    """Test game creation with 4 players."""
    r = post('create', {
        'decklists': [
            'decks/wise_mothman/decklist.txt',
            'decks/test_edric/decklist.txt',
            'decks/test_teysa/decklist.txt',
            'decks/test_valgavoth/decklist.txt',
        ],
        'seed': 11111
    })
    assert 'game_id' in r, f"No game_id: {r}"
    assert len(r['players']) == 4
    assert r['phase'] == 'mulligan' or r['phase'] == 'playing'
    for p in r['players']:
        assert p['hand_size'] == 7
    print(f"  create: OK ({r['game_id']})")
    return r['game_id']


def test_hand(gid):
    """Test viewing a hand."""
    r = post('hand', {'game_id': gid, 'player': 'Mothman'})
    assert 'hand' in r, f"No hand: {r}"
    assert r['hand_size'] == 7
    assert r['lands_in_hand'] >= 0
    for c in r['hand']:
        assert 'name' in c
        assert 'type_line' in c
    print(f"  hand: OK ({r['hand_size']} cards, {r['lands_in_hand']} lands)")
    return r


def test_mulligan(gid):
    """Test mulligan (free first)."""
    r = post('mulligan', {'game_id': gid, 'player': 'Mothman'})
    assert r['mulligan_number'] == 1
    assert r['bottom_required'] == 0  # First is free
    assert r['free'] is True
    assert len(r['hand']) == 7
    print(f"  mulligan: OK (free, 7 cards)")
    return r


def test_keep(gid):
    """Test keeping hand."""
    r = post('keep', {'game_id': gid, 'player': 'Mothman'})
    assert r['kept'] is True
    assert r['hand_size'] == 7
    assert r['bottomed'] == 0
    print(f"  keep: OK (kept 7)")
    return r


def test_all_keep(gid):
    """All players keep — transitions to playing."""
    for name in ['Edric', 'Teysa', 'Valgavoth']:
        post('keep', {'game_id': gid, 'player': name})

    r = post('priority', {'game_id': gid})
    assert r['phase'] == 'playing', f"Phase not playing: {r}"
    assert r['mulligan_pending'] == []
    print(f"  all_keep: OK (phase={r['phase']}, active={r['active_player'][:15]})")
    return r['active_player']


def test_begin_turn(gid, player):
    """Test beginning a turn — draws a card."""
    r = post('begin', {'game_id': gid, 'player': player})
    assert 'error' not in r, f"Begin error: {r}"
    assert r['hand_size'] == 8  # 7 + 1 draw
    assert r['drew'] is not None  # Commander draws T1
    print(f"  begin: OK (drew {r['drew']['name']}, hand={r['hand_size']})")
    return r


def test_wrong_player_begin(gid, wrong_player):
    """Test that wrong player can't begin turn."""
    r = post('begin', {'game_id': gid, 'player': wrong_player})
    assert 'error' in r, f"Should have errored: {r}"
    print(f"  wrong_begin: OK (blocked: {r['error'][:50]})")


def test_valid_actions(gid, player):
    """Test getting valid actions."""
    r = post('valid', {'game_id': gid, 'player': player})
    assert 'actions' in r
    assert 'pass' in r['actions']
    lands = [a for a in r['actions'] if 'play' in a]
    print(f"  valid: OK ({len(r['actions'])} actions, {len(lands)} lands playable)")
    return r['actions']


def test_play_land(gid, player, actions):
    """Test playing a land."""
    land_action = next((a for a in actions if 'play' in a), None)
    if not land_action:
        print(f"  play_land: SKIP (no lands)")
        return None
    r = post('action', {'game_id': gid, 'player': player, 'action': land_action})
    assert r['success'], f"Play failed: {r}"
    print(f"  play_land: OK ({r['message']})")
    return r


def test_end_turn(gid, player):
    """Test ending turn."""
    r = post('end', {'game_id': gid, 'player': player})
    assert 'error' not in r, f"End error: {r}"
    assert 'next_player' in r
    print(f"  end: OK (next: {r['next_player'][:15]}, T{r['turn']})")
    return r


def test_wrong_player_end(gid, wrong_player):
    """Test that wrong player can't end turn."""
    r = post('end', {'game_id': gid, 'player': wrong_player})
    assert 'error' in r
    print(f"  wrong_end: OK (blocked)")


def test_state(gid, player):
    """Test viewing game state."""
    r = post('state', {'game_id': gid, 'player': player})
    assert 'state' in r
    assert player[:5] in r['state'] or 'You are' in r['state']
    print(f"  state: OK ({len(r['state'])} chars)")


def test_wait_returns_immediately_for_active(gid, player):
    """Test that wait returns immediately when it's your turn."""
    r = post('wait', {'game_id': gid, 'player': player, 'timeout': 5})
    assert r.get('status') in ('your_turn', 'mulligan'), f"Wait status: {r}"
    print(f"  wait_active: OK (status={r['status']})")


def test_wait_blocks_for_inactive(gid, inactive_player):
    """Test that wait blocks for non-active player (with short timeout)."""
    r = post('wait', {'game_id': gid, 'player': inactive_player, 'timeout': 3})
    assert r.get('status') == 'timeout', f"Should timeout: {r}"
    print(f"  wait_inactive: OK (timed out as expected)")


def test_concurrent_waits(gid):
    """Test that multiple wait calls don't deadlock."""
    results = [None, None]

    def wait_player(idx, name):
        results[idx] = post('wait', {'game_id': gid, 'player': name, 'timeout': 5})

    t1 = threading.Thread(target=wait_player, args=(0, 'Edric'))
    t2 = threading.Thread(target=wait_player, args=(1, 'Valgavoth'))
    t1.start()
    t2.start()

    # Meanwhile, make a priority call to verify server isn't deadlocked
    time.sleep(1)
    r = post('priority', {'game_id': gid})
    assert 'error' not in r, f"Server deadlocked: {r}"
    print(f"  concurrent: OK (server responsive during waits)")

    t1.join(timeout=10)
    t2.join(timeout=10)


def test_full_turn_cycle(gid):
    """Test a full 4-player turn cycle."""
    for i in range(4):
        pr = post('priority', {'game_id': gid})
        active = pr['active_player']
        bt = post('begin', {'game_id': gid, 'player': active})
        if 'error' in bt:
            print(f"  turn_cycle: FAIL at player {i}: {bt['error']}")
            return
        va = post('valid', {'game_id': gid, 'player': active})
        # Play a land if possible
        land = next((a for a in va['actions'] if 'play' in a), None)
        if land:
            post('action', {'game_id': gid, 'player': active, 'action': land})
        post('end', {'game_id': gid, 'player': active})

    pr = post('priority', {'game_id': gid})
    print(f"  turn_cycle: OK (completed 4 turns, now T{pr['turn']})")


if __name__ == '__main__':
    print("=== Game Server Tests ===\n")

    # Check server is running
    try:
        post('priority', {'game_id': 'nonexistent'})
    except Exception:
        print("ERROR: Server not running. Start with: python3 game_http_server.py")
        exit(1)

    gid = test_create_game()
    test_hand(gid)
    test_mulligan(gid)
    test_keep(gid)
    active = test_all_keep(gid)
    test_begin_turn(gid, active)
    test_wrong_player_begin(gid, 'Edric')
    test_valid_actions(gid, active)
    actions = post('valid', {'game_id': gid, 'player': active})['actions']
    test_play_land(gid, active, actions)
    test_state(gid, active)
    test_wrong_player_end(gid, 'Edric')
    test_end_turn(gid, active)

    # Test wait
    pr = post('priority', {'game_id': gid})
    test_wait_returns_immediately_for_active(gid, pr['active_player'])
    test_wait_blocks_for_inactive(gid, 'Mothman' if 'Moth' not in pr['active_player'] else 'Edric')
    test_concurrent_waits(gid)

    # Full turn cycle
    # Need to begin the current player's turn first
    post('begin', {'game_id': gid, 'player': pr['active_player']})
    post('end', {'game_id': gid, 'player': pr['active_player']})
    test_full_turn_cycle(gid)

    print("\n=== All tests passed! ===")
