# pmakefile

## Background

Makefile is a fundamental tool when it comes to building software. As a simple way to organize code compilation,
it's been part of Unix world for over 40 years. However, it's not a perfect tool. Its cross-platform support is not native yet, and learning curves can be steep. This project aims to provide a practical alternative to Makefile subset for most common use cases.

> Software can be reproducible, protable, and maintainable, for regular users and developers, with a simple "P-makefile".

## Usage

See the `example/` directory where we write a single `make` in Python using `pmakefile` and `zig cc` to cross-compile the QuickJS project for Windows, Linux, and macOS (x86_64 and aarch64), which is a huge task and so far not achieved by any other known makefile written for QuickJS. With `pmakefile`, writing `make` promises us excellent portability, static type checking, and simplicity, while depending on only a standard Python distribution.

The `pmakefile` Python module exports some useful functions, see [builtin functions](#useful-helper-functions)

The pmakefile structure can be given as follows:

```python
#!/usr/bin/env python

from pmakefile import *

phony([
    'all', 'clean', ... # phony targets
])

ROOT = Path(__file__).parent.relative_to(os.getcwd())

@recipe('dep1', 'dep2')
def my_recipe():
    """documentation for my_recipe"""

    # some python statements


make()
```

Then you can use it in your favorite shell:

```shell
./make help
```

## Useful Helper Functions


- `get_os() -> 'windows' | 'linux' | 'macos'`
- `log(msg: str, level: 'ok' | 'error' | 'info' | 'debug' | 'warn' | 'normal' = 'normal')`
- `shell(command: str | list[str], *, env: dict | None = None, noprint: bool = False)`

## License

MIT License is used for this project. See [LICENSE](LICENSE) for more details.