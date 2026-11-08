// Le voci della barra laterale che in questo momento non hanno senso.
//
// **Perché non è il costruttore della barra.** In Impostazioni ▸ Aspetto si
// decide quali voci si vogliono: una voce assente da quell'elenco è una
// scelta, e resta. Qui è un'altra cosa — la voce c'è ed è voluta, ma oggi
// non porta da nessuna parte, e mostrarla sarebbe una porta su una stanza
// vuota.
//
// Oggi riguarda **Appunti**: la pagina esiste perché un client (il plugin
// Obsidian) racconta cosa tiene nel vault, e se nessun client ha mai
// raccontato niente la pagina non ha nulla da dire. Paolo ha chiesto di non
// mostrarla affatto in quel caso, come Dispositivi non ha senso per chi non
// ha lettori.
//
// **La domanda dev'essere leggera**, perché la fa la barra a ogni pagina che
// si apre: `/appunti/cliente` legge una riga, mentre `/appunti/stato`
// esporta le note, le raggruppa e ne calcola le impronte. Sono due rotte
// separate per questo.
//
// Nel dubbio si mostra: finché la risposta non è arrivata, o se la domanda
// fallisce, la voce resta al suo posto. Nascondere una pagina per un errore
// di rete sarebbe peggio che mostrarne una vuota.
//
// **E una voce che hai messo tu non si nasconde mai.** Il 06/11/2026 è
// successo esattamente questo: «Appunti» aggiunta a mano da Impostazioni ▸
// Aspetto, e invisibile — per un difetto del server, ma il risultato per chi
// guarda è un programma che non dà ascolto. L'automatismo serve a non
// proporre una stanza vuota, non a chiudere una porta aperta da te.
import { useQuery } from '@tanstack/react-query'
import { fetchClienteDegliAppunti } from './appuntiActions'
import { ALL_PAGE_IDS, type SidebarPageId } from './sidebarLayout'
import { vociDaNascondere, vociScelteAMano } from './vociDellaBarra'

export function useVociNascoste(): Set<SidebarPageId> {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['appunti', 'cliente'],
    queryFn: fetchClienteDegliAppunti,
    // Un client nuovo non compare da un minuto all'altro: si installa il
    // plugin e si preme il comando. Mezz'ora di validità risparmia una
    // domanda per ogni cambio di pagina.
    staleTime: 30 * 60 * 1000,
    retry: false,
  })
  return vociDaNascondere(
    { nessunClient: data == null, inAttesa: isLoading, fallita: isError },
    vociScelteAMano(ALL_PAGE_IDS)
  )
}
