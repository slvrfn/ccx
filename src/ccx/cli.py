"""Click presentation layer. All operations delegate to independently testable services."""

import json
from pathlib import Path
from typing import Any

import click

from ccx import __version__, watch
from ccx.config import Settings
from ccx.errors import CcxError
from ccx.service import Application


def emit(value: Any) -> None:
    click.echo(json.dumps(value, indent=2))


@click.group()
@click.option("--home", type=click.Path(path_type=Path), help="Override CCX_HOME.")
@click.version_option(__version__)
@click.pass_context
def cli(ctx: click.Context, home: Path | None) -> None:
    """Local OpenCode, semantic search, and knowledge graph environments."""
    ctx.obj = Application(Settings.load(home))


@cli.command()
@click.option("--force", is_flag=True, help="Refresh shipped templates, preserving .env and state.")
@click.pass_obj
def init(app: Application, force: bool) -> None:
    """Install local templates and create a private .env file. Does not contact endpoints."""
    app.initialize(force)
    click.echo(f"Initialized {app.settings.home}. Edit .env, then run ccx env check.")


@cli.group()
def env() -> None:
    """Inspect configuration without revealing credentials."""


@env.command("check")
@click.pass_obj
def env_check(app: Application) -> None:
    emit(app.settings.check())


@cli.group()
def platform() -> None:
    """Manage shared Milvus, MinIO, etcd and optional Attu."""


@platform.command("up")
@click.option("--ui", is_flag=True, help="Also start Attu on loopback.")
@click.pass_obj
def platform_up(app: Application, ui: bool) -> None:
    app.initialize()
    app.docker.platform_up(ui)


@platform.command("down")
@click.option("--yes", is_flag=True)
@click.pass_obj
def platform_down(app: Application, yes: bool) -> None:
    if yes or click.confirm("Stop shared services for ALL ccx projects? Volumes will be retained"):
        app.docker.compose("down")


@platform.command("status")
@click.pass_obj
def platform_status(app: Application) -> None:
    app.docker.compose("ps")


@cli.command("open")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--graph/--no-graph", default=None)
@click.option("--watch", "enable_watch", is_flag=True)
@click.option(
    "--interval",
    type=click.FloatRange(min=0.1),
    default=None,
    help="Watcher quiet-period debounce in seconds (default from .env).",
)
@click.option("--no-interactive", is_flag=True)
@click.option("--prepare-only", is_flag=True, help="Configure/start container, but do not index.")
@click.option("--rebuild", is_flag=True, help="Rebuild the project image.")
@click.option(
    "--keep-alive",
    is_flag=True,
    help="Leave the managed project container running after /exit (default: stop it on /exit).",
)
@click.pass_obj
def open_project(
    app: Application,
    path: Path,
    graph: bool | None,
    enable_watch: bool,
    interval: float | None,
    no_interactive: bool,
    prepare_only: bool,
    rebuild: bool,
    keep_alive: bool,
) -> None:
    project = app.open(path, graph=graph, rebuild=rebuild, prepare_only=prepare_only)
    click.echo(f"Project: {project.slug}")
    if enable_watch:
        watch.start(
            app.settings.home,
            app.store.directory(project),
            project,
            interval or app.settings.number("WATCH_DEBOUNCE_SECONDS"),
        )
    if no_interactive:
        return
    app.docker.interactive(project)
    # OpenCode exited (/exit or session end): stop the managed project container.
    # The persistent HOME volume is retained, so reopening reuses the image cache
    # and state instead of rebuilding. --keep-alive opts out.
    if not keep_alive:
        app.docker.remove(project)


@cli.command()
@click.argument("target")
@click.option("--full", is_flag=True, help="Drop/rebuild vectors and force graph extraction.")
@click.option("--yes", is_flag=True)
@click.pass_obj
def reindex(app: Application, target: str, full: bool, yes: bool) -> None:
    if full and not yes:
        click.confirm("Rebuild this project's semantic index and graph?", abort=True)
    emit(app.refresh(app.store.resolve(target), full=full))


@cli.command("build-graph")
@click.argument("target")
@click.option("--full", is_flag=True)
@click.pass_obj
def build_graph(app: Application, target: str, full: bool) -> None:
    emit(app.refresh(app.store.resolve(target), full=full, graph_only=True))


