from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Callable
from pathlib import Path
import subprocess
from textwrap import indent
from contextlib import contextmanager
import os
import sys
import shlex
import shutil
import base64
import hashlib
import time

__all__ = [
    "shlex",
    "os",
    "log",
    "get_os",
    "get_dlext",
    "shell",
    "phony",
    "recipe",
    "make",
    "Path",
    "shutil",
    "proft",
    "auto_decode_bytes",
    "text_to_b64",
    "b64_to_text",
]

_os_map: dict[str, Literal["windows", "linux", "macos"]] = {
    "win32": "windows",
    "cygwin": "windows",
    "msys2": "windows",
    "darwin": "macos",
    "linux": "linux",
    "linux2": "linux",
}


if os.environ.get("PMAKEFILE_PROF"):

    @contextmanager
    def proft(title: str):  # type: ignore
        t0 = time.time()
        try:
            yield
        finally:
            print(f"[{title}]: {time.time() - t0}s")

else:

    class proft:
        def __init__(self, title):
            pass

        def __enter__(self):
            pass

        def __exit__(self, a, b, c):
            pass


def get_os() -> Literal["windows", "linux", "macos"]:
    # https://stackoverflow.com/a/13874620/8355168
    platform_id = sys.platform.lower()

    if platform_id in _os_map:
        return _os_map[platform_id]
    else:
        raise SystemError(f"Unknown OS: {platform_id}")


def get_dlext(os: Literal["windows", "linux", "macos"] | None = None):
    if os is None:
        os = get_os()
    if os == "windows":
        return ".dll"
    if os == "linux":
        return ".so"
    if os == "macos":
        return ".dylib"
    raise SystemError(f"Unknown OS: {os}")


def _quote_arg(arg: str) -> str:
    if hasattr(shlex, "quote"):
        return shlex.quote(arg)
    if not arg:
        return "''"
    if arg.isalnum():
        return arg
    if "'" in arg:
        arg = arg.replace("'", r"'\''")
    return f"'{arg}'"


def _join_commands(cmds: str | list[str]):
    if isinstance(cmds, str):
        return cmds
    if hasattr(shlex, "join"):
        return shlex.join(cmds)
    cmds = [_quote_arg(cmd) for cmd in cmds]
    return " ".join(cmds)


CommonEncodings = ["utf-8", "gbk", "gb2312", "gb18030", "big5"]


class AutoDecodeError(UnicodeError):
    pass


def auto_decode_bytes(b: bytes) -> str:
    for encoding in CommonEncodings:
        try:
            return b.decode(encoding)
        except UnicodeDecodeError:
            continue
    else:
        raise AutoDecodeError("Fail to guess encoding")


