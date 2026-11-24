-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
Il riordino del lettore in `Autore/Libro`: l'ultima tappa di «Initialize
library» (piano 1.0.0, approvato da Paolo il 24/11/2026).

**Da zero.** I libri che Kolibre consegna stanno in `<libri>/<Autore>/
<Titolo>.<ext>`. Quelli che c'erano prima di Kolibre, o copiati a mano, stanno
dove li ha messi chi li ha copiati. Una volta accoppiati (per impronta, o
mandati al server) Kolibre sa chi sono, e li mette dove metterebbe un libro
suo: cosi' la vista Kolibre, che e' fatta di cartelle d'autore, li mostra.

**Come si sposta un libro senza perdere la lettura** — lo studio del
24/11, fatto sul KOReader vero (2025.08 e 2026.03) e sul sorgente dei tag
(2026.07.x), e che Paolo ha approvato:

  1. la cartella di arrivo, e niente gia' li' (un file con quel nome
     vincerebbe, e i suoi metadati verrebbero sovrascritti);
  2. `os.rename` del file, e si guarda il disco che sia andato;
  3. `DocSettings.updateLocation(vecchio, nuovo)`: riscrive i metadati
     (posizione, note, copertina scelta) nel posto giusto per la sede nuova,
     qualunque sia l'impostazione `document_metadata_folder`;
  4. `ReadHistory:updateItem` e `ReadCollection:updateItem`, DOPO lo
     spostamento: prima, il secondo va in errore;
  5. i file che non sono di KOReader rimasti nella `.sdr` vecchia si portano
     dietro a mano (`updateLocation` non li sposta), e la cartella vecchia si
     toglie se e' vuota.

Lo stesso su tutte e tre le versioni: nessun ripiego per versione.

**L'unico caso in cui `updateLocation` non sposta niente**: metadati accanto
al file («doc») con l'impostazione di KOReader su «hash». Allora i metadati
vengono dietro col passo 5, come i file estranei, e il libro si conta fra
quelli coi metadati fuori posto: e' la riga del riepilogo che Paolo ha
voluto.

Le API di KOReader arrivano da fuori (`k`), cosi' la prova
`il_riordino_non_perde_la_lettura` le usa vere dentro KOReader su una cartella
di passaggio.
]]

local R = {}

--- Dove dovrebbe stare un libro del manifesto. `nil` se non si sa (manca il
--- titolo, o l'estensione).
function R.destinazione(books_dir, voce, sanitize)
    if type(voce) ~= "table" or type(voce.path) ~= "string" then return nil end
    if type(voce.title) ~= "string" or voce.title == "" then return nil end
    local ext = voce.path:match("%.([%w]+)$")
    if not ext then return nil end
    local dir = books_dir
    if type(voce.author) == "string" and voce.author ~= "" then
        dir = books_dir .. "/" .. sanitize(voce.author)
    end
    return dir .. "/" .. sanitize(voce.title) .. "." .. ext:lower()
end

local function cartellaDi(percorso) return percorso:match("^(.*)/[^/]+$") end

--- I libri del manifesto da spostare: `{chiave, voce, da, a}`.
---
--- **Si sposta solo chi sta fuori dalla cartella del suo autore.** Un libro
--- gia' nella cartella giusta resta dov'e', anche se il nome del file non e'
--- quello che Kolibre gli darebbe oggi: sul Kindle di Paolo 88 libri su 211
--- hanno un nome che non si ricalcola piu' uguale (convenzioni cambiate nel
--- tempo, vedi `doveScrivere` in kolibre_sync.lua), e rinominarli tutti
--- sarebbe un lavoro grosso per niente.
---
--- Non si toccano il libro aperto (chiudendolo il lettore riscriverebbe i
--- metadati al posto vecchio), i file che non ci sono, e quelli la cui
--- destinazione e' occupata — questi tornano a parte.
function R.daSpostare(manifest, books_dir, sanitize, esiste, aperto)
    local da_spostare, occupati = {}, {}
    for chiave, voce in pairs(manifest:all()) do
        local a = R.destinazione(books_dir, voce, sanitize)
        if a and cartellaDi(a) ~= cartellaDi(voce.path) and voce.path ~= aperto
                and esiste(voce.path) and voce.library and voce.calibre_book_id then
            if esiste(a) then
                table.insert(occupati, { chiave = chiave, voce = voce, da = voce.path, a = a })
            else
                table.insert(da_spostare, { chiave = chiave, voce = voce, da = voce.path, a = a })
            end
        end
    end
    table.sort(da_spostare, function(x, y) return x.a < y.a end)
    return da_spostare, occupati
end

--- Sposta UN libro. Torna `ok, errore, fuori_posto`.
---
--- `k` porta: lfs, makePath, DocSettings, ReadHistory, ReadCollection,
--- `preferita` (l'impostazione `document_metadata_folder`, «doc» di serie).
function R.sposta(da, a, k)
    local lfs = k.lfs
    if lfs.attributes(a, "mode") then return false, "destination exists" end
    k.makePath(cartellaDi(a))
    local preferita = k.preferita or "doc"

    local _sidecar, dove = nil, nil
    pcall(function() _sidecar, dove = k.DocSettings:findSidecarFile(da) end)
    local fuori_posto = dove ~= nil and dove ~= preferita
    local sdr_vecchia = k.DocSettings:getSidecarDir(da, "doc")
    local sdr_nuova = k.DocSettings:getSidecarDir(a, "doc")

    local ok_r, err_r = os.rename(da, a)
    if not lfs.attributes(a, "mode") or lfs.attributes(da, "mode") then
        return false, tostring(err_r or "rename failed")
    end

    pcall(function() k.DocSettings.updateLocation(da, a) end)
    -- Quello che e' rimasto nella `.sdr` accanto al file vecchio viene
    -- dietro: i file che non sono di KOReader, e — nel caso «metadati
    -- accanto al file, impostazione su hash», in cui `updateLocation` non
    -- tocca niente — i metadati stessi. Dentro le due `.sdr` i nomi sono gli
    -- stessi (`metadata.<ext>.lua`), quindi KOReader li ritrova.
    if lfs.attributes(sdr_vecchia, "mode") == "directory" then
        local avanzi = {}
        for voce in lfs.dir(sdr_vecchia) do
            if voce ~= "." and voce ~= ".." then table.insert(avanzi, voce) end
        end
        if #avanzi > 0 then k.makePath(sdr_nuova) end
        for _i, voce in ipairs(avanzi) do
            if not lfs.attributes(sdr_nuova .. "/" .. voce, "mode") then
                os.rename(sdr_vecchia .. "/" .. voce, sdr_nuova .. "/" .. voce)
            end
        end
        pcall(lfs.rmdir, sdr_vecchia)
    end
    pcall(function() k.ReadHistory:updateItem(da, a) end)
    pcall(function() k.ReadCollection:updateItem(da, a) end)
    return true, nil, fuori_posto
end

return R
