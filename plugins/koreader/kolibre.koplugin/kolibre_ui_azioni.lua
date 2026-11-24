-- Kolibre — KOReader plugin.
-- Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
-- NOTICE files next to this one.

--[[--
I menu che si aprono tenendo premuto: su un libro, e sul logo.

**Da zero: perche' la pressione prolungata.** Nella vista Kolibre il tocco
apre il libro, senza schede intermedie (decisione di Paolo del 15/11): e' la
cosa che si fa novantanove volte su cento, e deve costare un dito. Tutto il
resto — mandare una posizione, togliere un libro dal lettore — e' la
centesima volta, e va messo dove non si preme per sbaglio. La pressione
prolungata e' quel posto.

**Perche' un file a parte.** Questi due menu servono a **tre** finestre: la
libreria (`kolibre_ui_libreria`), la cronologia e gli ultimi invii (che
discendono entrambe da `kolibre_ui_elenco`). Tre copie dello stesso menu
smettono di essere uguali alla prima voce aggiunta — e' la stessa ragione per
cui la cronologia e gli invii hanno una base comune.

────────────────────────────────────────────────────────────────────────
DUE SCELTE CHE VALE LA PENA SPIEGARE
────────────────────────────────────────────────────────────────────────

**1. La scheda del libro e' diventata il titolo del menu.** Fino al 16/11
tenendo premuto un libro nella libreria usciva un riquadro con titolo,
autore, biblioteca e pagine, e nient'altro: si leggeva e si chiudeva. Ora
quelle stesse righe sono il titolo del menu delle azioni. Non si e' perso
niente, e si e' guadagnato che la domanda «su quale libro sto agendo?» ha la
risposta scritta sopra i pulsanti — che e' esattamente la domanda da farsi
prima di premere «elimina».

**2. Il menu del logo non e' un elenco scritto a mano**, e' il primo livello
del menu del plugin, chiesto a `main.lua` (`Kolibre:_vociPrimoLivello`).
Paolo l'ha chiesto cosi': «un menu che coincide con il primo livello di
quello del plugin». Scriverlo a parte vorrebbe dire due elenchi che alla
prima voce aggiunta non coincidono piu' — e «coincide» era il requisito. Si
salta una voce sola, «apri la libreria di Kolibre», perche' la si sta
guardando.
]]

local ButtonDialog = require("ui/widget/buttondialog")
local ConfirmBox = require("ui/widget/confirmbox")
local InfoMessage = require("ui/widget/infomessage")
local UIManager = require("ui/uimanager")
local t = require("kolibre_lingua").t

local Azioni = {}

--- Il testo di una voce di menu di KOReader, che puo' essere una funzione.
local function etichetta(voce)
    if type(voce.text_func) == "function" then
        local ok, testo = pcall(voce.text_func)
        if ok and type(testo) == "string" then return testo end
    end
    return voce.text or "?"
end

--- Una voce e' attiva? `enabled_func` e' la forma che KOReader usa.
local function attiva(voce)
    if type(voce.enabled_func) ~= "function" then return true end
    local ok, risposta = pcall(voce.enabled_func)
    return (ok and risposta) and true or false
end

--- Una voce con l'interruttore: davanti ci va il segno di spunta.
local function conSpunta(voce, testo)
    if type(voce.checked_func) ~= "function" then return testo end
    local ok, acceso = pcall(voce.checked_func)
    if not ok then return testo end
    return (acceso and "☑ " or "☐ ") .. testo
end

--- Un menu di KOReader, mostrato come riquadro di pulsanti.
--
-- **Perche' non il menu vero di KOReader** (`TouchMenu`): quello vive dentro
-- il gestore di file e vuole il suo contesto; da una finestra nostra non si
-- apre senza entrare nelle sue viscere, che e' la cosa che il 15/11 ha
-- chiuso KOReader. Un riquadro di pulsanti, invece, e' un widget qualunque.
--
-- I sottomenu si aprono in un riquadro nuovo: una voce con
-- `sub_item_table`/`sub_item_table_func` chiude questo e ne mostra un altro,
-- col nome della voce come titolo. Vale a qualunque profondita', perche' la
-- funzione richiama se stessa.
function Azioni.menuDiVoci(voci, titolo)
    local dialogo
    local pulsanti = {}
    for _i, voce in ipairs(voci or {}) do
        -- Il separatore di KOReader (`separator = true`) non ha un pulsante
        -- suo: qui si salta, perche' una riga vuota in un riquadro di
        -- pulsanti sembra un pulsante rotto.
        if voce.text or voce.text_func then
            local testo = conSpunta(voce, etichetta(voce))
            local sotto = voce.sub_item_table
            if not sotto and type(voce.sub_item_table_func) == "function" then
                local ok, risposta = pcall(voce.sub_item_table_func)
                if ok then sotto = risposta end
            end
            table.insert(pulsanti, {{
                text = sotto and (testo .. "  ▸") or testo,
                enabled = attiva(voce),
                callback = function()
                    UIManager:close(dialogo)
                    if sotto then
                        Azioni.menuDiVoci(sotto, etichetta(voce))
                    elseif type(voce.callback) == "function" then
                        -- Sotto `pcall`: una voce che alza non deve lasciare
                        -- la vista con un riquadro chiuso e niente al suo
                        -- posto.
                        local ok, errore = pcall(voce.callback)
                        if not ok then
                            UIManager:show(InfoMessage:new{
                                text = t("koreader.ui.azione_non_riuscita",
                                         { error = tostring(errore) }) })
                        end
                    end
                end,
            }})
        end
    end
    if #pulsanti == 0 then return end
    table.insert(pulsanti, {{
        text = t("koreader.common.close"),
        callback = function() UIManager:close(dialogo) end,
    }})
    dialogo = ButtonDialog:new{ title = titolo, title_align = "left", buttons = pulsanti }
    UIManager:show(dialogo)
    return dialogo
