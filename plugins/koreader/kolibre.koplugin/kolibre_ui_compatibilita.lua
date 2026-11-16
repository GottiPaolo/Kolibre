-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
La vista dice se qualcun altro le ha cambiato le misure sotto i piedi.

**Da zero: perche' esiste questo file.** Il 15/11/2026 la vista libreria ha
chiuso KOReader sul Mac di Paolo. La causa non era nostra e non era un
difetto di KOReader: `coverbrowser`, un plugin che KOReader porta con se',
non cambia l'aspetto del gestore di file con dei parametri — **riscrive dei
metodi sulla classe `FileChooser`**, da cui la nostra vista eredita. Il suo
`_recalculateDimen` calcola le misure che servono a lui e non scrive
`available_height`, che a noi serve: aritmetica su un `nil`, e KOReader si
chiude in faccia.

Quella falla e' chiusa — la vista calcola le proprie misure da se', e
`prove/la_vista_regge_coverbrowser` lo tiene fermo. **La lezione pero' e'
piu' grande di quel plugin**: non sapremo mai in anticipo quale, fra i
plugin installati sul dispositivo di una persona che non conosciamo,
riscrivera' quale metodo. E su un Kindle non c'e' una console da guardare:
se la vista esce storta, chi la usa vede una vista storta e basta.

**Quindi questo modulo non previene: dichiara.** Guarda se le cose su cui la
vista si appoggia sono quelle che si aspetta, e se non lo sono lo scrive nel
registro e lo dice **una volta sola**.

**Perche' guarda gli invarianti e non chi li ha rotti.** La tentazione era
tenere l'elenco dei plugin colpevoli e confrontare i metodi con gli
originali. Ma gli originali non si conoscono: se un plugin si carica prima di
noi, la copia che faremmo sarebbe gia' la sua. E un elenco di nomi invecchia
al primo plugin nuovo. Un invariante rotto invece si vede comunque, chiunque
l'abbia rotto e qualunque cosa esca domani. I nomi dei plugin accesi entrano
nel messaggio perche' aiutano a capire, non perche' servano a decidere.

**E non puo' far morire la vista.** Una diagnosi che uccide il paziente non
e' una diagnosi: tutto quello che c'e' qui dentro e' difensivo, e chi chiama
lo fa comunque dentro un `pcall`.

Il guardiano e' la prova `la_vista_dice_se_qualcuno_la_tocca`.
]]

local Compat = {}

-- Detto per questa sessione? Una vista si ridisegna a ogni cambio di pagina:
-- un avviso per ridisegno sarebbe un dispositivo inservibile, cioe' peggio
-- del difetto che si sta segnalando.
local gia_detto = false

--- Azzera la memoria dell'avviso. Serve alle prove, e a nient'altro.
function Compat.dimentica()
    gia_detto = false
end

--- I nomi dei plugin accesi, letti SENZA farli caricare.
--
-- `PluginLoader:loadPlugins()` li caricherebbe davvero: chiamarlo per fare
-- una diagnosi vorrebbe dire che la diagnosi cambia il paziente. Si legge il
-- campo gia' popolato (`enabled_plugins`, che esiste sia nella v2025.08 sia
-- nella v2026.07.2 — verificato sulle due release, non su master), e se non
-- c'e' ancora si risponde «non lo so» invece di una bugia.
function Compat.pluginiAccesi(loader)
    local fuori = {}
    if type(loader) ~= "table" then return fuori end
    local accesi = loader.enabled_plugins
    if type(accesi) ~= "table" then return fuori end
    for _i, p in ipairs(accesi) do
        if type(p) == "table" and type(p.name) == "string" then
            table.insert(fuori, p.name)
        end
    end
    return fuori
end

--- Che cosa non torna in questa vista. Una lista di frasi, vuota se va bene.
--
-- Ognuna di queste tre e' un difetto gia' visto o gia' sfiorato, non un
-- controllo di principio.
function Compat.problemi(vista)
    local fuori = {}
    if type(vista) ~= "table" then return fuori end

    -- 1. L'altezza disponibile: e' esattamente quella del 15/11. Senza,
    --    l'altezza di una riga e' una divisione per nil.
    local alta = vista.available_height
    if type(alta) ~= "number" or alta <= 0 then
        table.insert(fuori, "l'altezza disponibile dell'elenco non c'e' o non e' un numero ("
            .. tostring(alta) .. ")")
    end

    -- 2. Le righe per schermata: l'altra meta' di quello che coverbrowser
    --    faceva — metteva le SUE dieci al posto di quelle scelte da Paolo.
    local volute = vista.righe_per_schermata
    local ora = vista.perpage
    if type(ora) ~= "number" or ora <= 0 then
        table.insert(fuori, "le righe per schermata non ci sono (" .. tostring(ora) .. ")")
    elseif type(volute) == "number" and ora ~= volute then
        table.insert(fuori, "le righe per schermata sono " .. tostring(ora)
            .. " invece di " .. tostring(volute) .. ": qualcun altro le ha cambiate")
    end

    -- 3. Il gruppo delle frecce in fondo: e' la tabella in cui infiliamo la
    --    batteria. Se sparisce, la batteria non si vede e non si capisce
    --    perche'.
    if type(vista.page_info) ~= "table" then
        table.insert(fuori, "il gruppo della navigazione in fondo non c'e'")
    end

    return fuori
end

--- Guarda, e se c'e' qualcosa da dire lo dice una volta sola.
--
-- `avvisa` riceve il testo gia' composto. Si passa da fuori invece di
-- mostrare una finestra qui dentro per due ragioni: questo modulo resta
-- provabile senza KOReader, e chi chiama decide se e' il momento di
-- interrompere qualcuno.
function Compat.controlla(vista, avvisa, loader)
    if gia_detto then return false end
    local ok, problemi = pcall(Compat.problemi, vista)
    if not ok or type(problemi) ~= "table" or #problemi == 0 then return false end
    gia_detto = true

    local testo = "Kolibre: la vista libreria non ha trovato le misure che si aspettava.\n- "
        .. table.concat(problemi, "\n- ")
    local nomi = {}
    pcall(function() nomi = Compat.pluginiAccesi(loader) end)
    if #nomi > 0 then
        testo = testo .. "\nPlugin accesi: " .. table.concat(nomi, ", ")
    end

    -- Nel registro sempre, a schermo solo se qualcuno sa come farlo.
    pcall(function() require("logger").warn("[kolibre]", testo) end)
    if type(avvisa) == "function" then pcall(avvisa, testo) end
    return true
end

return Compat
