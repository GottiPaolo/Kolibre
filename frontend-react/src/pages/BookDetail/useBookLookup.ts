import { useMemo } from 'react'
import { useLocation } from 'react-router-dom'
import { useQueries } from '@tanstack/react-query'
import { useLibraries, booksQueryOptions, useBooks } from '@/lib/queries'
import { compareBooks } from '@/pages/Library/sort'

interface BookDetailLocationState {
  libraryFolder?: string
}

// Non esiste un GET singolo-libro-per-id nel backend (verificato) — quando
// si arriva qui da un click dentro l'app passiamo la cartella libreria via
// stato di navigazione (percorso rapido); se manca (link diretto, reload
// pagina) proviamo ogni libreria finché non troviamo l'id, riusando la
// stessa queryKey/queryFn di useBooks così la cache è condivisa, non
// duplicata.
export function useBookLookup(bookId: number) {
  const location = useLocation()
  const stateFolder = (location.state as BookDetailLocationState | null)?.libraryFolder

  const { data: libraries } = useLibraries()

  const fallbackQueries = useQueries({
    queries: (stateFolder ? [] : libraries ?? []).map((lib) => booksQueryOptions(lib.folder_name)),
  })

  const resolvedFolder = useMemo(() => {
    if (stateFolder) return stateFolder
    if (!libraries) return undefined
    for (let i = 0; i < libraries.length; i++) {
      const books = fallbackQueries[i]?.data
      if (books?.some((b) => b.id === bookId)) return libraries[i].folder_name
    }
    return undefined
  }, [stateFolder, libraries, fallbackQueries, bookId])

  const isSearchingFallback = !stateFolder && !resolvedFolder && (!libraries || fallbackQueries.some((q) => q.isLoading))

  const booksQuery = useBooks(resolvedFolder)
  const books = booksQuery.data ?? []
  const book = books.find((b) => b.id === bookId) ?? null

  // Stesso ordinamento di default della Libreria (data di aggiunta,
  // discendente) — il prev/next qui non ha visibilità sul filtro/ordinamento
  // che l'utente aveva eventualmente impostato sulla pagina Libreria: è una
  // semplificazione deliberata, la navigazione è sempre sull'elenco
  // completo della libreria d'origine del libro.
  const orderedBooks = useMemo(() => {
    const data = booksQuery.data ?? []
    return [...data].sort((a, b) => compareBooks(a, b, [{ key: 'date_added', order: 'desc' }]))
  }, [booksQuery.data])
  const index = orderedBooks.findIndex((b) => b.id === bookId)

  return {
    book,
    libraryFolder: resolvedFolder,
    isLoading: isSearchingFallback || (!!resolvedFolder && booksQuery.isLoading),
    notFound: !isSearchingFallback && !!resolvedFolder && !book,
    hasPrev: index > 0,
    hasNext: index !== -1 && index < orderedBooks.length - 1,
    prevId: index > 0 ? orderedBooks[index - 1].id : null,
    nextId: index !== -1 && index < orderedBooks.length - 1 ? orderedBooks[index + 1].id : null,
  }
}
