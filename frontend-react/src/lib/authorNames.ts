import { containsFolded } from './foldAccents'

// Porting di splitAuthorNames da frontend/src/App.vue: il backend unisce
// autori multipli con " & " (semantica Calibre reale, vedi
// backend/app/calibre/functions.py::authors_to_string), con un "&" letterale
// dentro un nome escapato come "&&". Niente split su virgola — "Rossi,
// Mario" è UN autore in forma "cognome, nome".
const AMPERSAND_ESCAPE_PLACEHOLDER = '￿'

export function splitAuthorNames(author: string | null | undefined): string[] {
  if (!author) return []
  const escaped = author.replace(/&&/g, AMPERSAND_ESCAPE_PLACEHOLDER)
  return escaped
    .split('&')
    .map((name) => name.replace(new RegExp(AMPERSAND_ESCAPE_PLACEHOLDER, 'g'), '&').trim())
    .filter(Boolean)
}

// Quante proposte al massimo finiscono nel documento quando si scrive un
// autore. Senza un limite ci finiscono TUTTI: su una biblioteca con
// ventimila autori sono ventimila elementi <option> creati ogni volta che
// si apre la finestra, per una tendina che ne mostra una manciata.
const MAX_PROPOSTE = 50

// Le proposte per un campo "Autore", a partire da quello che si sta
// scrivendo. Due casi:
//
// - un autore solo: si propongono i nomi che contengono quanto digitato,
//   ignorando accenti e maiuscole (scrivendo "emile" deve uscire "Émile
//   Zola", come ovunque altrove in Kolibre);
// - più autori: dopo una "&" il valore del campo non corrisponde più a
//   nessun nome, e una tendina normale smetterebbe di aiutare proprio nel
//   caso in cui scrivere a mano è più noioso. Si propone allora il valore
//   già scritto PIÙ il nome, così "Mario Rossi & fri" propone "Mario Rossi &
//   Luigi Bianchi".
export function proposteAutore(digitato: string, nomi: string[]): string[] {
  const taglio = digitato.lastIndexOf('&')
  const prefisso = taglio === -1 ? '' : digitato.slice(0, taglio + 1)
  const parziale = (taglio === -1 ? digitato : digitato.slice(taglio + 1)).trim()

  const proposte: string[] = []
  for (const nome of nomi) {
    if (parziale && !containsFolded(nome, parziale)) continue
    proposte.push(prefisso ? `${prefisso.trimEnd()} ${nome}` : nome)
    if (proposte.length >= MAX_PROPOSTE) break
  }
  return proposte
}
