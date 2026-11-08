--[[--
Quali patch vanno aggiornate — e, soprattutto, quali non si devono
proporre.

**Il problema.** Una patch installata e poi modificata sul server resta
quella vecchia finche' qualcuno non apre il menu' e se ne accorge. Il menu'
lo dice («— da aggiornare»), ma bisogna andarci: e nessuno apre un menu' per
controllare una cosa che non sa di dover controllare. Quindi lo chiede il
plugin da se', nella sincronizzazione, come fa gia' per la propria versione.

**La regola che conta e' quella che NON propone niente.** Si offre di
aggiornare solo cio' che il dispositivo ha **gia'**: una patch mai
installata non e' un aggiornamento mancante, e' una proposta non richiesta —
e un avviso che non si e' chiesto si impara a ignorare, portandosi dietro
anche quelli che servivano (e' la stessa lezione del promemoria del backup,
che segnalava un backup da fare anche quando il backup era stato fatto).

E non si propone nulla nemmeno quando KOReader ha tirato il suo interruttore
generale delle patch: in quello stato nemmeno una patch installata viene
eseguita, quindi sostituirla non cambierebbe niente — chiederlo sarebbe
chiedere di fare una cosa inutile.

Sta in un modulo suo, e non dentro `main.lua`, perche' cosi' si puo'
provare senza KOReader e senza un server: la scelta e' una funzione pura di
un elenco e di uno stato (vedi
la prova «patch_da_aggiornare»).
--]]--

local KolibrePatch = {}

-- Le patch da proporre, nell'ordine in cui il server le ha elencate.
--
-- `elenco` e' quello che il server offre: voci con almeno `file` e `nome`.
-- `stato_di` e' una funzione `patch -> "assente" | "uguale" | "diversa"`
-- (nel plugin e' `_statoDellaPatch`, che confronta le impronte).
-- `disattivate` dice se KOReader ha l'interruttore generale tirato.
--
-- Torna sempre una tabella, anche vuota: chi la usa non deve distinguere
-- «niente da fare» da «non lo so», perche' in entrambi i casi la cosa
-- giusta da fare e' tacere.
function KolibrePatch.daAggiornare(elenco, stato_di, disattivate)
    if disattivate then return {} end
    if type(elenco) ~= "table" then return {} end
    if type(stato_di) ~= "function" then return {} end

    local fuori = {}
    for _idx, patch in ipairs(elenco) do
        if type(patch) == "table" and type(patch.file) == "string" and patch.file ~= "" then
            -- Senza impronta dal server non si puo' dire che sia diversa, e
            -- `_statoDellaPatch` torna infatti "uguale": una patch che il
            -- server non sa descrivere non si tocca.
            if stato_di(patch) == "diversa" then
                table.insert(fuori, patch)
            end
        end
    end
    return fuori
end

return KolibrePatch
