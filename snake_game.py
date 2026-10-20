import json
import math
import os
import random
import sys
import traceback

try:
    import pygame
except ImportError:
    print("Pygame is not installed.")
    print("Install it with:   pip install pygame")
    print("(or:  python -m pip install pygame   /   py -m pip install pygame on Windows)")
    input("Press Enter to close...")
    sys.exit(1)

# Older pygame versions don't support rounded rectangles (border_radius).
# Fall back to plain rectangles instead of crashing.
_orig_rect = pygame.draw.rect


def _safe_rect(surface, color, rect, width=0, **kwargs):
    try:
        return _orig_rect(surface, color, rect, width, **kwargs)
    except TypeError:
        return _orig_rect(surface, color, rect, width)


pygame.draw.rect = _safe_rect

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CELL_SIZE = 24
GRID_WIDTH = 26
GRID_HEIGHT = 18
TOP_BAR = 70
SCREEN_WIDTH = CELL_SIZE * GRID_WIDTH
SCREEN_HEIGHT = CELL_SIZE * GRID_HEIGHT + TOP_BAR

SPEEDS = {"Slow": 6, "Medium": 10, "Fast": 15}
SPEED_ORDER = ["Slow", "Medium", "Fast"]
MODES = ["Classic", "Wrap-around"]
SCORE_PER_LEVEL = 8
MAX_SPEED_BONUS = 6
MAX_OBSTACLES = 30
OBSTACLES_PER_LEVEL = 3

POWERUP_CHANCE = 0.35
POWERUP_LIFETIME = 8000      # ms on board before vanishing
EFFECT_DURATION = 7000       # ms for slow / double
BONUS_POINTS = 5
SHIELD_GRACE = 1000          # ms of safety after shield absorbs a hit

SAVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snake_highscores.json")

# Colors
BG = (24, 27, 34)
BLACK = (12, 13, 17)
WHITE = (240, 240, 240)
GRAY = (120, 120, 130)
YELLOW = (240, 200, 60)
RED = (220, 60, 60)
GRID_LINE = (34, 38, 47)
PANEL = (32, 36, 46)

SNAKE_TOP = (86, 214, 120)
SNAKE_LIGHT = (140, 235, 165)
SNAKE_MID = (52, 168, 90)
SNAKE_DARK = (24, 100, 52)
SNAKE_HEAD_TOP = (250, 235, 90)
SNAKE_HEAD_LIGHT = (255, 245, 150)
SNAKE_HEAD_MID = (220, 180, 40)
SNAKE_HEAD_DARK = (150, 115, 15)

SHIELD_TOP = (120, 230, 255)
SHIELD_LIGHT = (180, 245, 255)
SHIELD_MID = (60, 170, 220)
SHIELD_DARK = (20, 100, 150)

ROCK_TOP = (150, 154, 168)
ROCK_LIGHT = (185, 189, 202)
ROCK_MID = (105, 109, 124)
ROCK_DARK = (62, 65, 78)

FOOD_LIGHT = (255, 140, 130)
FOOD_MID = (220, 60, 60)
FOOD_DARK = (130, 25, 25)

# Power-up definitions: key -> (label, color, name)
POWERUPS = {
    "bonus": ("$", (255, 210, 50), "Bonus +5"),
    "slow": ("S", (90, 170, 255), "Slow-Mo"),
    "double": ("x2", (190, 110, 255), "Double Score"),
    "shield": ("O", (90, 230, 240), "Shield"),
    "shrink": ("-", (255, 150, 60), "Shrink"),
}

UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)

MENU_ITEMS = ["start", "speed", "mode", "obstacles", "controls", "quit"]


