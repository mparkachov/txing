import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { clearAuthState, processAuthCallbackIfPresent } from './auth'

let initialAuthError = ''

try {
  await processAuthCallbackIfPresent()
} catch (caughtError) {
  clearAuthState()
  initialAuthError =
    caughtError instanceof Error ? caughtError.message : 'Authentication failed'
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App initialAuthError={initialAuthError} />
  </StrictMode>,
)
