// `marks-pane` non porta i suoi tipi. Si dichiara solo quello che serve per
// innestare l'unione dei riquadri (vedi pages/Reader/UnisciRiquadri.ts): non
// e' la sua interfaccia completa, ed e' giusto che non lo sia.
declare module 'marks-pane' {
  interface RiquadroDisegnato {
    left: number
    top: number
    width: number
    height: number
  }
  export class Highlight {
    range: Range
    filteredRanges(): RiquadroDisegnato[]
  }
  export class Underline extends Highlight {}
}
