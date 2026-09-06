# snake.py — single-button Snake for the ESP32-C3 72x40 onboard OLED
# Designed to be launched by robot.py:
#
#     import snake
#     snake.run(_oled, _btn, OLED_X0, OLED_Y0, _led)
#
# Controls:
#   TAP BOOT = turn clockwise 90 degrees
#   RESET    = exit game / reboot normally
#   Game over: TAP = retry, HOLD ~2s = clear the saved high score
#
# High score persists in snake_hi.txt on flash.

import time
import random

VISIBLE_W = 72
VISIBLE_H = 40
GRID = 4

DIR_UP = (0, -1)
DIR_RIGHT = (1, 0)
DIR_DOWN = (0, 1)
DIR_LEFT = (-1, 0)
DIR_SEQUENCE = (DIR_UP, DIR_RIGHT, DIR_DOWN, DIR_LEFT)

# Top 8 pixels are reserved for the score.
PLAY_Y = 8
COLS = VISIBLE_W // GRID           # 18
ROWS = (VISIBLE_H - PLAY_Y) // GRID  # 8

START_SPEED_MS = 180
MIN_SPEED_MS = 70
SPEED_STEP_MS = 5

HI_FILE = "snake_hi.txt"
HOLD_CLEAR_MS = 2000       # game-over hold to clear the high score


def _load_hi():
    try:
        with open(HI_FILE) as f:
            return int(f.read())
    except (OSError, ValueError):
        return 0


def _save_hi(v):
    try:
        with open(HI_FILE, "w") as f:
            f.write(str(v))
    except OSError:
        pass


def _spawn_food(snake):
    """Pick an empty cell inside the play area."""
    free = []
    for y in range(ROWS):
        for x in range(COLS):
            if [x, y] not in snake:
                free.append([x, y])

    if not free:
        return None

    return free[random.randrange(len(free))]


def _wait_for_tap(button):
    """Wait for one clean press and release."""
    while button.value() == 1:
        time.sleep_ms(20)

    while button.value() == 0:
        time.sleep_ms(20)

    # tiny debounce delay
    time.sleep_ms(80)


def _show_game_over(oled, button, x0, y0, score, hi):
    """Show the result and wait. Returns the (possibly cleared) high score.

    Holding the button for two seconds wipes the saved score. Same gesture
    as invaders.py, so a student who learns it in one game knows it in the
    other.
    """
    beat = score > hi
    if beat:
        hi = score
        _save_hi(hi)

    oled.fill(0)
    oled.text("NEW BEST!" if beat else "GAME OVER", x0, y0)
    oled.text("SCORE " + str(score), x0, y0 + 8)
    oled.text("BEST  " + str(hi), x0, y0 + 16)
    oled.text("TAP RETRY", x0, y0 + 24)
    oled.show()

    time.sleep_ms(400)

    # Only a SHORT tap restarts, matching invaders.py and defender.py. If any
    # release restarted, the two-second hold that clears the score would
    # restart on release too and the confirmation would vanish unread.
    cleared = False
    while True:
        while button.value() == 1:
            time.sleep_ms(20)

        held_from = time.ticks_ms()
        while button.value() == 0:
            if (not cleared) and time.ticks_diff(
                    time.ticks_ms(), held_from) > HOLD_CLEAR_MS:
                hi = 0
                _save_hi(0)
                cleared = True
                oled.fill(0)
                oled.text("HI SCORE", x0, y0 + 8)
                oled.text("CLEARED", x0, y0 + 20)
                oled.show()
            time.sleep_ms(20)

        held = time.ticks_diff(time.ticks_ms(), held_from)
        time.sleep_ms(80)          # debounce
        if 0 < held < 600:
            return hi
        # A long press was the clear gesture, not a restart. Redraw and wait
        # for the tap that actually restarts.
        oled.fill(0)
        oled.text("NEW BEST!" if beat else "GAME OVER", x0, y0)
        oled.text("SCORE " + str(score), x0, y0 + 8)
        oled.text("BEST  " + str(hi), x0, y0 + 16)
        oled.text("TAP RETRY", x0, y0 + 24)
        oled.show()


