from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Callable
from pathlib import Path
from subprocess import call
from textwrap import indent
from contextlib import redirect_stdout
import os
import sys
import shlex
import shutil
import io

__all__ = [
    "shlex",
    "os",
    "log",
    "get_os",
    "shell",
    "phony",
    "recipe",
    "make",
    "Path",
    "shutil",
]


def get_os() -> Literal["windows", "linux", "macos"]:
    if os.name == "nt":
        return "windows"
    elif os.name == "posix":
        return "linux"
    elif os.name == "mac":
        return "macos"
    else:
        raise ValueError(f"Unknown OS: {os.name}")


def shell(
    command: str | list[str],
    *,
    env: dict | None = None,
    noprint: bool = False,
):
    try:
        if isinstance(command, list) and command:
            cmd = command[0]
            command[0] = shutil.which(cmd) or cmd
        stdout = io.StringIO()
        if not noprint:
            print("\033[36m", end="")
            if isinstance(command, str):
                print(command)
            else:
                print(shlex.join(command))
            print("\033[0m", end="")
        with redirect_stdout(stdout):
            call(command, env=env)
        return stdout.getvalue()
    except Exception as e:
        print(e)
        # print red
        print("\033[31m", end="")
        print(f"Error when executing: %s" % shlex.join(command))
        # print(f'Error: {e}')
        if os.environ.get("trace"):
            import traceback

            traceback.print_exc()
        # print reset
        print("\033[0m")

        sys.exit(1)


@dataclass
class Recipe:
    dependencies: list[str]
    command: Callable[[], None]


@dataclass
class Makefile:
    phony: set[str]
    commands: dict[str, Recipe]


class MakefileRunner:
    makefile: Makefile

    built_recipes: set[str]

    @property
    def phony(self):
        return self.makefile.phony

    def __init__(self, makefile: Makefile):
        self.makefile = makefile
        self.built_recipes = set()

    def run(self, recipe_name: str):
        if recipe_name not in self.makefile.commands:
            # print red
            print("\033[31m", end="")
            print(f'No recipe for "{recipe_name}"')
            # print reset
            print("\033[0m", end="")
            sys.exit(1)

        if recipe_name in self.built_recipes:
            return

        if recipe_name not in self.phony:
            if not Path(recipe_name).exists():
                self.built_recipes.add(recipe_name)
                self._run_simple(recipe_name)
            return

        self.built_recipes.add(recipe_name)
        self._run_simple(recipe_name)

    def _run_simple(self, recipe_name: str):
        recipe = self.makefile.commands[recipe_name]
        for each in recipe.dependencies:
            self.run(each)
        recipe.command()


PHONY: set[str] = set()
RECIPES: dict[str, Recipe] = {}


def phony(names: list[str]):
    PHONY.update(names)


def recipe(*dependencies: str, name: str | None = None):
    def decorator(func: Callable[[], None]):
        RECIPES[name or func.__name__.replace("_", "-")] = Recipe(
            list(dependencies), func
        )
        return func

    return decorator


def make(*recipes):
    if not recipes:
        recipes = sys.argv[1:]
        if not recipes:
            recipes = ["all"]

    if "help" in map(str.lower, recipes):
        print("Available recipes:")
        for name in RECIPES:
            if name in PHONY:
                doc = str(
                    getattr(RECIPES[name].command, "__doc__", "undocumented command")
                    or "undocumented command"
                )
                doc = indent(doc, " " * 14)
                print("\033[36m%-15s\033[0m \n%s" % (name, doc))
        return

    makefile = Makefile(PHONY, RECIPES)
    runner = MakefileRunner(makefile)
    for recipe in recipes:
        runner.run(recipe)


def log(
    msg: str, level: Literal["ok", "info", "warn", "error", "debug", "normal"] = "info"
):
    if level == "ok":
        # green
        print("\033[32m", end="")
        print(msg)
    elif level == "info":
        # blue
        print("\033[34m", end="")
        print(msg)
    elif level == "warn":
        # yellow
        print("\033[33m", end="")
        print(msg)
    elif level == "error":
        # red
        print("\033[31m", end="")
        print(msg)
    elif level == "debug":
        # cyan
        print("\033[36m", end="")
        print(msg)
    else:
        print(msg)
    # reset
    print("\033[0m", end="")
