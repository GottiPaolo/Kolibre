--[[--
Il registro di KOReader, ripulito e accorciato, pronto da mandare al server.

**A che cosa serve.** Quando sul Kindle qualcosa «non parte e non dice
niente», l'unico posto dove la risposta c'e' e' il `crash.log` di KOReader —
e su un Kindle quel file si raggiunge solo con un cavo. Questa funzione e'
la meta' del plugin di una voce di menu che lo manda al server di Paolo, da
dove si legge con un browser.

**Perche' e' un modulo a parte, e puro.** Non tocca KOReader: prende una
stringa e ne torna un'altra. Cosi' si prova senza avviare niente (vedi
la prova `il_registro_si_ripulisce`), ed e' la stessa
strada di `kolibre_patch.lua` e `kolibre_rinvii.lua`.

────────────────────────────────────────────────────────────────────────
CHE COSA SI TOGLIE, E PERCHE' PROPRIO QUESTO
────────────────────────────────────────────────────────────────────────

Il registro non e' scritto da noi: raccoglie tutto quello che KOReader manda
a schermo, quindi non si puo' sapere in anticipo che cosa ci finisca. Si
tolgono percio' le due cose che **non devono uscire dal dispositivo** anche
se il file resta in casa:

  * **il token del dispositivo**, in tutte le forme in cui potrebbe
    comparire: dietro un `Bearer`, dentro un parametro `token=`, o come
    valore di `device_token`/`library_token`. Oggi il plugin non lo scrive
    da nessuna parte — l'ho verificato riga per riga — ma «oggi non lo
    scrive» non e' una garanzia per domani, e un registro si manda proprio
    quando e' successo qualcosa di imprevisto.
  * **gli indirizzi**: l'URL del server e qualunque indirizzo IP. Un errore
    di rete di KOReader dice volentieri «connessione rifiutata a
    192.168.x.y:8081», e quello e' l'indirizzo di casa di Paolo.

**Quello che NON si toglie**: titoli dei libri e percorsi dei file. Sono
suoi, vanno sul suo server, e sono spesso l'unica cosa che spiega un difetto
(«si e' rotto aprendo QUEL libro»). Toglierli vorrebbe dire mandare un file
che non serve a niente.

**Il taglio in coda.** Un `crash.log` puo' essere grosso, e quello che serve
sta sempre in fondo: si mandano gli ultimi `MAX_BYTE`, tagliando all'inizio
di una riga per non spedire mezza parola. In testa resta scritto quanto si e'
tagliato, cosi' chi legge sa di stare guardando una coda e non tutto.
]]

local Diagnostica = {}

--: Quanto si manda al massimo. 256 KB sono migliaia di righe: abbastanza per
--  contenere l'avvio, il difetto e quello che e' successo dopo, e abbastanza
--  poco da non pesare su una connessione di un lettore.
Diagnostica.MAX_BYTE = 256 * 1024

--: Il segnaposto che prende il posto di quello che si toglie. Si vede, e
--  **si deve vedere**: un buco silenzioso farebbe pensare a un registro
--  incompleto invece che ripulito.
local TOLTO = "[tolto]"

-- Le sostituzioni, in ordine. Ognuna e' {schema, rimpiazzo} di `gsub`.
--
-- L'ordine conta: prima le forme con un nome davanti (`token=...`), poi
-- quelle generiche (un indirizzo nudo), altrimenti la generica mangia un
-- pezzo della specifica e il risultato e' illeggibile.
local REGOLE = {
    -- "Authorization: Bearer abc123..." in qualunque forma
    { "[Bb]earer%s+[%w%-%._~%+/=]+", "Bearer " .. TOLTO },
    -- token=..., device_token: "...", library_token = '...'
    { "([Tt]oken[\"']?%s*[:=]%s*[\"']?)[%w%-%._~%+/=]+", "%1" .. TOLTO },
    -- http://host:porta  e  https://host/...
    --
    -- **Due regole e non una con il punto interrogativo.** Negli schemi di
    -- Lua il `?` vale per UN carattere, non per un gruppo: `(:%d+)?` non
    -- vuol dire «la porta se c'e'», e un indirizzo per nome senza porta
    -- passava intero. Trovato dalla prova, non leggendo il codice.
    { "(https?://)[%w%.%-]+:%d+", "%1" .. TOLTO },
    { "(https?://)[%w%.%-]+", "%1" .. TOLTO },
    -- un indirizzo IPv4 nudo, con o senza porta
    { "%d+%.%d+%.%d+%.%d+:%d+", TOLTO },
    { "%d+%.%d+%.%d+%.%d+", TOLTO },
}

--- Il testo senza token e senza indirizzi.
function Diagnostica.ripulisci(testo)
    if type(testo) ~= "string" then return "" end
    for _i, regola in ipairs(REGOLE) do
        testo = testo:gsub(regola[1], regola[2])
    end
    return testo
end

--- Gli ultimi `MAX_BYTE` del testo, tagliati a inizio riga.
--
-- Torna anche quanti byte sono stati buttati, perche' chi legge deve saperlo.
function Diagnostica.coda(testo, massimo)
    if type(testo) ~= "string" then return "", 0 end
    massimo = massimo or Diagnostica.MAX_BYTE
    if #testo <= massimo then return testo, 0 end
    local taglio = #testo - massimo + 1
    -- Dal taglio in avanti, fino al primo a capo: cosi' la prima riga del
    -- file mandato e' una riga intera.
    local a_capo = testo:find("\n", taglio, true)
    local inizio = a_capo and (a_capo + 1) or taglio
    return testo:sub(inizio), inizio - 1
end

--- Il registro pronto da mandare: ripulito, accorciato, con l'intestazione.
--
-- L'intestazione dice le tre cose che servono a chi lo legge sul server:
-- da quale dispositivo arriva, che versione del plugin aveva, e che quello
-- che segue e' una coda ripulita — non il file intero.
function Diagnostica.prepara(testo, info)
    info = info or {}
    local corpo, tagliati = Diagnostica.coda(Diagnostica.ripulisci(testo))
    local testa = {
        "# registro di diagnostica Kolibre",
        "# dispositivo: " .. tostring(info.dispositivo or "?"),
        "# plugin: " .. tostring(info.versione or "?"),
        "# quando: " .. tostring(info.quando or "?"),
    }
    if tagliati > 0 then
        table.insert(testa, string.format(
            "# ATTENZIONE: e' la CODA del registro, i primi %d byte non ci sono.", tagliati))
    end
    table.insert(testa, "# token e indirizzi sono stati tolti e sostituiti con " .. TOLTO .. ".")
    table.insert(testa, "")
    return table.concat(testa, "\n") .. corpo
end

return Diagnostica
