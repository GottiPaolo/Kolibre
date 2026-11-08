--[[--
Lo stato del momento «avvio», e cosa gli succede a ogni risveglio.

**Da zero.** Il plugin ha quattro momenti in cui lavora da sé — avvio,
apertura di un libro, chiusura, spegnimento — e «avvio» copre anche il
**risveglio**, perché per un lettore che si sospende invece di spegnersi
sono la stessa cosa. Al momento «avvio» si arriva da tre strade:

  1. `init()`, una volta per processo;
  2. `onResume`, a ogni risveglio;
  3. `onNetworkConnected`, quando la rete arriva dopo — che è lo stesso
     momento visto da un'altra parte: un lettore che tiene il WiFi spento
     fra due sincronizzazioni si sveglia senza rete.

E c'è un contatore di tentativi, perché il server può non essere ancora
raggiungibile nei primi secondi.

**Perché questo modulo esiste** (08/11/2026). Quello stato stava in tre
variabili dentro `main.lua`, e il risultato era che **dopo la prima
sincronizzazione d'avvio riuscita il lettore non ne faceva più nessuna fino
a un riavvio di KOReader**. Misurato sul Kindle di Paolo: avvio a freddo
08/11 00:18 → due `auto_avvio`; risveglio alle 09:27 → nessuna, e lui che
preme a mano. Le sue parole: «non mi pare partire, semplicemente non la vedo
avviare».

Le due cause, entrambe di stato:

  * **`_avvio_concluso` non si azzerava mai.** Era una variabile del modulo,
    messa a `true` al primo successo, e `onNetworkConnected` era protetta da
    `if not _avvio_concluso`. Su un Kindle KOReader non si riavvia: si
    sospende. «La vita del processo» sono settimane, e per tutte la strada
    numero 3 era morta. Al risveglio la numero 2 girava una volta sola,
    senza ritentativi, nell'istante in cui il WiFi non è ancora su.
  * **l'antirimbalzo del sync completo stava su `self`.** Di questo plugin
    esistono DUE istanze nello stesso processo, una nel gestore file e una
    nel lettore: un contatore su `self` non può fermare un doppione fra
    istanze diverse. Le due `auto_avvio` di quella notte distavano 39
    secondi, con un antirimbalzo di 60.

**Perché in un modulo suo.** Per le stesse due ragioni di
`kolibre_percorsi`: così la regola si **prova** senza KOReader — niente
UIManager, niente rete, niente `self` — e così lo stato è davvero uno solo,
perché un modulo Lua si carica una volta e le due istanze del plugin vedono
la stessa tabella. Era già la ragione scritta a mano in `main.lua`; qui
diventa la struttura.
--]]--

local KolibreAvvio = {}

--- Uno stato nuovo. `nuovo()` serve alle prove; il processo ne usa uno solo.
function KolibreAvvio.nuovo()
    return {
        -- il momento «avvio» di QUESTO risveglio è andato a buon fine
        concluso = false,
        -- c'è già un tentativo in coda: senza questo, due istanze che
        -- ricevono lo stesso risveglio programmano due catene di ritentativi
        in_coda = false,
        tentativi = 0,
        -- quando è partito l'ultimo sync completo (os.time()), per
        -- l'antirimbalzo
        ultimo_sync = 0,
        -- si è già detto, in questa sequenza di risvegli senza rete, che si
        -- rinuncia: vedi `deveAnnunciareRinuncia`
        rinuncia_annunciata = false,
    }
end

--- Lo stato del processo. Uno, condiviso da tutte le istanze del plugin.
KolibreAvvio.condiviso = KolibreAvvio.nuovo()

