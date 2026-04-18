"""Hermes Trip Agent CLI — entry point `hermes-trip`."""

from __future__ import annotations

import typer

app = typer.Typer(name="hermes-trip", help="Chapman family travel planning assistant.")


@app.command()
def version() -> None:
    """Print version."""
    from hermes_trip import __version__

    typer.echo(f"hermes-trip {__version__}")


@app.command("db-init")
def db_init() -> None:
    """Create ~/.hermes_trip directory and run Alembic migrations."""
    import subprocess

    from hermes_trip import config

    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.VAULT_PATH.mkdir(parents=True, exist_ok=True)
    config.EXPORT_PATH.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    typer.echo(result.stdout)
    if result.returncode != 0:
        typer.echo(result.stderr, err=True)
        raise typer.Exit(1)
    typer.echo("Database initialised.")


if __name__ == "__main__":
    app()
