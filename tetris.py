#!/usr/bin/env python3
"""
TETRIS w terminalu.

Uruchom:  python3 tetris.py
Windows:  pip install windows-curses

Sterowanie:
  <- ->  / a d     ruch
  ^  / w / x       obrot w prawo
  z                obrot w lewo
  v / s            soft drop
  spacja           hard drop
  c                hold
  p                pauza
  q / Esc          wyjscie
"""
import curses
import os
import random
import time

os.environ.setdefault("ESCDELAY", "25")

W, H = 10, 20
KINDS = "IJLSZTO"
BEST_FILE = os.path.expanduser("~/.tetris_best")

MATS = {
    "I": [[0, 0, 0, 0], [1, 1, 1, 1], [0, 0, 0, 0], [0, 0, 0, 0]],
    "J": [[1, 0, 0], [1, 1, 1], [0, 0, 0]],
    "L": [[0, 0, 1], [1, 1, 1], [0, 0, 0]],
    "S": [[0, 1, 1], [1, 1, 0], [0, 0, 0]],
    "Z": [[1, 1, 0], [0, 1, 1], [0, 0, 0]],
    "T": [[0, 1, 0], [1, 1, 1], [0, 0, 0]],
    "O": [[1, 1], [1, 1]],
}


def rotate_cw(m):
    n = len(m)
    return [[m[n - 1 - c][r] for c in range(n)] for r in range(n)]


ROTS = {}
for _k, _m in MATS.items():
    _states, _cur = [], _m
    for _ in range(4):
        _states.append([(r, c) for r, row in enumerate(_cur) for c, v in enumerate(row) if v])
        _cur = rotate_cw(_cur)
    ROTS[_k] = _states

# SRS wall kicks: (x, y) z osia y w gore (przy uzyciu odwracamy y)
KICKS = {
    (0, 1): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    (1, 0): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
    (1, 2): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
    (2, 1): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    (2, 3): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
    (3, 2): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    (3, 0): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    (0, 3): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
}
KICKS_I = {
    (0, 1): [(0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)],
    (1, 0): [(0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)],
    (1, 2): [(0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)],
    (2, 1): [(0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)],
    (2, 3): [(0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)],
    (3, 2): [(0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)],
    (3, 0): [(0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)],
    (0, 3): [(0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)],
}

LINE_SCORES = {1: 100, 2: 300, 3: 500, 4: 800}
LOCK_DELAY = 0.5
MAX_RESETS = 15


class Game:
    def __init__(self, best=0):
        self.board = [[None] * W for _ in range(H)]
        self.bag, self.queue = [], []
        self.hold, self.hold_used = None, False
        self.score = self.lines = 0
        self.level = 1
        self.best = best
        self.over = False
        self.anim = None
        self.flash_rows = []
        self.last_clear = ""
        while len(self.queue) < 5:
            self.queue.append(self._from_bag())
        self.spawn()

    # --- generowanie klockow (7-bag) ---
    def _from_bag(self):
        if not self.bag:
            self.bag = list(KINDS)
            random.shuffle(self.bag)
        return self.bag.pop()

    def spawn(self, kind=None):
        if kind is None:
            kind = self.queue.pop(0)
            self.queue.append(self._from_bag())
        self.kind, self.rot = kind, 0
        self.r = -1 if kind == "I" else 0
        self.c = 4 if kind == "O" else 3
        self.last_fall = time.time()
        self.lock_start = None
        self.resets = 0
        if not self.valid(self.kind, self.rot, self.r, self.c):
            self.over = True

    # --- kolizje ---
    @staticmethod
    def cells(kind, rot, r, c):
        return [(r + dr, c + dc) for dr, dc in ROTS[kind][rot]]

    def valid(self, kind, rot, r, c):
        for y, x in self.cells(kind, rot, r, c):
            if x < 0 or x >= W or y >= H:
                return False
            if y >= 0 and self.board[y][x] is not None:
                return False
        return True

    def ghost_r(self):
        r = self.r
        while self.valid(self.kind, self.rot, r + 1, self.c):
            r += 1
        return r

    # --- ruchy ---
    def _touched(self):
        if self.lock_start is not None and self.resets < MAX_RESETS:
            self.lock_start = time.time()
            self.resets += 1

    def move(self, dc):
        if self.valid(self.kind, self.rot, self.r, self.c + dc):
            self.c += dc
            self._touched()

    def rotate(self, d):
        new = (self.rot + d) % 4
        table = KICKS_I if self.kind == "I" else KICKS
        for kx, ky in table[(self.rot, new)]:
            nr, nc = self.r - ky, self.c + kx
            if self.valid(self.kind, new, nr, nc):
                self.rot, self.r, self.c = new, nr, nc
                self._touched()
                return

    def soft_drop(self):
        if self.valid(self.kind, self.rot, self.r + 1, self.c):
            self.r += 1
            self.score += 1
            self.last_fall = time.time()

    def hard_drop(self):
        gr = self.ghost_r()
        self.score += 2 * (gr - self.r)
        self.r = gr
        self.lock()

    def hold_piece(self):
        if self.hold_used:
            return
        if self.hold is None:
            self.hold = self.kind
            self.spawn()
        else:
            self.hold, k = self.kind, self.hold
            self.spawn(k)
        self.hold_used = True

    # --- blokowanie i czyszczenie linii ---
    def lock(self):
        for y, x in self.cells(self.kind, self.rot, self.r, self.c):
            if y < 0:
                self.over = True
                return
            self.board[y][x] = self.kind
        full = [y for y in range(H) if all(self.board[y])]
        if full:
            if self.anim:
                self.flash_rows = full
                self.anim()
                self.flash_rows = []
            self.board = [row for i, row in enumerate(self.board) if i not in full]
            self.board = [[None] * W for _ in full] + self.board
            n = len(full)
            self.score += LINE_SCORES[n] * self.level
            self.lines += n
            self.level = self.lines // 10 + 1
            self.last_clear = {1: "SINGLE", 2: "DOUBLE", 3: "TRIPLE", 4: "TETRIS!"}[n]
        self.best = max(self.best, self.score)
        self.hold_used = False
        self.spawn()

    def interval(self):
        return max(0.03, 0.8 * (0.85 ** (self.level - 1)))

    def update(self, now):
        if self.over:
            return
        grounded = not self.valid(self.kind, self.rot, self.r + 1, self.c)
        if grounded:
            if self.lock_start is None:
                self.lock_start = now
            elif now - self.lock_start >= LOCK_DELAY:
                self.lock()
                return
            self.last_fall = now
        else:
            self.lock_start = None
            steps = 0
            iv = self.interval()
            while now - self.last_fall >= iv and steps < 20:
                if not self.valid(self.kind, self.rot, self.r + 1, self.c):
                    break
                self.r += 1
                self.last_fall += iv
                steps += 1
        self.best = max(self.best, self.score)


