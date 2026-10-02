-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files in the Kolibre repository. This plugin extends KOReader
-- (AGPL-3.0) from the inside, which is why the whole project is AGPL.

local _ = require("gettext")
return {
    name = "kolibre",
    fullname = _("Kolibre sync"),
    description = _([[Syncs this device with a Kolibre server: receives the books the server queued, applies the removals it asked for (with confirmation), reports page counts, and uploads reading positions and highlights.]]),
}