def shell(
    command: str | list[str],
    *,
    env: dict | None = None,
    noprint: bool = False,
    assure_output: bool = False,
):
    """
    Run a shell command, raise exception if return code is not 0.
    If the command succeeds, return the output of the command.

    If `noprint` is True:
        The command will not be printed.

    If `assure_output` is True:
        The command output will be automatically decoded, and fail if the output is not encoded by `CommonEncodings`.

    If `env` is not None:
        The command will be executed with the given environment variables.

    If `command` is a string:
        The command will be executed with `shell=True`.
    """
    try:
        if isinstance(command, list) and command:
            cmd = command[0]
            command[0] = shutil.which(cmd) or cmd
        if not noprint:
            print("\033[36m", end="")
            if isinstance(command, str):
                print(command)
            else:
                print(_join_commands(command))
            print("\033[0m", end="")
        if isinstance(command, str):
            out = subprocess.run(
                command,
                env=env,
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        else:
            out = subprocess.run(
                command,
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        out.check_returncode()
        res = out.stdout
        try:
            return auto_decode_bytes(res)
        except AutoDecodeError:
            if assure_output:
                raise
            return None

    except subprocess.CalledProcessError as e:
        # print red
        print("\033[31m", end="")
        print(f"Error when executing: %s" % _join_commands(command))
        stdout = e.stdout
        if isinstance(stdout, bytes):
            # common encodings
            for encoding in ["utf-8", "gbk", "gb2312", "gb18030", "big5"]:
                try:
                    print(stdout.decode(encoding))
                    break
                except UnicodeDecodeError:
                    continue
            else:
                print(stdout)
        else:
            print(stdout)

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
    rebuild: Literal["auto", "no", "always", "autoWithDir"] = "auto"


@dataclass
class Makefile:
    phony: set[str]
    commands: dict[str, Recipe]


_deps: list[str] | None = None


_cache_text_to_b64: dict[str, str] = {}


def text_to_b64(s: str, cache: bool = False):
    if cache:
        v = _cache_text_to_b64.get(s)
        if v is None:
            _cache_text_to_b64[s] = v = text_to_b64(s, False)
        return v
    return base64.b64encode(s.encode("utf-8")).decode("utf-8")


def b64_to_text(s: str):
    return base64.b64decode(s.encode("utf-8")).decode("utf-8")


def get_deps():
    if _deps is None:
        raise RuntimeError("can only use 'get_deps()' inside recipes")
    return list(_deps)


_encodes: dict[str, bytes] = {}


def _get_encodes(k: str):
    v = _encodes.get(k)
    if v is None:
        _encodes[k] = v = k.encode("utf-8")
    return v


class MakefileRunner:
    makefile: Makefile
    built_recipes: set[str]
    cwd: Path
    cache_dir: Path

    @property
    def phony(self):
        return self.makefile.phony

    def __init__(self, makefile: Makefile):
        self.makefile = makefile
        self.built_recipes = set()
        self.cwd = Path.cwd()
        self.cache_dir = self._find_cache_dir(self.cwd)

    def _find_cache_dir(self, cwd: Path):
        specified = os.environ.get("PMAKEFILE_CACHE_DIR")
        if specified:
            return Path(specified).absolute()

        cache_dir = cwd.joinpath(".pmake_caches")
        if cache_dir.exists():
            if cache_dir.is_file():
                raise FileExistsError(".pmake_caches is not a directory")
            return cache_dir
        cache_dir.mkdir(exist_ok=True, parents=True)
        return cache_dir

    def _get_cache_hash(self, recipe_self: str) -> bytes:
        recipe_cache_dir = self.cache_dir.joinpath("recipes")
        recipe_cache_dir.mkdir(exist_ok=True, parents=True)
        cache_file = recipe_cache_dir.joinpath(text_to_b64(recipe_self, cache=True))
        if cache_file.exists():
            if cache_file.is_dir():
                raise FileExistsError(
                    f"cache for {recipe_self} is a directory, try fixing it by removing '.pmake_caches'"
                )
            return base64.b64decode(cache_file.read_text(encoding="utf-8"))
        return b""

    def _save_cache_hash(self, recipe_self: str, h: bytes):
        recipe_cache_dir = self.cache_dir.joinpath("recipes")
        recipe_cache_dir.mkdir(exist_ok=True, parents=True)
        cache_file = recipe_cache_dir.joinpath(text_to_b64(recipe_self, cache=True))
        cache_file.write_text(base64.b64encode(h).decode())

    def _compute_hash(self, prereqs: list[str], recipe_self: str, is_phony: bool):
        prereqs = sorted(prereqs)
        if not is_phony:
            hgen = hashlib.md5(b"fs@")
            p = Path(recipe_self)
            if p.exists():
                hgen.update(b"exist@")
                hgen.update(_get_encodes(recipe_self))
                if p.is_file():
                    hgen.update(b"~file=")
                    hgen.update(p.read_bytes())
            else:
                hgen.update(b"unknown@")
                hgen.update(_get_encodes(recipe_self))
        else:
            hgen = hashlib.md5(b"phony@")
            hgen.update(_get_encodes(recipe_self))

        for each in prereqs:
            hgen.update(b"+")
            hgen.update(_get_encodes(each))
            hgen.update(self._get_cache_hash(each))

        return hgen.digest()

    def run(self, recipe_name: str):
        global _deps

        if recipe_name in self.built_recipes:
            return

        with proft(f"[PMakefile] run {recipe_name}"):
            recipe = self.makefile.commands.get(recipe_name)
            if recipe:
                for each in recipe.dependencies:
                    self.run(each)

            is_phony = recipe_name in self.phony
            if is_phony and recipe_name not in self.makefile.commands:
                if self.cwd.joinpath(recipe_name).exists():
                    return
                # print red
                print("\033[31m", end="")
                print(f'No phony recipe for "{recipe_name}"')
                # print reset
                print("\033[0m", end="")
                sys.exit(1)

            if recipe:

                def compute_hash():
                    return self._compute_hash(
                        recipe.dependencies, recipe_name, is_phony
                    )

                new_hash = compute_hash()
                _deps = recipe.dependencies
            else:

                def compute_hash():
                    return self._compute_hash([], recipe_name, is_phony)

                new_hash = compute_hash()
                _deps = []

            old_hash = self._get_cache_hash(recipe_name)

            if recipe:
                if recipe.rebuild == "always":
                    pass
                elif (
                    recipe.rebuild in ("auto", "autoWithDir")
                    and new_hash == old_hash
                    and (is_phony or self.cwd.joinpath(recipe_name).exists())
                ):
                    return
                elif (
                    recipe.rebuild == "no"
                    and not is_phony
                    and self.cwd.joinpath(recipe_name).exists()
                ):
                    self._save_cache_hash(recipe_name, new_hash)
                    return
            else:
                if new_hash == old_hash:
                    return

            self._run_impl(recipe_name)
            new_hash = compute_hash()
            self._save_cache_hash(recipe_name, new_hash)

    def _run_impl(self, recipe_name: str):
        try:
            if recipe_name not in self.phony:
                p = Path(recipe_name)
                recipe = self.makefile.commands.get(recipe_name)
                if p.exists() and recipe:
                    if p.is_dir():
                        if recipe.rebuild in ("always", "autoWithDir"):
                            shutil.rmtree(p, ignore_errors=True)
                            try:
                                p.rmdir()
                            except:
                                pass
                        elif recipe.rebuild == "auto":
                            # will run the recipe, but directories are reused.
                            pass
                        else:
                            # else is in possible
                            assert False, f"unknown rebuild mode: {recipe.rebuild}"
                    else:
                        p.unlink(missing_ok=True)
            self._run_simple(recipe_name)
        finally:
            self.built_recipes.add(recipe_name)

    def _run_simple(self, recipe_name: str):
        recipe = self.makefile.commands.get(recipe_name)
        if recipe:
            recipe.command()


PHONY: set[str] = set()
RECIPES: dict[str, Recipe] = {}


def phony(names: list[str]):
    PHONY.update(names)


def recipe(
    *dependencies: str,
    name: str | None = None,
    rebuild: Literal["always", "no", "auto", "autoWithDir"] = "auto",
):
    """
    Usage:
    ```python
        @recipe('dep1', 'dep2')
        def my_recipe():
            print('dep1 or dep2 has been done!')

        @recipe('dep1', 'dep2', name='myfolder', rebuild='autoWithDir')
        def recreate_myfolder():
            print('myfolder will be removed and recreated if dep1 or dep2 changes')
    ```
    ---------------------------
    For the 'rebuild' keyword:
    - 'no': never rebuild if the target exists.
    - 'always': always rebuild.
    - 'auto': only rebuild when dependencies are changed (force removing out-of-date files but not folders)
    - 'autoWithDir': rebuild when dependencies are changed (force removing out-of-date files and folders)

    The difference between 'auto' and 'autoWithDir' is that
    'auto' will not remove targets if the target is a directory.
    """

    def decorator(func: Callable[[], None]):
        RECIPES[name or func.__name__.replace("_", "-")] = Recipe(
            list(dependencies), func, rebuild=rebuild
        )
        return func

    return decorator


_hasRun = False


def make(*recipes):
    global _hasRun
    if _hasRun:
        return
    try:
        if not recipes:
            recipes = sys.argv[1:]
            if not recipes:
                recipes = ["all"]

        if "help" in map(str.lower, recipes):
            print("Available recipes:")
            for name in RECIPES:
                if name in PHONY:
                    doc = str(
                        getattr(
                            RECIPES[name].command, "__doc__", "undocumented command"
                        )
                        or "undocumented command"
                    )
                    doc = indent(doc, " " * 14)
                    print("\033[36m%-15s\033[0m \n%s" % (name, doc))
            return

        makefile = Makefile(PHONY, RECIPES)
        runner = MakefileRunner(makefile)
        for recipe in recipes:
            runner.run(recipe)
    finally:
        _hasRun = True


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


def import_from_source_file(path: Path, module_name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, path.absolute())
    if not spec:
        raise FileNotFoundError(f"module is not found at given path: {path}")
    module = importlib.util.module_from_spec(spec)
    if not spec.loader:
        raise FileNotFoundError(f"ModuleSpec.loader is missing for module: {path}")
    spec.loader.exec_module(module)
    return module


def main():
    cwd = Path.cwd()
    sys.path.append(cwd.absolute().as_posix())
    alternatives = ["make.py", "make"]
    for alt in alternatives:
        if cwd.joinpath(alt).exists():
            if not alt.endswith(".py"):
                import ast

                try:
                    ast.parse(cwd.joinpath(alt).read_text(encoding="utf-8"))
                except SyntaxError:
                    # print warning
                    print("\033[33m", end="")
                    print(f"Warning: {alt} is not a valid python file")
                    # print reset
                    print("\033[0m", end="")
                    continue
            with proft("[PMakefile] run main procedure"):
                import_from_source_file(cwd.joinpath(alt), "__make_main__")
                if not _hasRun:
                    make()

            return

    # print warning
    print("\033[33m", end="")
    print(f"Warning: no make.py found")
    # print reset
    print("\033[0m", end="")
