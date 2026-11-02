"""允许 `python -m embyqt` 启动。"""

import sys

from .main import main

sys.exit(main())
