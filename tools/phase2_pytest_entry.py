import faulthandler
import os
import sys
faulthandler.enable()
faulthandler.dump_traceback_later(30 if os.environ.get('TFI_INTEGRATION')=='1' else 6)
print('phase2 pytest entry started',flush=True)
import pytest
print('pytest imported; beginning selected case',flush=True)
try:
    raise SystemExit(pytest.main(sys.argv[1:]))
finally:
    faulthandler.cancel_dump_traceback_later()
