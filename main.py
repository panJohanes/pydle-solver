import argparse
import json
from html.parser import HTMLParser
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
MAX_CODE_LENGTH = 250


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


def make_solution(tiles: list[tuple[str, str]]) -> str:
    palette = list(dict.fromkeys(color for _, color in tiles))
    palette_indices = {color: str(index) for index, color in enumerate(palette)}
    encoded_colors = "".join(palette_indices[color] for _, color in tiles)
    characters = "".join(text for text, _ in tiles)

    code = (
        f'c="{" ".join(palette)}".split();s="{encoded_colors}";'
        f"t={json.dumps(characters, ensure_ascii=True)};"
        f'[pydle(i%5,i//5,t[i],c[int(s[i])]) for i in range(25)]'
    )
    if len(code) >= MAX_CODE_LENGTH:
        raise ValueError(
            f"Generated solution is {len(code)} characters; "
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

        print(f"Solution ({len(code)} characters):")
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
