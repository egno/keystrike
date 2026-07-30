"""CompositeLayoutRepository: bundled layouts + user TOML layouts from
`<config>/keystrike/layouts/*.toml`. Bundled names take priority on collision."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from keystrike.domain.models import Layout

from .bundled_layouts.colemak import LAYOUT as _COLEMAK
from .bundled_layouts.colemak_dh import LAYOUT as _COLEMAK_DH
from .bundled_layouts.dvorak import LAYOUT as _DVORAK
from .bundled_layouts.qwerty import LAYOUT as _QWERTY
from .layout_toml import load_layout_toml
from .paths import Paths

BUNDLED_LAYOUTS: Mapping[str, Layout] = MappingProxyType(
    {layout.name: layout for layout in (_QWERTY, _DVORAK, _COLEMAK, _COLEMAK_DH)},
)


class CompositeLayoutRepository:
    def __init__(self, paths: Paths, bundled: Mapping[str, Layout] | None = None) -> None:
        self._paths = paths
        self._bundled = bundled if bundled is not None else BUNDLED_LAYOUTS

    def list_available(self) -> list[str]:
        names = set(self._bundled)
        if self._paths.layouts_dir.exists():
            names.update(f.stem for f in self._paths.layouts_dir.glob("*.toml"))
        return sorted(names)

    def get(self, name: str) -> Layout:
        bundled = self._bundled.get(name)
        if bundled is not None:
            return bundled
        file = self._paths.layouts_dir / f"{name}.toml"
        if not file.exists():
            raise KeyError(f"unknown layout: {name!r}")
        return load_layout_toml(file)