# ---------------------------------------------------------------- rysowanie
PAIR_BG, PAIR_FG = {}, {}


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    big = curses.COLORS >= 256
    C = curses
    cols = {
        "I": C.COLOR_CYAN,
        "J": 27 if big else C.COLOR_BLUE,
        "L": 208 if big else C.COLOR_YELLOW,
        "S": C.COLOR_GREEN,
        "Z": C.COLOR_RED,
        "T": 129 if big else C.COLOR_MAGENTA,
        "O": 226 if big else C.COLOR_YELLOW,
    }
    for i, k in enumerate(KINDS):
        curses.init_pair(1 + i, cols[k], cols[k])
        curses.init_pair(11 + i, cols[k], -1)
        PAIR_BG[k] = curses.color_pair(1 + i)
        PAIR_FG[k] = curses.color_pair(11 + i) | curses.A_BOLD
    curses.init_pair(8, C.COLOR_WHITE, C.COLOR_WHITE)
    PAIR_BG["flash"] = curses.color_pair(8)


def put(scr, y, x, s, attr=0):
    try:
        scr.addstr(y, x, s, attr)
    except curses.error:
        pass


def cell(scr, y, x, kind, ghost=False):
    if ghost:
        put(scr, y, x, "[]", PAIR_FG[kind])
    else:
        put(scr, y, x, "  ", PAIR_BG[kind])


def mini(scr, y, x, kind):
    for dr, dc in ROTS[kind][0]:
        cell(scr, y + dr, x + 2 * dc, kind)