--- Si può mettere in coda un tentativo del momento «avvio»?
--
-- No se è già concluso (non c'è niente da fare) e no se ce n'è già uno in
-- coda (lo farebbe due volte).
function KolibreAvvio.puoProgrammare(stato)
    if type(stato) ~= "table" then return false end
    return not stato.concluso and not stato.in_coda
end

--- La rete che arriva deve fare il momento «avvio» adesso?
--
-- Solo se questo risveglio non l'ha ancora fatto: a rete già su l'ha fatto
-- `init`/`onResume`, e rifarlo vorrebbe dire due sincronizzazioni per lo
-- stesso risveglio.
function KolibreAvvio.reteDeveProvare(stato)
    if type(stato) ~= "table" then return false end
    return not stato.concluso
end

--- Un tentativo parte adesso.
function KolibreAvvio.tentativoPartito(stato)
    stato.in_coda = false
    stato.tentativi = (stato.tentativi or 0) + 1
end

--- Un tentativo è stato messo in coda.
function KolibreAvvio.tentativoInCoda(stato)
    stato.in_coda = true
end

--- Il momento «avvio» è riuscito: non si riprova più, fino alla prossima
--- sospensione.
function KolibreAvvio.riuscito(stato)
    stato.concluso = true
    stato.in_coda = false
    -- La rete è tornata: se dovesse sparire di nuovo, l'avviso si rifà. È
    -- questo che rende «una volta» una volta **per ogni volta che si perde
    -- la rete**, e non una volta per sempre.
    stato.rinuncia_annunciata = false
end

--- Si deve DIRE che si rinuncia, o lo si è già detto?
---
--- **La regola, scelta l'08/11/2026.** Paolo: «mi piace l'idea di tenere
--- solo l'avviso di rinuncia». Uno solo, però: un lettore lasciato fuori
--- casa si risveglia dieci volte e rinuncia dieci volte, e dieci avvisi
--- identici sono peggio di nessuno — su un e-ink sono anche dieci ridisegni.
---
--- Quindi: **si avvisa una volta per ogni volta che si perde la rete.** La
--- bandierina si alza quando si avvisa e si abbassa quando una
--- sincronizzazione riesce (`riuscito`), NON quando si sospende: la
--- sospensione riapre il momento d'avvio ma non cambia il fatto che la rete
--- non c'era, ed è esattamente il caso dei risvegli uno dopo l'altro.
---
--- Vive nel modulo, quindi dura quanto il processo: un riavvio di KOReader
--- è un gesto esplicito e lì l'avviso può ricomparire.
function KolibreAvvio.deveAnnunciareRinuncia(stato)
    if type(stato) ~= "table" then return false end
    return not stato.rinuncia_annunciata
end

function KolibreAvvio.rinunciaAnnunciata(stato)
    stato.rinuncia_annunciata = true
end

--- I tentativi sono finiti: si smette, ma il prossimo risveglio riproverà.
function KolibreAvvio.rinuncia(stato)
    stato.in_coda = false
end

--- Il lettore si sospende: **il prossimo risveglio è un avvio nuovo.**
---
--- È la riga che mancava, ed è tutta la correzione dell'08/11/2026.
function KolibreAvvio.sospeso(stato)
    stato.concluso = false
    stato.in_coda = false
    stato.tentativi = 0
end

--- Si può fare un sync completo adesso, o se n'è fatto uno troppo poco fa?
---
--- L'antirimbalzo serve perché le consegne dei libri sono una coda del
--- dispositivo, non di un documento: non ha senso richiederla più di una
--- volta al minuto anche se avvio, apertura e risveglio scattano a pochi
--- secondi l'uno dall'altro. Sta qui, e non su `self`, perché deve valere
--- fra le due istanze del plugin.
function KolibreAvvio.puoSincronizzare(stato, adesso, antirimbalzo)
    if type(stato) ~= "table" then return false end
    return (adesso - (stato.ultimo_sync or 0)) >= antirimbalzo
end

--- Un sync completo è partito adesso.
function KolibreAvvio.sincronizzato(stato, adesso)
    stato.ultimo_sync = adesso
end

return KolibreAvvio
