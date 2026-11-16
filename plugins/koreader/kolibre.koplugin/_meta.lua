-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one (the server puts them in the zip — see
-- main.lua's own header for why they are not in the source folder). This plugin extends KOReader
-- (AGPL-3.0) from the inside, which is why the whole project is AGPL.

local _ = require("gettext")
return {
    name = "kolibre",
    fullname = _("Kolibre sync"),
    description = _([[Syncs this device with a Kolibre server: receives the books the server queued, applies the removals it asked for (with confirmation), reports page counts, and uploads reading positions and highlights.]]),
}
