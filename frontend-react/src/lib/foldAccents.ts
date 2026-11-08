// Confronto di testo che ignora gli accenti.
//
// Cercando "Emile Zola" si vuole trovare "Émile Zola", e cercando "Garcia"
// si vuole trovare "García": in una biblioteca con autori francesi,
// spagnoli, portoghesi e tedeschi digitare l'accento giusto e' un ostacolo,
// non una precisazione. Vale per titoli e autori, che sono i due campi su
// cui si cerca per davvero.
//
// NFD separa la lettera dal suo segno diacritico ("é" -> "e" + accento), poi
// si buttano via i segni. E' lo stesso trucco gia' usato da authorInitial
// per mettere "Émile" sotto la E invece che sotto #, e dall'indice full-text
// lato server (`unicode61 remove_diacritics 2`), quindi le tre ricerche di
// Kolibre ora concordano.
//
// Non tocca le lettere che NON sono accenti ma caratteri a se': la "ø"
// danese e la "ł" polacca restano quello che sono, perche' in NFD non si
// scompongono. Toglierle richiederebbe una tabella di equivalenze per
// lingua, che e' un altro mestiere.
export function foldAccents(s: string): string {
  return s.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
}

/** `ago` contenuto in `pagliaio`, ignorando accenti e maiuscole. */
export function containsFolded(pagliaio: string, ago: string): boolean {
  return foldAccents(pagliaio).includes(foldAccents(ago))
}