@cli.command()
@click.argument("target")
@click.pass_obj
def status(app: Application, target: str) -> None:
    emit(app.status(app.store.resolve(target)))


@cli.command("graph-status")
@click.argument("target")
@click.pass_obj
def graph_status(app: Application, target: str) -> None:
    project = app.store.resolve(target)
    emit({"enabled": project.graph_enabled, **app.graph.status(project)})


@cli.command("graph-query")
@click.argument("target")
@click.argument("query")
@click.pass_obj
def graph_query(app: Application, target: str, query: str) -> None:
    project = app.store.resolve(target)
    app.require_running(project)
    if not project.graph_enabled:
        raise CcxError("Graphify is disabled for this project.")
    click.echo(app.graph.query(project, query))


@cli.command("search")
@click.argument("target")
@click.argument("query")
@click.pass_obj
def search(app: Application, target: str, query: str) -> None:
    project = app.store.resolve(target)
    app.require_running(project)
    click.echo(app.semantic.search(project, query))


@cli.command("clear-index")
@click.argument("target")
@click.option("--yes", is_flag=True)
@click.pass_obj
def clear_index(app: Application, target: str, yes: bool) -> None:
    project = app.store.resolve(target)
    app.require_running(project)
    if watch.is_running(app.store.directory(project)):
        raise CcxError("Stop the watcher before clearing an index.")
    if yes or click.confirm(f"Delete semantic collection {project.collection}?"):
        click.echo(app.semantic.clear(project))


@cli.command("clear-graph")
@click.argument("target")
@click.option("--yes", is_flag=True)
@click.pass_obj
def clear_graph(app: Application, target: str, yes: bool) -> None:
    project = app.store.resolve(target)
    if watch.is_running(app.store.directory(project)):
        raise CcxError("Stop the watcher before clearing a graph.")
    if yes or click.confirm(f"Delete all generated files in {project.path / project.graph_out}?"):
        # Container lock protects against concurrent OpenCode MCP writers.
        app.require_running(project)
        app.docker.exec(project, ["python", "-m", "ccx.runtime.clear_graph"])
        click.echo("Graph output deleted; semantic index retained.")


@cli.command("watch")
@click.argument("target")
@click.option("--interval", type=click.FloatRange(min=0.1), default=None)
@click.option("--stop", is_flag=True)
@click.pass_obj
def watch_project(app: Application, target: str, interval: float | None, stop: bool) -> None:
    project = app.store.resolve(target)
    state = app.store.directory(project)
    if stop:
        watch.stop(state)
        click.echo("Watcher stopped.")
    else:
        app.require_running(project)
        watch.start(
            app.settings.home,
            state,
            project,
            interval or app.settings.number("WATCH_DEBOUNCE_SECONDS"),
        )
        click.echo(f"Watcher started. Logs: {state / 'watch.log'}")


@cli.command("_watch-run", hidden=True)
@click.argument("target")
@click.option("--interval", type=float, required=True)
@click.option("--token", required=True)
@click.pass_obj
def watch_run(app: Application, target: str, interval: float, token: str) -> None:
    project = app.store.resolve(target)
    watch.run_loop(
        project, app.store.directory(project), interval, token, lambda: app.refresh(project)
    )


@cli.command("export")
@click.argument("target")
@click.argument("destination", type=click.Path(path_type=Path))
@click.pass_obj
def export(app: Application, target: str, destination: Path) -> None:
    project = app.store.resolve(target)
    app.require_running(project)
    app.transfers.export(project, destination.resolve())
    click.echo(f"Exported {destination}")


@cli.command("import")
@click.argument("target")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--yes", is_flag=True)
@click.pass_obj
def import_bundle(app: Application, target: str, source: Path, yes: bool) -> None:
    project = app.store.resolve(target)
    app.require_running(project)
    if watch.is_running(app.store.directory(project)):
        raise CcxError("Stop the watcher before importing.")
    if yes or click.confirm(
        f"Import {source} into {project.slug}? Existing indexes are never replaced"
    ):
        app.transfers.restore(project, source.resolve())
        click.echo("Imported. First refresh will rebuild path-dependent indexing snapshots.")


def main() -> None:
    try:
        cli()
    except CcxError as exc:
        click.ClickException(str(exc)).show()
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
