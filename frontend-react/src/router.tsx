import { createBrowserRouter } from 'react-router-dom'
import { lazyWithReload } from '@/lib/lazyWithReload'
import { Layout } from '@/components/Layout'
// Non lazy come le pagine qui sotto: è solo un redirect che apre la modale
// Impostazioni (vedi SettingsRoute.tsx), non vale una chunk a parte.
import { SettingsRoute } from '@/pages/Settings/SettingsRoute'

// Ogni pagina è la sua chunk: al primo avvio il browser scarica solo
// Layout + la pagina su cui si atterra, non l'intero bundle (Statistiche
// con chart.js, la libreria con la tabella virtualizzata, ecc.) — vedi
// Suspense in Layout.tsx per il fallback di caricamento.
// La pagina che apre un indirizzo condivisibile (`/k/...`): non si guarda,
// si attraversa — chiede al server dove porta e ci va.
const ApriIndirizzo = lazyWithReload(() => import('@/pages/ApriIndirizzo').then((m) => ({ default: m.ApriIndirizzo })))
const LibraryPage = lazyWithReload(() => import('@/pages/Library/LibraryPage').then((m) => ({ default: m.LibraryPage })))
const BookDetailPage = lazyWithReload(() => import('@/pages/BookDetail/BookDetailPage').then((m) => ({ default: m.BookDetailPage })))
const AuthorsPage = lazyWithReload(() => import('@/pages/Authors/AuthorsPage').then((m) => ({ default: m.AuthorsPage })))
const AuthorDetailPage = lazyWithReload(() => import('@/pages/Authors/AuthorDetailPage').then((m) => ({ default: m.AuthorDetailPage })))
const SeriesPage = lazyWithReload(() => import('@/pages/Series/SeriesPage').then((m) => ({ default: m.SeriesPage })))
const EntitiesPage = lazyWithReload(() => import('@/pages/Entities/EntitiesPage').then((m) => ({ default: m.EntitiesPage })))
const AnnotationsPage = lazyWithReload(() => import('@/pages/Annotations/AnnotationsPage').then((m) => ({ default: m.AnnotationsPage })))
const VocabularyPage = lazyWithReload(() => import('@/pages/Vocabulary/VocabularyPage').then((m) => ({ default: m.VocabularyPage })))
const StatisticsPage = lazyWithReload(() => import('@/pages/Statistics/StatisticsPage').then((m) => ({ default: m.StatisticsPage })))
const ChartBuilderPage = lazyWithReload(() => import('@/pages/Statistics/ChartBuilderPage').then((m) => ({ default: m.ChartBuilderPage })))
const InterventionsPage = lazyWithReload(() => import('@/pages/Interventions/InterventionsPage').then((m) => ({ default: m.InterventionsPage })))
const ImportPage = lazyWithReload(() => import('@/pages/Ingest/ImportPage').then((m) => ({ default: m.ImportPage })))
const AppuntiPage = lazyWithReload(() => import('@/pages/Appunti/AppuntiPage').then((m) => ({ default: m.AppuntiPage })))
const LibroDegliAppunti = lazyWithReload(() => import('@/pages/Appunti/LibroDegliAppunti').then((m) => ({ default: m.LibroDegliAppunti })))
const DevicesPage = lazyWithReload(() => import('@/pages/Devices/DevicesPage').then((m) => ({ default: m.DevicesPage })))
const DeviceDetailPage = lazyWithReload(() => import('@/pages/Devices/DeviceDetailPage').then((m) => ({ default: m.DeviceDetailPage })))

// Non con `lazyWithReload` come le altre: è la pagina che si mostra quando
// qualcosa non si trova, e farla dipendere da un file da scaricare vuol dire
// che con la rete malferma non appare nemmeno lei.
import { IndirizzoSbagliato } from '@/pages/IndirizzoSbagliato'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <LibraryPage /> },
      // Gli indirizzi condivisibili. La rotta sta DENTRO il guscio
      // dell'applicazione, e quindi dietro l'accesso, di proposito: un link
      // del genere nasce per essere aperto da un browser che magari non ha
      // una sessione — un altro computer, o sette giorni dopo — e l'ordine
      // giusto è prima entrare, poi andare a cercare dove porta.
      { path: 'k/*', element: <ApriIndirizzo /> },
      { path: 'autori', element: <AuthorsPage /> },
      { path: 'autori/:name', element: <AuthorDetailPage /> },
      { path: 'serie', element: <SeriesPage /> },
      { path: 'entita', element: <EntitiesPage /> },
      { path: 'libri/:id', element: <BookDetailPage /> },
      { path: 'annotazioni', element: <AnnotationsPage /> },
      { path: 'vocabolario', element: <VocabularyPage /> },
      { path: 'appunti', element: <AppuntiPage /> },
      // La biblioteca e l'id del libro stanno nella query e non nel
      // percorso: il nome di una biblioteca e' il nome vero di una
      // cartella, e in un percorso andrebbe codificato due volte.
      { path: 'appunti/libro', element: <LibroDegliAppunti /> },
      { path: 'dispositivi', element: <DevicesPage /> },
      { path: 'dispositivi/:id', element: <DeviceDetailPage /> },
      { path: 'statistiche', element: <StatisticsPage /> },
      { path: 'statistiche/grafici', element: <ChartBuilderPage /> },
      { path: 'interventi', element: <InterventionsPage /> },
      { path: 'importa', element: <ImportPage /> },
      { path: 'impostazioni', element: <SettingsRoute /> },
      // Ultima, e dentro il Layout di proposito: chi arriva su un indirizzo
      // che non esiste deve restare DENTRO l'applicazione — con la barra
      // laterale, la ricerca e tutto il resto — invece di trovarsi in una
      // pagina nuda da cui l'unica via è il tasto indietro.
      { path: '*', element: <IndirizzoSbagliato /> },
    ],
  },
])
