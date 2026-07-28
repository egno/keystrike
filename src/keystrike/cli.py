import typer

from keystrike import __version__
from keystrike.app import build

app = typer.Typer(
    add_completion=False,
    help="Adaptive drills for your weakest keys",
    no_args_is_help=False,
    invoke_without_command=True,
)


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


if __name__ == "__main__":
    app()