def load_scores():
    try:
        with open(SAVE_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def save_scores(scores):
    try:
        with open(SAVE_FILE, "w") as f:
            json.dump(scores, f)
    except OSError:
        pass


class SnakeGame:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("Snake Game 3D")
        self.clock = pygame.time.Clock()
        self.font_tiny = self.make_font(16)
        self.font_small = self.make_font(22)
        self.font_med = self.make_font(28, bold=True)
        self.font_big = self.make_font(48, bold=True)

        self.scores = load_scores()
        self.state = "menu"          # menu, controls, playing, paused, game_over
        self.menu_idx = 0
        self.selected_speed_idx = 1
        self.mode_idx = 0
        self.obstacles_on = True
        self.pause_started = 0
        self.new_record = False
        self.particles = []
        self.floaters = []           # floating "+5" texts
        self.reset()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def make_font(size, bold=False):
        try:
            return pygame.font.SysFont("consolas,couriernew,dejavusansmono,monospace", size, bold=bold)
        except Exception:
            return pygame.font.Font(None, size + 6)

    @property
    def wrap(self):
        return MODES[self.mode_idx] == "Wrap-around"

    def score_key(self):
        return f"{SPEED_ORDER[self.selected_speed_idx]}|{MODES[self.mode_idx]}|{'Obs' if self.obstacles_on else 'NoObs'}"

    @property
    def high_score(self):
        return self.scores.get(self.score_key(), 0)

    def now(self):
        return pygame.time.get_ticks()

    def quit(self):
        pygame.quit()
        sys.exit()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def reset(self):
        cx, cy = GRID_WIDTH // 2, GRID_HEIGHT // 2
        self.snake = [(cx, cy), (cx - 1, cy), (cx - 2, cy)]
        self.direction = RIGHT
        self.queue = []
        self.score = 0
        self.level = 1
        self.foods_eaten = 0
        self.speed_name = SPEED_ORDER[self.selected_speed_idx]
        self.base_fps = SPEEDS[self.speed_name]
        self.obstacles = set()
        self.powerup = None         # (pos, kind, expire_tick)
        self.effects = {}           # kind -> end tick
        self.shield = False
        self.invuln_until = 0
        self.particles = []
        self.floaters = []
        self.new_record = False
        self.last_step = self.now()
        self.food = None
        self.food = self.spawn_food()

    def free_cells(self):
        blocked = set(self.snake) | self.obstacles
        if getattr(self, "food", None):
            blocked.add(self.food)
        if self.powerup:
            blocked.add(self.powerup[0])
        return [(x, y) for x in range(GRID_WIDTH) for y in range(GRID_HEIGHT)
                if (x, y) not in blocked]

    def spawn_food(self):
        free = self.free_cells()
        return random.choice(free) if free else None

    def spawn_powerup(self):
        free = self.free_cells()
        if not free:
            return
        kind = random.choice(list(POWERUPS.keys()))
        self.powerup = (random.choice(free), kind, self.now() + POWERUP_LIFETIME)

    def add_obstacles(self, count):
        hx, hy = self.snake[0]
        free = [c for c in self.free_cells()
                if abs(c[0] - hx) + abs(c[1] - hy) > 5
                and 1 <= c[0] < GRID_WIDTH - 1 and 1 <= c[1] < GRID_HEIGHT - 1]
        random.shuffle(free)
        for cell in free[:count]:
            if len(self.obstacles) < MAX_OBSTACLES:
                self.obstacles.add(cell)

    # ------------------------------------------------------------------
    # Timing / speed
    # ------------------------------------------------------------------
    def current_fps(self):
        fps = self.base_fps + min(self.level - 1, MAX_SPEED_BONUS)
        if "slow" in self.effects:
            fps = max(4, int(fps * 0.6))
        return fps

    def shift_times(self, delta):
        """Push all timers forward after a pause."""
        self.effects = {k: v + delta for k, v in self.effects.items()}
        self.invuln_until += delta
        self.last_step += delta
        if self.powerup:
            pos, kind, exp = self.powerup
            self.powerup = (pos, kind, exp + delta)

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def handle_input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit()
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.state == "menu":
                    mx, my = event.pos
                    panel = pygame.Rect(SCREEN_WIDTH // 2 - 230, 125, 460, 250)
                    if panel.collidepoint(mx, my):
                        clicked_idx = (my - 140) // 38
                        if 0 <= clicked_idx < len(MENU_ITEMS):
                            self.menu_idx = clicked_idx
                            item = MENU_ITEMS[clicked_idx]
                            if item == "start":
                                self.reset()
                                self.state = "playing"
                            elif item == "controls":
                                self.state = "controls"
                            elif item == "quit":
                                self.quit()
                            else:
                                self.change_option(item, 1)
                elif self.state == "controls":
                    self.state = "menu"
                elif self.state == "paused":
                    self.shift_times(self.now() - self.pause_started)
                    self.state = "playing"
                elif self.state == "game_over":
                    self.reset()
                    self.state = "playing"
                continue
            if event.type != pygame.KEYDOWN:
                continue
            key = event.key
            if self.state == "menu":
                self.input_menu(key)
            elif self.state == "controls":
                if key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE, pygame.K_BACKSPACE):
                    self.state = "menu"
            elif self.state == "playing":
                self.input_playing(key)
            elif self.state == "paused":
                if key in (pygame.K_p, pygame.K_SPACE, pygame.K_RETURN):
                    self.shift_times(self.now() - self.pause_started)
                    self.state = "playing"
                elif key == pygame.K_m:
                    self.state = "menu"
                elif key in (pygame.K_q, pygame.K_ESCAPE):
                    self.quit()
            elif self.state == "game_over":
                if key in (pygame.K_RETURN, pygame.K_SPACE):
                    self.reset()
                    self.state = "playing"
                elif key in (pygame.K_r, pygame.K_m):
                    self.state = "menu"
                elif key in (pygame.K_q, pygame.K_ESCAPE):
                    self.quit()

    def input_menu(self, key):
        item = MENU_ITEMS[self.menu_idx]
        if key in (pygame.K_UP, pygame.K_w):
            self.menu_idx = (self.menu_idx - 1) % len(MENU_ITEMS)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.menu_idx = (self.menu_idx + 1) % len(MENU_ITEMS)
        elif key in (pygame.K_LEFT, pygame.K_a):
            self.change_option(item, -1)
        elif key in (pygame.K_RIGHT, pygame.K_d):
            self.change_option(item, 1)
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            if item == "start":
                self.reset()
                self.state = "playing"
            elif item == "controls":
                self.state = "controls"
            elif item == "quit":
                self.quit()
            else:
                self.change_option(item, 1)
        elif key in (pygame.K_q, pygame.K_ESCAPE):
            self.quit()

    def change_option(self, item, step):
        if item == "speed":
            self.selected_speed_idx = (self.selected_speed_idx + step) % len(SPEED_ORDER)
        elif item == "mode":
            self.mode_idx = (self.mode_idx + step) % len(MODES)
        elif item == "obstacles":
            self.obstacles_on = not self.obstacles_on

    def input_playing(self, key):
        mapping = {
            pygame.K_UP: UP, pygame.K_w: UP,
            pygame.K_DOWN: DOWN, pygame.K_s: DOWN,
            pygame.K_LEFT: LEFT, pygame.K_a: LEFT,
            pygame.K_RIGHT: RIGHT, pygame.K_d: RIGHT,
        }
        if key in mapping:
            new_dir = mapping[key]
            last = self.queue[-1] if self.queue else self.direction
            opposite = (-last[0], -last[1])
            if new_dir != opposite and new_dir != last and len(self.queue) < 3:
                self.queue.append(new_dir)
        elif key in (pygame.K_p, pygame.K_SPACE):
            self.pause_started = self.now()
            self.state = "paused"
        elif key in (pygame.K_q, pygame.K_ESCAPE):
            self.quit()

    # ------------------------------------------------------------------
    # Game logic
    # ------------------------------------------------------------------
    def update(self):
        self.update_particles()
        if self.state != "playing":
            return
        now = self.now()

        # expire timed things
        self.effects = {k: v for k, v in self.effects.items() if v > now}
        if self.powerup and self.powerup[2] <= now:
            self.powerup = None

        interval = 1000.0 / self.current_fps()
        if now - self.last_step >= interval:
            self.last_step = now
            self.step()

    def step(self):
        if self.queue:
            self.direction = self.queue.pop(0)
        hx, hy = self.snake[0]
        dx, dy = self.direction
        nx, ny = hx + dx, hy + dy

        blocked = False
        if self.wrap:
            nx %= GRID_WIDTH
            ny %= GRID_HEIGHT
        elif not (0 <= nx < GRID_WIDTH and 0 <= ny < GRID_HEIGHT):
            blocked = True
        new_head = (nx, ny)

        eating = (new_head == self.food)
        body_check = self.snake if eating else self.snake[:-1]
        if not blocked and (new_head in self.obstacles or new_head in body_check):
            blocked = True

        if blocked:
            now = self.now()
            if self.shield:
                self.shield = False
                self.invuln_until = now + SHIELD_GRACE
                self.burst(self.snake[0], SHIELD_TOP, 18)
                self.floater(self.snake[0], "Shield!", SHIELD_TOP)
                return
            if now < self.invuln_until:
                return
            self.end_game()
            return

        self.snake.insert(0, new_head)
        grew = False

        if eating:
            mult = 2 if "double" in self.effects else 1
            self.add_score(1 * mult, new_head)
            self.burst(new_head, FOOD_LIGHT, 14)
            self.foods_eaten += 1
            grew = True
            self.food = None
            self.food = self.spawn_food()
            if self.powerup is None and random.random() < POWERUP_CHANCE:
                self.spawn_powerup()

        if self.powerup and new_head == self.powerup[0]:
            self.collect_powerup(self.powerup[1], new_head)
            self.powerup = None

        if not grew:
            self.snake.pop()

    def add_score(self, points, pos):
        self.score += points
        self.floater(pos, f"+{points}", WHITE)
        if self.score > self.high_score:
            self.scores[self.score_key()] = self.score
            self.new_record = True
        new_level = self.score // SCORE_PER_LEVEL + 1
        if new_level > self.level:
            self.level = new_level
            self.floater(self.snake[0], f"LEVEL {self.level}", YELLOW)
            if self.obstacles_on:
                self.add_obstacles(OBSTACLES_PER_LEVEL)

    def collect_powerup(self, kind, pos):
        label, color, name = POWERUPS[kind]
        now = self.now()
        self.burst(pos, color, 20)
        self.floater(pos, name, color)
        if kind == "bonus":
            mult = 2 if "double" in self.effects else 1
            self.add_score(BONUS_POINTS * mult, pos)
        elif kind in ("slow", "double"):
            self.effects[kind] = now + EFFECT_DURATION
        elif kind == "shield":
            self.shield = True
        elif kind == "shrink":
            remove = min(3, max(0, len(self.snake) - 3))
            if remove:
                del self.snake[-remove:]

    def end_game(self):
        self.state = "game_over"
        if self.score >= self.scores.get(self.score_key(), 0):
            self.scores[self.score_key()] = self.score
        save_scores(self.scores)
        for seg in self.snake[::2]:
            self.burst(seg, SNAKE_MID, 4)

    # ------------------------------------------------------------------
    # Particles / floating text
    # ------------------------------------------------------------------
    def burst(self, cell, color, n):
        cx = cell[0] * CELL_SIZE + CELL_SIZE / 2
        cy = cell[1] * CELL_SIZE + TOP_BAR + CELL_SIZE / 2
        for _ in range(n):
            ang = random.uniform(0, math.tau)
            spd = random.uniform(40, 160)
            self.particles.append([cx, cy, math.cos(ang) * spd, math.sin(ang) * spd,
                                   random.uniform(0.35, 0.8), color])

    def floater(self, cell, text, color):
        x = cell[0] * CELL_SIZE + CELL_SIZE / 2
        y = cell[1] * CELL_SIZE + TOP_BAR
        self.floaters.append([x, y, 1.0, text, color])

    def update_particles(self):
        dt = self.clock.get_time() / 1000.0
        for p in self.particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[4] -= dt
        self.particles = [p for p in self.particles if p[4] > 0]
        for f in self.floaters:
            f[1] -= 30 * dt
            f[2] -= dt
        self.floaters = [f for f in self.floaters if f[2] > 0]

    # ------------------------------------------------------------------
    # Drawing primitives
    # ------------------------------------------------------------------
    def draw_cube(self, x, y, top, light, mid, dark, bevel=5):
        px = x * CELL_SIZE
        py = y * CELL_SIZE + TOP_BAR
        size = CELL_SIZE

        shadow_surf = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.rect(shadow_surf, (0, 0, 0, 70), (0, 0, size - 2, size - 2), border_radius=6)
        self.screen.blit(shadow_surf, (px + 3, py + 4))

        base_rect = (px + 1, py + 1, size - 2, size - 2)
        pygame.draw.rect(self.screen, mid, base_rect, border_radius=6)

        highlight_poly = [
            (px + 1, py + 1 + bevel),
            (px + 1 + bevel, py + 1),
            (px + size - 1 - bevel, py + 1),
            (px + size - 1, py + 1 + bevel),
            (px + size - 1 - bevel, py + 1 + 2 * bevel),
            (px + 1 + bevel, py + 1 + 2 * bevel),
        ]
        pygame.draw.polygon(self.screen, light, highlight_poly)
        pygame.draw.rect(self.screen, top, (px + 1 + bevel, py + 1, size - 2 - 2 * bevel, bevel))
        pygame.draw.rect(self.screen, dark, (px + 1, py + size - 1 - bevel, size - 2, bevel), border_radius=4)
        pygame.draw.rect(self.screen, BLACK, base_rect, width=1, border_radius=6)

    def draw_eyes(self, x, y):
        cx = x * CELL_SIZE + CELL_SIZE // 2
        cy = y * CELL_SIZE + TOP_BAR + CELL_SIZE // 2
        dx, dy = self.direction
        # perpendicular offset for the two eyes
        px, py = -dy, dx
        for side in (-1, 1):
            ex = cx + dx * 4 + px * 5 * side
            ey = cy + dy * 4 + py * 5 * side
            pygame.draw.circle(self.screen, WHITE, (ex, ey), 3)
            pygame.draw.circle(self.screen, BLACK, (ex + dx, ey + dy), 1)

    def draw_food(self):
        if not self.food:
            return
        fx, fy = self.food
        px = fx * CELL_SIZE + CELL_SIZE // 2
        py = fy * CELL_SIZE + TOP_BAR + CELL_SIZE // 2
        pulse = math.sin(self.now() / 180.0) * 1.5
        radius = int(CELL_SIZE // 2 - 2 + pulse)

        shadow_surf = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
        pygame.draw.circle(shadow_surf, (0, 0, 0, 80), (CELL_SIZE // 2 + 2, CELL_SIZE // 2 + 3), radius)
        self.screen.blit(shadow_surf, (fx * CELL_SIZE, fy * CELL_SIZE + TOP_BAR))

        pygame.draw.circle(self.screen, FOOD_DARK, (px, py), radius)
        pygame.draw.circle(self.screen, FOOD_MID, (px, py), radius - 2)
        pygame.draw.circle(self.screen, FOOD_LIGHT, (px - radius // 3, py - radius // 3), max(radius // 3, 2))

    def draw_powerup(self):
        if not self.powerup:
            return
        (x, y), kind, expire = self.powerup
        label, color, _ = POWERUPS[kind]
        cx = x * CELL_SIZE + CELL_SIZE // 2
        cy = y * CELL_SIZE + TOP_BAR + CELL_SIZE // 2
        remaining = max(0, expire - self.now())
        # blink in the last 2 seconds
        if remaining < 2000 and (self.now() // 150) % 2 == 0:
            return
        r = CELL_SIZE // 2 - 1
        glow = pygame.Surface((CELL_SIZE * 2, CELL_SIZE * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow, color + (60,), (CELL_SIZE, CELL_SIZE), r + 5)
        self.screen.blit(glow, (cx - CELL_SIZE, cy - CELL_SIZE))
        pygame.draw.circle(self.screen, BLACK, (cx, cy), r)
        pygame.draw.circle(self.screen, color, (cx, cy), r - 2)
        txt = self.font_tiny.render(label, True, BLACK)
        self.screen.blit(txt, (cx - txt.get_width() // 2, cy - txt.get_height() // 2))
        # countdown arc
        frac = remaining / POWERUP_LIFETIME
        rect = pygame.Rect(cx - r - 2, cy - r - 2, 2 * r + 4, 2 * r + 4)
        pygame.draw.arc(self.screen, WHITE, rect, math.pi / 2,
                        math.pi / 2 + math.tau * frac, 2)

    def draw_grid_lines(self):
        for x in range(0, SCREEN_WIDTH, CELL_SIZE):
            pygame.draw.line(self.screen, GRID_LINE, (x, TOP_BAR), (x, SCREEN_HEIGHT), 1)
        for y in range(TOP_BAR, SCREEN_HEIGHT, CELL_SIZE):
            pygame.draw.line(self.screen, GRID_LINE, (0, y), (SCREEN_WIDTH, y), 1)
        if not self.wrap:
            pygame.draw.rect(self.screen, RED, (0, TOP_BAR, SCREEN_WIDTH, SCREEN_HEIGHT - TOP_BAR), 2)

    def draw_particles(self):
        for x, y, _, _, life, color in self.particles:
            size = max(1, int(4 * min(1, life * 2)))
            pygame.draw.rect(self.screen, color, (int(x), int(y), size, size))
        for x, y, life, text, color in self.floaters:
            surf = self.font_tiny.render(text, True, color)
            surf.set_alpha(int(255 * min(1, life * 2)))
            self.screen.blit(surf, (x - surf.get_width() // 2, y))

    def draw_top_bar(self):
        pygame.draw.rect(self.screen, BLACK, (0, 0, SCREEN_WIDTH, TOP_BAR))
        score_text = self.font_small.render(f"Score: {self.score}", True, WHITE)
        level_text = self.font_small.render(f"Lv {self.level}", True, GRAY)
        high_text = self.font_small.render(f"Best: {self.high_score}", True, YELLOW)
        self.screen.blit(score_text, (15, 8))
        self.screen.blit(level_text, (SCREEN_WIDTH // 2 - level_text.get_width() // 2, 8))
        self.screen.blit(high_text, (SCREEN_WIDTH - high_text.get_width() - 15, 8))

        info = f"{self.speed_name} | {MODES[self.mode_idx]} | Obstacles {'On' if self.obstacles_on else 'Off'}"
        info_s = self.font_tiny.render(info, True, GRAY)
        self.screen.blit(info_s, (15, 34))

        # active status badges
        now = self.now()
        badges = []
        if self.shield:
            badges.append(("Shield", POWERUPS["shield"][1], None))
        for kind in ("slow", "double"):
            if kind in self.effects:
                badges.append((POWERUPS[kind][2], POWERUPS[kind][1],
                               (self.effects[kind] - now) / 1000.0))
        x = 15
        for name, color, secs in badges:
            label = name if secs is None else f"{name} {secs:0.1f}s"
            s = self.font_tiny.render(label, True, BLACK)
            rect = pygame.Rect(x, 50, s.get_width() + 12, 18)
            pygame.draw.rect(self.screen, color, rect, border_radius=8)
            self.screen.blit(s, (x + 6, 51))
            x += rect.width + 8
        if not badges:
            hint = self.font_tiny.render("P: pause", True, GRAY)
            self.screen.blit(hint, (15, 50))

    # ------------------------------------------------------------------
    # Screens
    # ------------------------------------------------------------------
    def draw_center(self, font, text, color, y):
        s = font.render(text, True, color)
        self.screen.blit(s, (SCREEN_WIDTH // 2 - s.get_width() // 2, y))

    def draw_menu(self):
        self.screen.fill(BG)
        self.draw_grid_lines_menu()
        self.draw_center(self.font_big, "SNAKE 3D", SNAKE_TOP, 28)
        self.draw_center(self.font_tiny, "Eat, grow, collect power-ups, survive the levels", GRAY, 92)

        panel = pygame.Rect(SCREEN_WIDTH // 2 - 230, 125, 460, 250)
        pygame.draw.rect(self.screen, PANEL, panel, border_radius=14)
        pygame.draw.rect(self.screen, BLACK, panel, width=2, border_radius=14)

        labels = {
            "start": "▶ PLAY GAME",
            "speed": f"Speed:  < {SPEED_ORDER[self.selected_speed_idx]} ({SPEEDS[SPEED_ORDER[self.selected_speed_idx]]}) >",
            "mode": f"Mode:  < {MODES[self.mode_idx]} >",
            "obstacles": f"Obstacles:  < {'On' if self.obstacles_on else 'Off'} >",
            "controls": "Controls & Power-ups",
            "quit": "Quit",
        }
        for i, item in enumerate(MENU_ITEMS):
            selected = (i == self.menu_idx)
            color = YELLOW if selected else WHITE
            text = labels[item]
            if selected and item in ("start", "controls", "quit"):
                text = f"> {text} <"
            s = self.font_med.render(text, True, color)
            y = 140 + i * 38
            if selected:
                bar = pygame.Rect(panel.x + 12, y - 2, panel.width - 24, 36)
                pygame.draw.rect(self.screen, (50, 56, 70), bar, border_radius=8)
            self.screen.blit(s, (SCREEN_WIDTH // 2 - s.get_width() // 2, y))

        self.draw_center(self.font_small, f"Best ({self.setup_label()}): {self.high_score}", YELLOW, 392)
        self.draw_center(self.font_tiny,
                          "Click an option or use UP/DOWN, LEFT/RIGHT and ENTER   |   Q: Quit", GRAY, SCREEN_HEIGHT - 30)

    def setup_label(self):
        return f"{SPEED_ORDER[self.selected_speed_idx]}, {MODES[self.mode_idx]}"

    def draw_grid_lines_menu(self):
        for x in range(0, SCREEN_WIDTH, CELL_SIZE):
            pygame.draw.line(self.screen, GRID_LINE, (x, 0), (x, SCREEN_HEIGHT), 1)
        for y in range(0, SCREEN_HEIGHT, CELL_SIZE):
            pygame.draw.line(self.screen, GRID_LINE, (0, y), (SCREEN_WIDTH, y), 1)

    def draw_controls(self):
        self.screen.fill(BG)
        self.draw_center(self.font_med, "CONTROLS & POWER-UPS", SNAKE_TOP, 14)
        lines = [
            ("Arrow keys / WASD", "Steer the snake"),
            ("P / SPACE", "Pause / resume"),
            ("Q / ESC", "Quit"),
        ]
        y = 56
        for key, desc in lines:
            self.screen.blit(self.font_tiny.render(key, True, YELLOW), (40, y))
            self.screen.blit(self.font_tiny.render(desc, True, WHITE), (260, y))
            y += 22
        y += 8
        details = [
            ("bonus", f"Gold coin: +{BONUS_POINTS} points"),
            ("slow", "Slow-Mo: snake slows for 7s"),
            ("double", "Double Score: 2x points for 7s"),
            ("shield", "Shield: absorbs one crash"),
            ("shrink", "Shrink: cuts 3 tail segments"),
        ]
        for kind, desc in details:
            label, color, _ = POWERUPS[kind]
            pygame.draw.circle(self.screen, color, (52, y + 9), 10)
            t = self.font_tiny.render(label, True, BLACK)
            self.screen.blit(t, (52 - t.get_width() // 2, y + 9 - t.get_height() // 2))
            self.screen.blit(self.font_tiny.render(desc, True, WHITE), (80, y))
            y += 30
        y += 6
        notes = [
            f"Level up every {SCORE_PER_LEVEL} points: faster snake + new rocks",
            "Wrap-around mode: walls become portals",
            "Power-ups vanish after 8s - grab them fast!",
        ]
        for n in notes:
            self.screen.blit(self.font_tiny.render(n, True, GRAY), (40, y))
            y += 22
        self.draw_center(self.font_tiny, "Press ENTER or ESC to go back", YELLOW, SCREEN_HEIGHT - 30)

    def draw_playing(self):
        self.screen.fill(BG)
        self.draw_top_bar()
        self.draw_grid_lines()
        for (x, y) in self.obstacles:
            self.draw_cube(x, y, ROCK_TOP, ROCK_LIGHT, ROCK_MID, ROCK_DARK)
        self.draw_food()
        self.draw_powerup()

        shielded = self.shield or self.now() < self.invuln_until
        blink = (self.now() // 120) % 2 == 0
        for i, (x, y) in enumerate(self.snake):
            if i == 0:
                self.draw_cube(x, y, SNAKE_HEAD_TOP, SNAKE_HEAD_LIGHT, SNAKE_HEAD_MID, SNAKE_HEAD_DARK)
                self.draw_eyes(x, y)
            else:
                if self.shield or (self.now() < self.invuln_until and blink):
                    self.draw_cube(x, y, SHIELD_TOP, SHIELD_LIGHT, SHIELD_MID, SHIELD_DARK)
                elif "double" in self.effects:
                    self.draw_cube(x, y, (210, 150, 255), (225, 185, 255), (150, 80, 220), (90, 40, 140))
                else:
                    self.draw_cube(x, y, SNAKE_TOP, SNAKE_LIGHT, SNAKE_MID, SNAKE_DARK)
        if shielded:
            hx, hy = self.snake[0]
            pygame.draw.circle(self.screen, SHIELD_TOP,
                               (hx * CELL_SIZE + CELL_SIZE // 2, hy * CELL_SIZE + TOP_BAR + CELL_SIZE // 2),
                               CELL_SIZE // 2 + 3, 2)
        self.draw_particles()

    def draw_overlay(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))

    def draw_paused(self):
        self.draw_playing()
        self.draw_overlay()
        self.draw_center(self.font_big, "PAUSED", YELLOW, SCREEN_HEIGHT // 2 - 70)
        self.draw_center(self.font_small, "P / ENTER: Resume", WHITE, SCREEN_HEIGHT // 2)
        self.draw_center(self.font_small, "M: Main menu   Q: Quit", GRAY, SCREEN_HEIGHT // 2 + 32)

    def draw_game_over(self):
        self.draw_playing()
        self.draw_overlay()
        self.draw_center(self.font_big, "GAME OVER", RED, SCREEN_HEIGHT // 2 - 120)
        self.draw_center(self.font_med, f"Final Score: {self.score}   Level: {self.level}", WHITE,
                         SCREEN_HEIGHT // 2 - 50)
        if self.new_record and self.score > 0:
            self.draw_center(self.font_med, "NEW HIGH SCORE!", YELLOW, SCREEN_HEIGHT // 2 - 12)
        else:
            self.draw_center(self.font_small, f"Best: {self.high_score}", YELLOW, SCREEN_HEIGHT // 2 - 8)
        self.draw_center(self.font_small, "ENTER: Play again   R: Menu   Q: Quit", GRAY,
                         SCREEN_HEIGHT // 2 + 40)

    def draw(self):
        if self.state == "menu":
            self.draw_menu()
        elif self.state == "controls":
            self.draw_controls()
        elif self.state == "playing":
            self.draw_playing()
        elif self.state == "paused":
            self.draw_paused()
        elif self.state == "game_over":
            self.draw_game_over()
        pygame.display.flip()

    # ------------------------------------------------------------------
    def run(self):
        while True:
            self.handle_input()
            self.update()
            self.draw()
            self.clock.tick(60)


def main():
    try:
        SnakeGame().run()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        input("\nThe game hit an error (shown above). Press Enter to close...")


if __name__ == "__main__":
    main()