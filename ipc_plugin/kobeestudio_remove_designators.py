import os, sys
from kobeestudio_ipc import main

code = main("remove-designators")
if sys.platform == "win32": os._exit(code)
raise SystemExit(code)
