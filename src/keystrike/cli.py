import subprocess
from collections.abc import Callable
from typing import NoReturn

import typer

from keystrike import __version__
from keystrike.app import build, build_sync

app = typer.Typer(
    add_completion=False,
    help="Adaptive drills for your weakest keys",
    no_args_is_help=False,
    invoke_without_command=True,
)

sync_app = typer.Typer(help="Git-backed backup of settings and sessions (opt-in, CLI-only)")
app.add_typer(sync_app, name="sync")


@app.callback()
def _default(  # pyright: ignore[reportUnusedFunction]
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version"),
) -> None:
    if version:
        typer.echo(f"keystrike {__version__}")
        raise typer.Exit
    if ctx.invoked_subcommand is None:
        build().run()


@app.command()
def run() -> None:
    """Launch the typing tutor TUI."""
    build().run()


def _sync_err(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _run_sync[T](fn: Callable[[], T]) -> T:
    """Wrap a sync operation with consistent error handling."""
    try:
        return fn()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        _sync_err(exc)


@sync_app.command("init")
def sync_init(
    repo_url: str = typer.Argument(..., help="Private git remote URL (HTTPS or SSH)"),
) -> None:
    """One-time setup: clone remote, merge local data, write sync.toml."""
    _run_sync(lambda: build_sync().init(repo_url))
    typer.echo(f"sync initialized ({repo_url})")


@sync_app.command()
def pull() -> None:
    """Pull remote, union-merge sessions/settings locally, rebuild stats cache."""
    imported = _run_sync(lambda: build_sync().pull())
    typer.echo(f"pull complete: {imported} session(s) imported")


@sync_app.command()
def push() -> None:
    """Merge local data into clone and push to remote."""
    pushed = _run_sync(lambda: build_sync().push())
    typer.echo("push complete" if pushed else "push skipped (nothing to commit)")


@sync_app.command()
def status() -> None:
    """Show sync remote and session diff summary."""
    st = _run_sync(lambda: build_sync().status())
    if not st.configured:
        typer.echo("sync not configured — run: keystrike sync init <repo-url>")
        raise typer.Exit(code=1)
    typer.echo(f"remote: {st.remote_url}")
    typer.echo(
        f"sessions: local={st.local_sessions} clone={st.clone_sessions} "
        f"(only local={st.only_local}, only remote={st.only_clone})",
    )
    summary = st.git_status.strip() or "(clean)"
    typer.echo(f"git: {summary}")


if __name__ == "__main__":
    app()
