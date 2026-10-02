import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { leggiLingua, ProviderLingua } from './lib/i18n'

// `lang` sul documento prima di qualunque disegno: lo leggono i lettori di
// schermo per scegliere la pronuncia e il browser per la sillabazione, e
// impostarlo dopo il primo render vorrebbe dire leggere la prima schermata
// con l'accento sbagliato.
document.documentElement.lang = leggiLingua()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ProviderLingua>
      <App />
    </ProviderLingua>
  </StrictMode>,
)
