"""Allow running as `python -m chatgpt_pwm` and as a PyInstaller entry point.

Use an absolute import so the frozen binary works: when PyInstaller runs this
file as the top-level script there is no parent package, so a relative
`from .cli import main` raises ImportError. The relative form is kept as a
fallback for unusual execution contexts.
"""
try:
    from chatgpt_pwm.cli import main
except ImportError:  # pragma: no cover - fallback when run inside the package
    from .cli import main

if __name__ == "__main__":
    main()
