from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

_APP_NAME = "keystrike"


@dataclass(frozen=True, slots=True)
class Paths:
    config_dir: Path
    data_dir: Path
    log_dir: Path

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.toml"

    @property
    def layouts_dir(self) -> Path:
        return self.config_dir / "layouts"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def sessions_index(self) -> Path:
        return self.sessions_dir / "index.jsonl"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def sync_config_file(self) -> Path:
        return self.config_dir / "sync.toml"

    @property
    def sync_clone_dir(self) -> Path:
        return self.config_dir / "sync" / "repo"


def default_paths() -> Paths:
    dirs = PlatformDirs(appname=_APP_NAME, appauthor=False)
    return Paths(
        config_dir=Path(dirs.user_config_dir),
        data_dir=Path(dirs.user_data_dir),
        log_dir=Path(dirs.user_log_dir),
    )


def ensure_dirs(paths: Paths) -> None:
    for p in (
        paths.config_dir,
        paths.data_dir,
        paths.log_dir,
        paths.layouts_dir,
        paths.sessions_dir,
        paths.cache_dir,
    ):
        p.mkdir(parents=True, exist_ok=True)
