import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { EmailGate } from './components/EmailGate'
import './shell.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <EmailGate>
      <App />
    </EmailGate>
  </StrictMode>,
)