def draw(scr, g, paused=False):
    scr.erase()
    sh, sw = scr.getmaxyx()
    if sh < H + 4 or sw < 56:
        put(scr, 0, 0, "Powieksz okno terminala (min 56x24)")
        scr.refresh()
        return
    top = (sh - (H + 2)) // 2
    left = (sw - 54) // 2
    bx = left + 16
    bold = curses.A_BOLD

    put(scr, top - 1 if top > 0 else 0, bx + 7, "TETRIS", bold)

    # plansza
    for y in range(H):
        put(scr, top + 1 + y, bx, "|")
        put(scr, top + 1 + y, bx + 1 + 2 * W, "|")
        for x in range(W):
            k = g.board[y][x]
            px = bx + 1 + 2 * x
            if y in g.flash_rows:
                put(scr, top + 1 + y, px, "  ", PAIR_BG["flash"])
            elif k:
                cell(scr, top + 1 + y, px, k)
            else:
                put(scr, top + 1 + y, px, " .", curses.A_DIM)
    put(scr, top + 1 + H, bx, "+" + "-" * (2 * W) + "+")

    if not g.over:
        gr = g.ghost_r()
        for y, x in g.cells(g.kind, g.rot, gr, g.c):
            if y >= 0:
                cell(scr, top + 1 + y, bx + 1 + 2 * x, g.kind, ghost=True)
        for y, x in g.cells(g.kind, g.rot, g.r, g.c):
            if y >= 0:
                cell(scr, top + 1 + y, bx + 1 + 2 * x, g.kind)

    # hold
    put(scr, top + 1, left + 2, "HOLD", bold)
    if g.hold:
        mini(scr, top + 3, left + 2, g.hold)

    # statystyki
    put(scr, top + 9, left, "SCORE", bold)
    put(scr, top + 10, left, f"{g.score}")
    put(scr, top + 12, left, "LINES", bold)
    put(scr, top + 13, left, f"{g.lines}")
    put(scr, top + 15, left, "LEVEL", bold)
    put(scr, top + 16, left, f"{g.level}")
    put(scr, top + 18, left, "BEST", bold)
    put(scr, top + 19, left, f"{g.best}")

    # next
    rx = bx + 2 * W + 5
    put(scr, top + 1, rx, "NEXT", bold)
    for i, k in enumerate(g.queue[:3]):
        mini(scr, top + 3 + i * 3, rx, k)

    help_lines = [
        "<- -> ruch",
        "^ / x obrot",
        "z obrot wstecz",
        "v soft drop",
        "spacja hard drop",
        "c hold",
        "p pauza",
        "q wyjscie",
    ]
    for i, s in enumerate(help_lines):
        put(scr, top + 12 + i, rx, s, curses.A_DIM)

    if g.last_clear:
        put(scr, top + 10, rx, g.last_clear, bold)

    def center(y, text):
        put(scr, top + 1 + y, bx + 1 + (2 * W - len(text)) // 2, text, bold | curses.A_REVERSE)

    if g.over:
        center(8, "  GAME OVER  ")
        center(10, " R - jeszcze raz ")
        center(11, "    Q - wyjscie  ")
    elif paused:
        center(9, "  PAUZA  ")
    scr.refresh()


def read_keys(scr):
    keys = []
    scr.timeout(16)
    k = scr.getch()
    scr.timeout(0)
    while k != -1 and len(keys) < 8:
        keys.append(k)
        k = scr.getch()
    scr.timeout(16)
    return keys


def is_key(k, *chars):
    return any(k == ord(c) or k == ord(c.upper()) for c in chars)


def load_best():
    try:
        with open(BEST_FILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def save_best(v):
    try:
        with open(BEST_FILE, "w") as f:
            f.write(str(v))
    except OSError:
        pass


def play(scr, best):
    g = Game(best)
    g.anim = lambda: (draw(scr, g), curses.napms(140))
    paused = False
    while True:
        now = time.time()
        for k in read_keys(scr):
            if k == 27 or is_key(k, "q"):
                save_best(g.best)
                return "quit", g.best
            if g.over:
                if is_key(k, "r") or k in (10, 13):
                    save_best(g.best)
                    return "restart", g.best
                continue
            if is_key(k, "p"):
                paused = not paused
                if not paused:
                    g.last_fall = time.time()
                    if g.lock_start is not None:
                        g.lock_start = time.time()
                continue
            if paused:
                continue
            if k in (curses.KEY_LEFT,) or is_key(k, "a", "h"):
                g.move(-1)
            elif k in (curses.KEY_RIGHT,) or is_key(k, "d", "l"):
                g.move(1)
            elif k in (curses.KEY_DOWN,) or is_key(k, "s", "v", "j"):
                g.soft_drop()
            elif k in (curses.KEY_UP,) or is_key(k, "w", "x", "k"):
                g.rotate(1)
            elif is_key(k, "z"):
                g.rotate(-1)
            elif k == ord(" "):
                g.hard_drop()
            elif is_key(k, "c"):
                g.hold_piece()
        if not paused and not g.over:
            g.update(time.time())
        if g.over:
            save_best(g.best)
        draw(scr, g, paused)


def title(scr):
    scr.nodelay(False)
    scr.timeout(-1)
    scr.erase()
    sh, sw = scr.getmaxyx()
    art = [
        "####  ####  ####  ###   ###   ####",
        " ##   ##     ##   ## #    #   ##   ",
        " ##   ###    ##   ###     #    ### ",
        " ##   ##     ##   ## #    #      ##",
        " ##   ####   ##   ##  #  ###  #### ",
    ]
    y0 = max(0, sh // 2 - 5)
    for i, line in enumerate(art):
        put(scr, y0 + i, max(0, (sw - len(line)) // 2), line,
            PAIR_FG[KINDS[i % 7]])
    msg = "nacisnij dowolny klawisz, zeby zagrac"
    put(scr, y0 + 7, max(0, (sw - len(msg)) // 2), msg, curses.A_BOLD)
    scr.refresh()
    scr.getch()


def main(scr):
    curses.curs_set(0)
    scr.keypad(True)
    init_colors()
    title(scr)
    best = load_best()
    while True:
        action, best = play(scr, best)
        if action == "quit":
            break


if __name__ == "__main__":
    random.seed()
    curses.wrapper(main)
