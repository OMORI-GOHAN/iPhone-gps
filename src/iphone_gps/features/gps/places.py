"""User-owned named locations, persisted locally without device access."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from ...core.coordinates import to_wgs84
from ...core.errors import GpsError
from ...host.paths import user_data_directory


class PlaceError(GpsError):
    pass


def validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise PlaceError("地点名必须是文字")
    name = name.strip()
    if not name or len(name) > 100 or any(not char.isprintable() for char in name):
        raise PlaceError("地点名需为 1–100 个可打印字符，不能包含换行")
    try:
        float(name)
    except ValueError:
        return name
    raise PlaceError("地点名不能是纯数字或数值，请加上文字以便与坐标区分")


@dataclass(frozen=True)
class SavedPlace:
    name: str
    latitude: float
    longitude: float
    coord_system: str

    @property
    def coordinate(self):
        return to_wgs84(self.latitude, self.longitude, source=self.coord_system)


class PlaceStore:
    """SQLite transactions protect updates from concurrent CLI processes.

    Original input and its declared system are stored together. Conversion is
    performed when resolving a name, never saved back over the source values.
    """

    def __init__(self, path: str | Path | None = None):
        if path is None:
            path = user_data_directory() / 'places.sqlite3'
        self.path = Path(path)

    @contextmanager
    def _connect(self, *, write=False):
        connection = None
        try:
            if write:
                self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            uri = self.path.resolve().as_uri() + ('?mode=rwc' if write else '?mode=ro')
            connection = sqlite3.connect(uri, uri=True, timeout=5)
            connection.row_factory = sqlite3.Row
            with connection:
                if write:
                    connection.execute('''CREATE TABLE IF NOT EXISTS places (
                        name TEXT PRIMARY KEY,
                        latitude REAL NOT NULL,
                        longitude REAL NOT NULL,
                        coord_system TEXT NOT NULL
                    )''')
                yield connection
        except (OSError, sqlite3.Error) as exc:
            raise PlaceError(f"无法读写地点文件 {self.path}；请检查文件权限或文件是否损坏") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _place(row):
        try:
            place = SavedPlace(**dict(row))
            if validate_name(place.name) != place.name:
                raise ValueError('invalid stored name')
            place.coordinate  # Validate stored data rather than silently using corrupt values.
            return place
        except (ValueError, TypeError, OverflowError) as exc:
            raise PlaceError("保存的地点数据无效，请检查地点文件") from exc

    def list(self) -> list[SavedPlace]:
        if not self.path.exists():
            return []
        with self._connect() as connection:
            return [self._place(row) for row in connection.execute('SELECT * FROM places ORDER BY name')]

    def get(self, name: str) -> SavedPlace:
        name = validate_name(name)
        if self.path.exists():
            with self._connect() as connection:
                row = connection.execute('SELECT * FROM places WHERE name = ?', (name,)).fetchone()
                if row is not None:
                    return self._place(row)
        raise PlaceError(f"未保存地点“{name}”；运行 gps place list 查看，或用 gps place save 添加")

    def save(self, name: str, latitude: float, longitude: float, *, coord_system='wgs84', replace=False) -> SavedPlace:
        name = validate_name(name)
        try:
            to_wgs84(latitude, longitude, source=coord_system)
        except (TypeError, ValueError, OverflowError) as exc:
            raise PlaceError(f"地点坐标无效：{exc}") from exc
        place = SavedPlace(name, latitude, longitude, coord_system)
        with self._connect(write=True) as connection:
            query = 'INSERT INTO places (name, latitude, longitude, coord_system) VALUES (?, ?, ?, ?)'
            if replace:
                query += ' ON CONFLICT(name) DO UPDATE SET latitude=excluded.latitude, longitude=excluded.longitude, coord_system=excluded.coord_system'
            try:
                connection.execute(query, (name, latitude, longitude, coord_system))
            except sqlite3.IntegrityError as exc:
                raise PlaceError(f"地点“{name}”已存在；确认覆盖请加 --replace") from exc
        return place

    def delete(self, name: str):
        name = validate_name(name)
        if self.path.exists():
            with self._connect(write=True) as connection:
                if connection.execute('DELETE FROM places WHERE name = ?', (name,)).rowcount:
                    return
        raise PlaceError(f"未保存地点“{name}”，未删除任何地点")
