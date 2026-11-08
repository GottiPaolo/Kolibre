--[[--
Che cosa è già stato proposto, e quando — per non riproporlo domani.

**Perché esiste un modulo per una sottrazione.** Perché la sottrazione
sbagliata è costata una giornata intera di aggiornamenti mancati, e la
versione prima non si poteva provare senza un Kindle in mano.

Fino all'08/11/2026 il controllo automatico degli aggiornamenti
(`_autoCheckForUpdate` in main.lua) aveva un freno di ventiquattr'ore sul
**controllare**, e lo scriveva *prima* di controllare. Chi aveva acceso
«Controlla aggiornamenti» al risveglio vedeva questo: il primo risveglio
della giornata controllava, non trovava niente — perché in quel momento sul
server non c'era ancora niente — e spendeva la giornata. Tutti i risvegli
dopo tornavano subito. *Paolo: «ho abilitato il check update al risveglio sul
mio dispositivo eppure continua a non trovarmelo e devo controllare a mano.»*
Verificato nel suo `settings.reader.lua`: `kolibre_last_update_check_at`
valeva le 12:12:49 dell'8/11, l'istante di una sincronizzazione `auto_avvio`
che la cronologia del server registra, e da lì in poi niente.

**Il freno cambia oggetto.** Controllare costa due richieste piccole a un
server che la sincronizzazione del risveglio ha già contattato un istante
prima: non c'è niente da risparmiare. Quello che va frenato è **riproporre**
— una finestra che torna a ogni risveglio dopo che hai detto «Più tardi» è
una finestra che si impara a chiudere senza leggerla.

Quindi: si controlla sempre, e si ripropone solo se è passato il tempo
**oppure** se c'è qualcosa di diverso da proporre.

**L'impronta tiene il contenuto, non il numero di versione.** Una patch che
cambia senza cambiare la versione che dichiara è il caso normale mentre la si
sviluppa, e deve risultare da riproporre. Solo lo sha256 lo dice — è la
stessa ragione per cui il server confronta le patch per impronta
(services/patch_koreader.py::stato_sul_dispositivo).

Niente `require` di KOReader qui dentro, di proposito: è la parte che si può
provare su un computer, senza un dispositivo in mano.
]]

local KolibreRinvii = {}

--- L'impronta di quello che c'è da aggiornare adesso.
---
--- `nuova` è la versione nuova del plugin (o nil), `patch` l'elenco delle
--- patch da sostituire. Torna **nil quando non c'è niente**: è il valore su
--- cui chi chiama distingue «non c'è nulla da proporre» da «c'è qualcosa, e
--- forse l'ho già proposto». Un `nil` non si salva, e quindi un controllo a
--- vuoto non consuma la giornata — che era esattamente il difetto.
function KolibreRinvii.impronta(nuova, patch)
    local pezzi = {}
    if type(nuova) == "table" and nuova.versione then
        table.insert(pezzi, "plugin=" .. tostring(nuova.versione))
    end
    -- Ordinate: l'ordine in cui il server le elenca non e' una decisione, e
    -- un riordino qualunque non deve rimettere la finestra davanti a chi
    -- aveva detto «dopo».
    local nomi = {}
    if type(patch) == "table" then
        for _idx, p in ipairs(patch) do
            if type(p) == "table" and type(p.file) == "string" and p.file ~= "" then
                table.insert(nomi, p.file .. ":" .. tostring(p.sha256 or ""))
            end
        end
    end
    table.sort(nomi)
    for _idx, n in ipairs(nomi) do table.insert(pezzi, n) end

    if #pezzi == 0 then return nil end
    return table.concat(pezzi, "|")
end

--- Si deve mettere in mezzo una finestra?
---
--- `rinvio` è quello che c'è nelle impostazioni (`{ impronta, at }`, o
--- qualunque cosa ci fosse rimasta), `impronta` quello che si proporrebbe
--- adesso, `attesa` i secondi da lasciar passare prima di riproporre la
--- stessa cosa.
function KolibreRinvii.deveProporre(rinvio, impronta, adesso, attesa)
    -- Niente da proporre: non e' «e' presto», e' «non c'e' nulla».
    if impronta == nil then return false end
    -- Nessun rinvio, o un rinvio che non si capisce: si propone. Sbagliare
    -- mostrando una finestra di troppo e' meglio che sbagliare tacendo.
    if type(rinvio) ~= "table" or type(rinvio.impronta) ~= "string" then return true end
    -- Qualcosa di diverso da quello che si e' proposto: subito, senza
    -- aspettare il tempo del precedente.
    if rinvio.impronta ~= impronta then return true end

    local quando = tonumber(rinvio.at) or 0
    -- **L'orologio che torna indietro.** Su un Kindle scaricato del tutto la
    -- data puo' ripartire da molto prima: il rinvio salvato si troverebbe
    -- nel futuro, e `adesso - quando` sarebbe un numero grande e negativo —
    -- cioe' silenzio per sempre. Un rinvio nel futuro e' un rinvio senza
    -- senso.
    if adesso < quando then return true end
    return (adesso - quando) >= (tonumber(attesa) or 0)
end

--- Il segnale da salvare nelle impostazioni dopo aver proposto.
function KolibreRinvii.rinviato(impronta, adesso)
    return { impronta = impronta, at = adesso }
end

return KolibreRinvii
