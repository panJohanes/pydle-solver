import argparse
import io
import tokenize
from html.parser import HTMLParser
from itertools import groupby, permutations
from pathlib import Path

BOARD_SIZE = 5
COLORS = {
    "blue",
    "red",
    "black",
    "yellow",
    "green",
    "orange",
    "white",
    "purple",
    "brown",
}
MAX_CODE_LENGTH = 100


class BoardParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.board_depth: int | None = None
        self.tile_depth: int | None = None
        self.tile_color = ""
        self.tile_text: list[str] = []
        self.boards: list[list[tuple[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()

        if tag == "div" and "columns-2" in classes:
            self.board_depth = self.depth
            self.boards.append([])
        elif (
            self.board_depth is not None
            and tag == "div"
            and "w-8" in classes
            and attributes.get("title") in COLORS
        ):
            self.tile_depth = self.depth
            self.tile_color = attributes["title"] or ""
            self.tile_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.tile_depth == self.depth:
            text = "".join(self.tile_text).strip() or " "
            self.boards[-1].append((text, self.tile_color))
            self.tile_depth = None

        if tag == "div" and self.board_depth == self.depth:
            self.board_depth = None

        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.tile_depth is not None:
            self.tile_text.append(data)


def board_tiles(html: str) -> list[tuple[str, str]]:
    parser = BoardParser()
    parser.feed(html)
    return parser.boards[-1] if parser.boards else []


def target_tiles(html: str) -> list[tuple[str, str]]:
    tiles = board_tiles(html)
    board_area = BOARD_SIZE * BOARD_SIZE
    if len(tiles) < board_area * 2 or len(tiles) % board_area:
        raise ValueError(
            f"Expected both {BOARD_SIZE}x{BOARD_SIZE} Pydle boards to be loaded."
        )

    target = tiles[-board_area:]
    if any(len(text) != 1 for text, _ in target):
        raise ValueError("Every target tile must contain exactly one character.")
    return target


def compact_literal(value: str) -> str:
    options = {repr(value)}
    runs = [
        (character, len(list(group)))
        for character, group in groupby(value)
    ]
    if runs:
        options.add(
            "+".join(
                f"{character!r}*{count}" if count > 1 else repr(character)
                for character, count in runs
            )
        )
    for size in range(1, len(value)):
        repeats, remainder = divmod(len(value), size)
        prefix = value[:size]
        if repeats > 1 and prefix * repeats + prefix[:remainder] == value:
            expression = f"{prefix!r}*{repeats}"
            if remainder:
                expression += f"+{prefix[:remainder]!r}"
            options.add(expression)
    return min(options, key=len)


def code_character_count(code: str) -> int:
    ignored = {
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.INDENT,
        tokenize.NEWLINE,
        tokenize.NL,
    }
    return sum(
        len(token.string)
        for token in tokenize.generate_tokens(io.StringIO(code).readline)
        if token.type not in ignored
    )


def pack_utf16(code: str) -> str | None:
    try:
        source = code.encode("ascii")
    except UnicodeEncodeError:
        return None
    if len(source) % 2:
        source += b"\n"
    packed = "".join(
        chr(source[index] | source[index + 1] << 8)
        for index in range(0, len(source), 2)
    )
    if bytes(packed, "u16")[2:] != source:
        return None
    wrapper = f"exec(bytes('{packed}','u16')[2:])"
    try:
        compile(wrapper, "<pydle-packed-solution>", "exec")
    except SyntaxError:
        return None
    return wrapper


def make_solution(tiles: list[tuple[str, str]]) -> str:
    characters = "".join(text for text, _ in tiles)
    if set(characters) == {" "}:
        character_expression = "''"
        character_setup = ""
    elif len(set(characters)) == 1:
        character_expression = repr(characters[0])
        character_setup = ""
    else:
        character_expression = "t[i]"
        character_setup = f"t={compact_literal(characters)}"

    palette = sorted(set(color for _, color in tiles))
    if len(palette) <= 7:
        palette_orders = set(permutations(palette))
    else:
        bits = max(1, (len(palette) - 1).bit_length())
        weights = {
            color: sum(
                1 << (bits * i)
                for i, (_, tile_color) in enumerate(tiles)
                if tile_color == color
            )
            for color in palette
        }
        palette_orders = {
            tuple(palette),
            tuple(dict.fromkeys(color for _, color in tiles)),
            tuple(reversed(palette)),
            tuple(sorted(palette, key=weights.get, reverse=True)),
        }
    candidates: list[str] = []

    def add_loop_candidates(
        setup: str,
        color_expression: str,
        character_expression_override: str | None = None,
    ) -> None:
        selected_character_expression = (
            character_expression_override or character_expression
        )
        call = (
            f"pydle(i%5,i//5,{selected_character_expression},{color_expression})"
        )
        bodies = [
            f"for i in range(25):{call}",
            f"i=25\nwhile i:i-=1;{call}",
            f"i=0\nwhile i<25:{call};i+=1",
        ]
        for body in bodies:
            candidates.append(f"{setup}\n{body}" if setup else body)

    character_options = [(character_setup, character_expression)]
    if len(set(characters)) == 2:
        for character_order in permutations(sorted(set(characters))):
            character_bits = sum(
                (character == character_order[1]) << index
                for index, character in enumerate(characters)
            )
            encoded = min(
                (str(character_bits), hex(character_bits), oct(character_bits)),
                key=len,
            )
            character_options.append(
                (
                    "",
                    f"{''.join(character_order)!r}[{encoded}>>i&1]",
                )
            )

    if len(palette) == 2:
        for color_order in permutations(palette):
            interleaved_colors = "".join(
                color[index]
                for index in range(max(map(len, color_order)))
                for color in color_order
                if index < len(color)
            )
            color_bits = sum(
                (color == color_order[1]) << index
                for index, (_, color) in enumerate(tiles)
            )
            encoded = min(
                (str(color_bits), hex(color_bits), oct(color_bits)),
                key=len,
            )
            color_expression = f"{interleaved_colors!r}[{encoded}>>i&1::2]"
            for setup, selected_character_expression in character_options:
                add_loop_candidates(
                    setup,
                    color_expression,
                    character_expression_override=selected_character_expression,
                )

        for boundary in range(1, len(tiles)):
            first_color = tiles[0][1]
            second_color = tiles[boundary][1]
            if first_color == second_color:
                continue
            if not all(color == first_color for _, color in tiles[:boundary]):
                continue
            if not all(color == second_color for _, color in tiles[boundary:]):
                continue

            for color_order, selector in (
                ((first_color, second_color), f"i>{boundary - 1}"),
                ((second_color, first_color), f"i<{boundary}"),
            ):
                interleaved_colors = "".join(
                    color[index]
                    for index in range(max(map(len, color_order)))
                    for color in color_order
                    if index < len(color)
                )
                color_expression = f"{interleaved_colors!r}[{selector}::2]"
                for setup, selected_character_expression in character_options:
                    add_loop_candidates(
                        setup,
                        color_expression,
                        character_expression_override=selected_character_expression,
                    )

    for order in palette_orders:
        palette_indices = {color: index for index, color in enumerate(order)}
        colors = [palette_indices[color] for _, color in tiles]
        palette_codes = (
            f"c={' '.join(order)!r}.split()",
            f"c={','.join(repr(color) for color in order)}",
        )
        if len(order) == 1:
            color_expressions = {repr(order[0])}
            if order[0] == "black":
                color_expressions.add("0")
            for setup, selected_character_expression in character_options:
                for color_expression in color_expressions:
                    add_loop_candidates(
                        setup,
                        color_expression,
                        character_expression_override=selected_character_expression,
                    )
            continue

        encoded_colors = "".join(str(color) for color in colors)
        bits = max(1, (len(order) - 1).bit_length())
        packed_colors = sum(color << (bits * i) for i, color in enumerate(colors))
        packed_literals = {str(packed_colors), hex(packed_colors), oct(packed_colors)}
        for palette_code in palette_codes:
            for setup, selected_character_expression in character_options:
                for encoded in packed_literals:
                    color_setup = f"b={encoded}"
                    color_expression = f"c[b>>i*{bits}&{(1 << bits) - 1}]"
                    prefix = "\n".join(
                        part for part in (palette_code, setup, color_setup) if part
                    )
                    add_loop_candidates(
                        prefix,
                        color_expression,
                        character_expression_override=selected_character_expression,
                    )

                color_setup = f"s={compact_literal(encoded_colors)}"
                color_expression = "c[int(s[i])]"
                prefix = "\n".join(
                    part for part in (palette_code, setup, color_setup) if part
                )
                add_loop_candidates(
                    prefix,
                    color_expression,
                    character_expression_override=selected_character_expression,
                )

        black_options = (False, True) if "black" in order else (False,)
        for use_zero_for_black in black_options:
            items = [
                "0" if use_zero_for_black and color == "black" else repr(color)
                for color in order
            ]
            inline_palettes = {
                f"[{','.join(items)}]",
                f"({','.join(items)})",
                f"{' '.join(order)!r}.split(' ')",
                f"{' '.join(order)!r}.split()",
            }
            for inline_palette in inline_palettes:
                for encoded in packed_literals:
                    color_expression = (
                        f"{inline_palette}[{encoded}>>i*{bits}&{(1 << bits) - 1}]"
                    )
                    for setup, selected_character_expression in character_options:
                        add_loop_candidates(
                            setup,
                            color_expression,
                            character_expression_override=selected_character_expression,
                        )

    ascii_candidates: dict[int, list[str]] = {}
    for candidate in candidates:
        if candidate.isascii():
            ascii_candidates.setdefault(len(candidate), []).append(candidate)
    packed_candidates: list[str] = []
    for source_length in sorted(ascii_candidates):
        for candidate in ascii_candidates[source_length]:
            packed = pack_utf16(candidate)
            if packed is not None:
                packed_candidates.append(packed)
        if packed_candidates:
            break
    candidates.extend(packed_candidates)
    code = min(
        candidates,
        key=lambda candidate: (
            code_character_count(candidate),
            candidate.startswith("exec(bytes("),
            candidate,
        ),
    )
    if code_character_count(code) > MAX_CODE_LENGTH:
        raise ValueError(
            f"Shortest generated solution is "
            f"{code_character_count(code)} characters; "
            f"the limit is {MAX_CODE_LENGTH}."
        )
    return code


def solve_online(url: str, headless: bool) -> None:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as conditions
    from selenium.webdriver.support.ui import WebDriverWait

    options = Options()
    options.add_argument("--window-size=1280,1000")
    if headless:
        options.add_argument("--headless=new")

    driver = webdriver.Edge(options=options)
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 90)
        editor_selector = ".cm-content[contenteditable='true']"
        run_selector = "button[title='Run (F5)']"

        try:
            wait.until(
                lambda browser: (
                    "Pydle #" in browser.find_element(By.TAG_NAME, "body").text
                    and browser.find_elements(
                        By.CSS_SELECTOR, editor_selector
                    )
                    and len(board_tiles(browser.page_source))
                    >= BOARD_SIZE * BOARD_SIZE * 2
                )
            )
            target = target_tiles(driver.page_source)
            code = make_solution(target)

            for dialog in driver.find_elements(By.CSS_SELECTOR, "[role='dialog']"):
                if dialog.is_displayed() and dialog.text.startswith("How to play Pydle"):
                    dialog.find_element(By.CSS_SELECTOR, "button svg").click()
                    wait.until(
                        conditions.invisibility_of_element_located(
                            (By.CSS_SELECTOR, "[role='dialog']")
                        )
                    )
                    break

            code_tab = wait.until(
                conditions.element_to_be_clickable(
                    (
                        By.XPATH,
                        "//button[@role='tab' and normalize-space()='Code']",
                    )
                )
            )
            code_tab.click()
            editor = wait.until(
                conditions.visibility_of_element_located(
                    (By.CSS_SELECTOR, editor_selector)
                )
            )
            editor.click()
            editor.send_keys(Keys.CONTROL, "a")
            editor.send_keys(code)
            entered_code = driver.execute_script(
                "return arguments[0].textContent;", editor
            )
            if entered_code != code:
                raise RuntimeError("Could not enter the solution into Pydle's editor.")

            run_button = wait.until(
                conditions.element_to_be_clickable((By.CSS_SELECTOR, run_selector))
            )
            run_button.click()
            wait.until(
                lambda browser: board_tiles(browser.page_source)[: BOARD_SIZE**2]
                == target
            )
            board_class = driver.find_element(
                By.CSS_SELECTOR, ".columns-2 > div:first-child"
            ).get_attribute("class") or ""
            if "border-green-500" not in board_class:
                raise RuntimeError(
                    "The board output matched visually but Pydle did not mark the "
                    "puzzle solved. Check that --url points to the intended puzzle."
                )
        except TimeoutException as error:
            if "Pydle NOT FOUND" in driver.find_element(
                By.TAG_NAME, "body"
            ).text:
                raise RuntimeError(
                    "Pydle is still showing its loading placeholder. Its live ."
                    "puzzle request did not finish loading."
                ) from error
            raise RuntimeError(
                "Pydle did not load or finish running the solution in time."
            ) from error

        print(f"Solution ({code_character_count(code)} characters):")
        print(code)
        print("Solved the live Pydle board.")
        if not headless:
            try:
                input("Press Enter to close the solved browser window...")
            except EOFError:
                pass
    finally:
        driver.quit()


def main() -> None:
    cli = argparse.ArgumentParser(description="Automatically solve Pydle in Chrome.")
    cli.add_argument("--url", default="https://pydle.net", help="Pydle puzzle URL")
    cli.add_argument(
        "--headless", action="store_true", help="solve without showing the browser"
    )
    cli.add_argument(
        "--generate-only",
        action="store_true",
        help="print a solution for the local HTML snapshot instead of opening Chrome",
    )
    cli.add_argument(
        "--html",
        type=Path,
        default=Path(__file__).with_name("website.html"),
        help="HTML snapshot to use with --generate-only",
    )
    args = cli.parse_args()

    if args.generate_only:
        try:
            html = args.html.read_text(encoding="utf-8")
            solution = make_solution(target_tiles(html))
        except (OSError, ValueError) as error:
            cli.error(str(error))
        print(solution)
    else:
        solve_online(args.url, args.headless)


if __name__ == "__main__":
    main()
