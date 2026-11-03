"""Convenience entry point using the isolated local dependency copy, without install."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'.runtime/test-tools',ROOT/'.runtime/runtime-tools'):
    sys.path.insert(0,str(path))
sys.dont_write_bytecode=True
from node.__main__ import main
if __name__=='__main__': main()
