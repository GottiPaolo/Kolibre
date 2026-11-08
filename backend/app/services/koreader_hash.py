"""
KOReader's own "partial MD5" file-identity hash, ported from KOReader's real
source (frontend/util.lua, function util.partialMD5) — verified against
https://github.com/koreader/koreader/blob/master/frontend/util.lua:

    local lshift = bit.lshift
    function util.partialMD5(filepath)
        local file = io.open(filepath, "rb")
        if not file then return end
        local step, size = 1024, 1024
        local update = md5()
        for i = -1, 10 do
            file:seek("set", lshift(step, 2*i))
            local sample = file:read(size)
            if sample then
                update(sample)
            else
                break
            end
        end
        file:close()
        return update()
    end

`lshift` here is LuaJIT's `bit.lshift`, which masks its shift amount to 5
bits (`n & 31`) rather than doing a mathematical right-shift for negative
`n` — so `lshift(1024, -2)` (the i=-1 case) is NOT `1024 / 4 = 256` as a naive
"negative shift = divide" reading would suggest; it's `1024 << 30` truncated
to a 32-bit int, which is exactly 0 (1024 = 2^10, so 2^10 << 30 = 2^40, and
2^40 mod 2^32 = 0). This was confirmed by actually running LuaJIT's `bit`
library locally rather than assuming a formula, since getting this wrong
would silently make every hash mismatch a real device's.

The 12 offsets below are that verified `lshift(1024, 2*i)` output for
i = -1..10, hardcoded rather than recomputed with bit ops in Python to avoid
any risk of re-introducing the same mistake.
"""

import hashlib
import os
from typing import Optional

_SAMPLE_SIZE = 1024

# lshift(1024, 2*i) for i = -1, 0, 1, ..., 10 — verified via LuaJIT's bit.lshift.
_OFFSETS = [0, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864, 268435456, 1073741824]


def partial_md5(file_path: str) -> Optional[str]:
    if not os.path.exists(file_path):
        return None
    h = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for offset in _OFFSETS:
                f.seek(offset)
                sample = f.read(_SAMPLE_SIZE)
                if not sample:
                    break
                h.update(sample)
        return h.hexdigest()
    except OSError:
        return None
