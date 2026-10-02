--[[--
Capability negotiation — lets the plugin ask a Kolibre server "do you support
feature X" instead of just trying X and hoping for the best, so a server that
predates a given feature degrades gracefully (feature hidden) instead of the
plugin firing a request the server has no route for at all.

Structural port of BookOrbit's own bookorbit_capabilities.lua (same
three-state result, same per-server in-memory cache — see below), adapted to
this plugin's own KolibreApi shape.

Cache is keyed by server URL (self.api.server_url, see kolibre_api.lua),
in-memory only for the current KOReader process — no persistence, no TTL.
Rationale: a device only ever talks to one server at a time in practice, the
cache is trivially small, and a stale answer only matters across a KOReader
restart (which clears it) or a server upgrade mid-session (rare enough that
"restart KOReader" is an acceptable workaround for phase 1 — no retry logic
here yet, see below).

Three states, not two, returned by supports():
  true  — the /capabilities call succeeded AND the feature is listed.
  false — the /capabilities call succeeded but the feature is NOT listed
          (confirmed absence — this server genuinely predates or lacks it).
  nil   — the /capabilities call itself failed: network error, timeout, 5xx,
          or a 404 (old server, the route doesn't exist yet at all — an
          EXPECTED response on such a server, not a fault to warn about).
Phase 1 callers all just want a yes/no gate and can treat false and nil the
same (safely hide the feature either way), but the two are kept distinct in
the return value on purpose: a future phase may want to retry an unknown
(nil) state — the server might come back, or get upgraded — but should never
retry a confirmed-absent (false) one. This module itself doesn't retry
anything yet either way; once a server URL has an entry (fetched or not) it
is cached for the rest of the process.
]]

local logger = require("logger")

local KolibreCapabilities = {}

-- server_url -> { fetched = bool, server_version = string|nil,
--                 capabilities = {feature_name = true, ...} }
-- `fetched = false` entries have no `capabilities` table — supports() must
-- check `fetched` first, never index `capabilities` unconditionally.
local _cache = {}

local function fetchCapabilities(api)
    local result, err = api:request("GET", "/api/kolibre/devices/capabilities")
    if not result then
        -- A 404 here means "old server, this route doesn't exist yet" —
        -- the expected, common case while this feature rolls out, not
        -- worth alarming logs about. Anything else (timeout, 5xx, transport
        -- error) is worth a warning since it might be a real problem.
        if err ~= 404 then
            logger.warn("Kolibre: /capabilities fetch failed:", err)
        end
        return { fetched = false }
    end

    local set = {}
    for _, name in ipairs(result.capabilities or {}) do
        set[name] = true
    end
    return {
        fetched = true,
        server_version = result.serverVersion,
        capabilities = set,
    }
end

-- Returns true/false/nil per the three states documented above. Triggers
-- (and caches) the /capabilities fetch on first call for this server if not
-- already cached; every later call this session is free.
function KolibreCapabilities:supports(api, feature_name)
    local server_url = api and api.server_url
    if not server_url then return nil end

    local entry = _cache[server_url]
    if not entry then
        entry = fetchCapabilities(api)
        _cache[server_url] = entry
    end

    if not entry.fetched then return nil end
    return entry.capabilities[feature_name] == true
end

return KolibreCapabilities
