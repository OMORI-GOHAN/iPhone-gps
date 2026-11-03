"""Platform-specific user storage paths; existing Linux locations stay stable."""

import os
from pathlib import Path
import sys


def user_data_directory() -> Path:
    if sys.platform == 'win32':
        local_app_data = os.environ.get('LOCALAPPDATA')
        base = (Path(local_app_data) if local_app_data and Path(local_app_data).is_absolute()
                else Path.home() / 'AppData' / 'Local')
    else:
        data_home = os.environ.get('XDG_DATA_HOME')
        base = (Path(data_home) if data_home and Path(data_home).is_absolute()
                else Path.home() / '.local' / 'share')
    return base / 'iphone-gps'
