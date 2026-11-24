-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
I libri eliminati dal lettore che il server non sa ancora.

**Da zero.** Quali libri stanno su un lettore lo decide il server: a ogni
sincronizzazione offre quello che manca. Per questo, fino alla 0.31.0,
«elimina dal dispositivo» chiedeva PRIMA al server di non volere piu' quel
libro, e cancellava il file solo dopo il si': senza rete non si poteva
eliminare niente, e un file cancellato a insaputa del server tornava alla
sincronizzazione dopo.

**Adesso** (Paolo, 24/11/2026): il file si cancella subito, e la richiesta
al server va in questa coda. La coda si consegna:

  * appena c'e' rete, se c'e' gia' quando si elimina;
  * all'inizio di OGNI sincronizzazione, **prima** dell'handshake: e' la
    risposta all'handshake che porta i libri da consegnare, quindi il server
    deve gia' sapere che quel libro non lo vogliamo piu';
  * e se una voce non e' riuscita a partire, i libri in coda si tolgono da
    quelli da scaricare (`togliDaiDaScaricare`): un libro eliminato non torna
    mai, nemmeno con il server che non risponde a quella sola richiesta.

**Quando una voce esce dalla coda.** Quando il server risponde si', e anche
quando risponde 404 («non e' su questo lettore, non c'e' niente da
togliere»): la cosa che volevamo e' gia' vera. Un altro rifiuto del server
(400: l'identita' non basta) non migliora riprovando, e si scarta col suo
segno nel registro. Un errore di rete o del server (5xx, 409, 429) si
riprova alla volta dopo.

Il modulo non sa niente di KOReader, ne' di UIManager: riceve il manifesto
e l'API, e cosi' la regola si prova con `lua` e basta
(`prove/elimina_senza_rete.lua`).
]]

local R = {}

--: La chiave nei metadati del manifesto.
R.CHIAVE = "rimozioni_in_coda"

local ENDPOINT = "/api/kolibre/devices/books/removed"

--- La coda com'e' adesso: una lista, mai nil.
function R.elenco(manifest)
    local coda = manifest:getMeta(R.CHIAVE)
    if type(coda) ~= "table" then return {} end
    local copia = {}
    for _i, voce in ipairs(coda) do table.insert(copia, voce) end
    return copia
end

--- Mette in coda un libro eliminato. `voce` e' l'identita' come la vuole
--- `/books/removed` ({hash}, {library, calibre_book_id}, {format}) piu'
--- `path` e `quando`, per il registro.
function R.aggiungi(manifest, voce)
    local coda = R.elenco(manifest)
    table.insert(coda, voce)
    manifest:setMeta(R.CHIAVE, coda)
end

--- Che cosa fare di una voce, dato l'errore di `api:request`.
--- `"fatta"`, `"scarta"` o `"riprova"`.
function R.esito(risposta, errore)
    if risposta then return "fatta" end
    if errore == 404 then return "fatta" end
    if type(errore) == "number" and errore >= 400 and errore < 500
            and errore ~= 408 and errore ~= 409 and errore ~= 429 then
        return "scarta"
    end
    return "riprova"
end

--- Consegna la coda al server. Torna quante voci sono uscite e quante
--- restano. `registro(msg)` e' facoltativo.
function R.consegna(manifest, api, registro)
    local coda = R.elenco(manifest)
    if #coda == 0 then return 0, 0 end
    local restanti, uscite = {}, 0
    for _i, voce in ipairs(coda) do
        local corpo = {
            hash = voce.hash, format = voce.format,
            library = voce.library, calibre_book_id = voce.calibre_book_id,
        }
        local risposta, errore = api:request("POST", ENDPOINT, corpo)
        local cosa = R.esito(risposta, errore)
        if cosa == "riprova" then
            table.insert(restanti, voce)
        else
            uscite = uscite + 1
            if cosa == "scarta" and registro then
                registro("Kolibre: rimozione scartata dal server (" .. tostring(errore) .. "): "
                    .. tostring(voce.path))
            end
        end
    end
    manifest:setMeta(R.CHIAVE, restanti)
    return uscite, #restanti
end

--- Il libro da scaricare e' uno di quelli in coda?
local function inCoda(coda, item)
    for _i, voce in ipairs(coda) do
        if voce.library and item.library and voce.calibre_book_id ~= nil
                and voce.library == item.library
                and tonumber(voce.calibre_book_id) == tonumber(item.calibre_book_id)
                and (not voce.format or not item.format
                     or voce.format:upper() == tostring(item.format):upper()) then
            return true
        end
        if voce.hash and item.delivery_hash and voce.hash == item.delivery_hash then
            return true
        end
    end
    return false
end

--- I libri da scaricare, senza quelli eliminati che il server non sa ancora.
function R.togliDaiDaScaricare(manifest, sends)
    local coda = R.elenco(manifest)
    if #coda == 0 then return sends or {}, 0 end
    local tenuti, tolti = {}, 0
    for _i, item in ipairs(sends or {}) do
        if inCoda(coda, item) then tolti = tolti + 1 else table.insert(tenuti, item) end
    end
    return tenuti, tolti
end

return R
