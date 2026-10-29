# Compatibility entry: the mid-tier implementation lives in tests/mid/archived/scripts/check_tools.py.
# Keep the original module/package and __file__ so existing fixtures resolve unchanged.
from pathlib import Path as _TierPath
_tier_source = _TierPath(__file__).resolve().parents[1] / 'tests/mid/archived/scripts/check_tools.py'
exec(compile(_tier_source.read_bytes(), str(_tier_source), "exec"), globals())