def _draw(oled, x0, y0, snake, food, score, hi=0):
    oled.fill(0)

    # Score row + divider. The best score sits right-aligned so there is
    # always something to beat on screen.
    oled.text(str(score), x0, y0)
    if hi:
        s = "H" + str(hi)
        oled.text(s, x0 + VISIBLE_W - 8 * len(s), y0)
    oled.hline(x0, y0 + 7, VISIBLE_W, 1)

    # Food
    if food is not None:
        fx = x0 + food[0] * GRID
        fy = y0 + PLAY_Y + food[1] * GRID
        oled.fill_rect(fx, fy, GRID - 1, GRID - 1, 1)

    # Snake
    for i, segment in enumerate(snake):
        sx = x0 + segment[0] * GRID
        sy = y0 + PLAY_Y + segment[1] * GRID

        # Head is solid 4x4; body is 3x3 so direction is easier to see.
        if i == 0:
            oled.fill_rect(sx, sy, GRID, GRID, 1)
        else:
            oled.fill_rect(sx, sy, GRID - 1, GRID - 1, 1)

    oled.show()


def run(oled, button, x0=28, y0=24, led=None):
    """Run Snake using the robot's existing OLED and BOOT button.

    The caller should stop robot Timer 0 before entering this function.
    This function deliberately never returns during normal play.
    Press the board RESET button to leave the game.
    """

    hi = _load_hi()

    while True:
        # Start roughly in the middle of the 18x8 play field, moving right.
        snake = [[8, 4], [7, 4], [6, 4]]
        dir_idx = 1
        food = _spawn_food(snake)
        score = 0
        speed_ms = START_SPEED_MS
        button_was_down = False

        _draw(oled, x0, y0, snake, food, score, hi)

        while True:
            # Poll repeatedly during the movement delay so short taps
            # register. A boolean rather than a counter, deliberately: two
            # taps inside one step would otherwise turn 180 degrees straight
            # into the snake's own neck, which reads as the game cheating.
            turned_this_step = False
            slices = 12
            slice_ms = max(1, speed_ms // slices)

            for _ in range(slices):
                down = (button.value() == 0)

                if down and not button_was_down:
                    turned_this_step = True

                button_was_down = down
                time.sleep_ms(slice_ms)

            if turned_this_step:
                dir_idx = (dir_idx + 1) % 4

            dx, dy = DIR_SEQUENCE[dir_idx]
            new_head = [
                snake[0][0] + dx,
                snake[0][1] + dy,
            ]

            # Wall collision
            if (
                new_head[0] < 0
                or new_head[0] >= COLS
                or new_head[1] < 0
                or new_head[1] >= ROWS
            ):
                break

            eating = (food is not None and new_head == food)

            # Moving into the current tail cell is legal when the tail is
            # about to move away; all other body collisions end the round.
            body_to_check = snake if eating else snake[:-1]
            if new_head in body_to_check:
                break

            snake.insert(0, new_head)

            if eating:
                score += 1
                food = _spawn_food(snake)

                # Full board = win; show it through the normal game-over screen.
                if food is None:
                    _draw(oled, x0, y0, snake, food, score, hi)
                    break

                speed_ms = max(
                    MIN_SPEED_MS,
                    START_SPEED_MS - score * SPEED_STEP_MS
                )

                # Tiny LED flash on food if an LED object was supplied.
                if led is not None:
                    try:
                        led.value(0)  # onboard LED is inverted on this board
                        time.sleep_ms(35)
                        led.value(1)
                    except Exception:
                        pass
            else:
                snake.pop()

            _draw(oled, x0, y0, snake, food, score, hi)

        hi = _show_game_over(oled, button, x0, y0, score, hi)