end

--- Il menu del logo: il primo livello del menu del plugin.
function Azioni.menuDelPlugin(vista)
    local kolibre = vista and vista.kolibre
    if not (kolibre and kolibre._vociPrimoLivello) then
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.menu_non_disponibile") })
        return
    end
    local ok, voci = pcall(function() return kolibre:_vociPrimoLivello() end)
    if not ok or type(voci) ~= "table" then
        UIManager:show(InfoMessage:new{ text = t("koreader.ui.menu_non_disponibile") })
        return
    end
    return Azioni.menuDiVoci(voci, t("koreader.menu.title"))
end

--- Le quattro righe della scheda, che fanno da titolo al menu di un libro.
local function schedaDelLibro(vista, voce)
    local m = {}
    if vista.kolibre and vista.kolibre.manifest and voce.path then
        m = vista.kolibre.manifest:findByPath(voce.path) or {}
    end
    return t("koreader.ui.scheda_breve", {
        titolo = voce.titolo or m.title or voce.text or "?",
        autore = voce.autore or m.author or "-",
        biblioteca = m.library or "-",
        pagine = (voce.stima_pagine or m.server_pages)
            and tostring(voce.stima_pagine or m.server_pages)
            or t("koreader.ui.pagine_ignote"),
    })
end

--- Il menu di un libro: la scheda, e le tre cose che si possono fare.
--
-- **L'ordine dei pulsanti non e' casuale.** Le due posizioni prima, perche'
-- sono reversibili: una posizione sbagliata si rimanda. «Elimina» per
-- ultimo, staccato, e con una domanda di conferma che dice **che cosa resta**
-- — il libro nella biblioteca sul server — perche' il dubbio davanti a
-- quella voce e' «lo perdo per sempre?» e la risposta e' no.
function Azioni.perUnLibro(vista, voce)
    if not voce or voce.e_cartella or voce.is_go_up or not voce.path then return end
    local kolibre = vista.kolibre
    if not kolibre then
        -- Senza il plugin dietro non c'e' niente da fare su un libro: si
        -- mostra la scheda e basta, che e' quello che questa pressione
        -- prolungata faceva fino al 16/11/2026.
        UIManager:show(InfoMessage:new{ text = schedaDelLibro(vista, voce) })
        return
    end

    local dialogo
    local function poi()
        -- La riga deve sparire (o cambiare) dopo l'azione: un elenco che
        -- resta identico fa sembrare che il comando non abbia fatto niente.
        pcall(function() if vista.rileggi then vista:rileggi() end end)
    end

    dialogo = ButtonDialog:new{
        title = schedaDelLibro(vista, voce),
        title_align = "left",
        buttons = {
            {{
                text = t("koreader.ui.azione_manda_posizione"),
                callback = function()
                    UIManager:close(dialogo)
                    kolibre:posizioneDiUnLibro(voce.path, "manda")
                end,
            }},
            {{
                text = t("koreader.ui.azione_scarica_posizione"),
                callback = function()
                    UIManager:close(dialogo)
                    kolibre:posizioneDiUnLibro(voce.path, "scarica")
                    poi()
                end,
            }},
            {{
                text = t("koreader.ui.azione_elimina"),
                callback = function()
                    UIManager:close(dialogo)
                    UIManager:show(ConfirmBox:new{
                        text = t("koreader.ui.elimina_conferma", {
                            titolo = voce.titolo or voce.text or "?" }),
                        ok_text = t("koreader.ui.azione_elimina"),
                        ok_callback = function()
                            kolibre:toglieQuestoLibro(voce.path, poi)
                        end,
                    })
                end,
            }},
            {{
                text = t("koreader.common.close"),
                callback = function() UIManager:close(dialogo) end,
            }},
        },
    }
    UIManager:show(dialogo)
    return dialogo
end

return Azioni
