import { useEffect, useMemo, useState } from 'react'
import {
  beginSignIn,
  clearAuthState,
  getAuthUser,
  refreshTokensIfNeeded,
  signOut,
  type AuthUser,
} from './auth'
import { appConfig } from './config'
import { getThingShadow, updateThingShadow } from './shadow-api'

type SessionStatus = 'loading' | 'authenticating' | 'signed_out' | 'signed_in'
type AppProps = {
  initialAuthError?: string
}

const formatJson = (value: unknown): string => JSON.stringify(value, null, 2)

function App({ initialAuthError = '' }: AppProps) {
  const [status, setStatus] = useState<SessionStatus>('loading')
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [shadowJson, setShadowJson] = useState<string>('{}')
  const [isLoadingShadow, setIsLoadingShadow] = useState(false)
  const [isUpdatingShadow, setIsUpdatingShadow] = useState(false)
  const [feedback, setFeedback] = useState<string>('')
  const [error, setError] = useState<string>(initialAuthError)

  const hasConfigErrors = appConfig.errors.length > 0

  const adminEmailMismatch = useMemo(() => {
    if (!appConfig.adminEmail || !authUser?.email) {
      return false
    }
    return authUser.email.toLowerCase() !== appConfig.adminEmail
  }, [authUser?.email])

  useEffect(() => {
    if (hasConfigErrors) {
      setStatus('signed_out')
      return
    }

    const hydrateSession = async () => {
      setFeedback('')
      if (!initialAuthError) {
        setError('')
      }

      try {
        const restoredTokens = await refreshTokensIfNeeded()
        if (!restoredTokens) {
          setStatus('signed_out')
          return
        }

        const user = getAuthUser(restoredTokens)
        setAuthUser(user)
        setError('')
        setStatus('signed_in')
      } catch (caughtError) {
        clearAuthState()
        setStatus('signed_out')
        setError(caughtError instanceof Error ? caughtError.message : 'Authentication failed')
      }
    }

    void hydrateSession()
  }, [hasConfigErrors, initialAuthError])

  useEffect(() => {
    if (status !== 'signed_in') {
      return
    }
    if (!adminEmailMismatch) {
      return
    }

    clearAuthState()
    setStatus('signed_out')
    setError(`Signed-in user is not allowed. Expected: ${appConfig.adminEmail}`)
  }, [adminEmailMismatch, status])

  const withApiToken = async (): Promise<string> => {
    const refreshedTokens = await refreshTokensIfNeeded()
    if (!refreshedTokens) {
      clearAuthState()
      setAuthUser(null)
      setStatus('signed_out')
      throw new Error('Session expired. Sign in again.')
    }

    setAuthUser(getAuthUser(refreshedTokens))
    // The identity pool exchanges the user pool ID token for temporary AWS credentials.
    return refreshedTokens.idToken
  }

  const loadShadow = async (): Promise<void> => {
    setIsLoadingShadow(true)
    setError('')
    setFeedback('')

    try {
      const token = await withApiToken()
      const response = await getThingShadow(token)
      setShadowJson(formatJson(response))
      setFeedback(`Shadow loaded at ${new Date().toLocaleTimeString()}`)
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to load shadow')
    } finally {
      setIsLoadingShadow(false)
    }
  }

  const saveShadow = async (): Promise<void> => {
    setIsUpdatingShadow(true)
    setError('')
    setFeedback('')

    try {
      const parsed = JSON.parse(shadowJson)
      const token = await withApiToken()
      const response = await updateThingShadow(token, parsed)
      setShadowJson(formatJson(response))
      setFeedback(`Shadow updated at ${new Date().toLocaleTimeString()}`)
    } catch (caughtError) {
      if (caughtError instanceof SyntaxError) {
        setError(`JSON parse error: ${caughtError.message}`)
      } else {
        setError(caughtError instanceof Error ? caughtError.message : 'Unable to update shadow')
      }
    } finally {
      setIsUpdatingShadow(false)
    }
  }

  const updateDesiredPower = async (power: boolean): Promise<void> => {
    setIsUpdatingShadow(true)
    setError('')
    setFeedback('')

    try {
      const token = await withApiToken()
      const payload = {
        state: {
          desired: {
            mcu: {
              power,
            },
          },
        },
      }
      const response = await updateThingShadow(token, payload)
      setShadowJson(formatJson(response))
      setFeedback(`desired.mcu.power -> ${power} at ${new Date().toLocaleTimeString()}`)
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to update desired power')
    } finally {
      setIsUpdatingShadow(false)
    }
  }

  if (hasConfigErrors) {
    return (
      <main className="page">
        <section className="card">
          <h1>Txing Shadow Admin</h1>
          <p>App configuration is incomplete.</p>
          <ul className="error-list">
            {appConfig.errors.map((cfgError) => (
              <li key={cfgError}>{cfgError}</li>
            ))}
          </ul>
        </section>
      </main>
    )
  }

  if (status === 'loading' || status === 'authenticating') {
    return (
      <main className="page">
        <section className="card">
          <h1>Txing Shadow Admin</h1>
          <p>{status === 'authenticating' ? 'Finishing sign-in...' : 'Loading session...'}</p>
        </section>
      </main>
    )
  }

  if (status === 'signed_out') {
    return (
      <main className="page">
        <section className="card">
          <h1>Txing Shadow Admin</h1>
          <p>Authentication is required.</p>
          {error && <p className="error">{error}</p>}
          <button type="button" onClick={() => void beginSignIn()} className="primary">
            Sign in
          </button>
        </section>
      </main>
    )
  }

  return (
    <main className="page">
      <section className="card">
        <header className="top-row">
          <div>
            <h1>Txing Shadow Admin</h1>
            <p className="subtitle">
              Thing: <code>{appConfig.thingName}</code>
            </p>
            <p className="subtitle">
              Signed in as <strong>{authUser?.email ?? authUser?.sub ?? 'unknown user'}</strong>
            </p>
          </div>
          <button type="button" onClick={signOut}>
            Sign out
          </button>
        </header>

        <div className="button-row">
          <button type="button" onClick={() => void loadShadow()} disabled={isLoadingShadow}>
            {isLoadingShadow ? 'Loading...' : 'Load Shadow'}
          </button>
          <button type="button" onClick={() => void updateDesiredPower(true)} disabled={isUpdatingShadow}>
            Wake MCU
          </button>
          <button type="button" onClick={() => void updateDesiredPower(false)} disabled={isUpdatingShadow}>
            Sleep MCU
          </button>
          <button type="button" onClick={() => void saveShadow()} disabled={isUpdatingShadow}>
            {isUpdatingShadow ? 'Updating...' : 'Update Shadow'}
          </button>
        </div>

        <label htmlFor="shadow-json" className="editor-label">
          Full shadow JSON
        </label>
        <textarea
          id="shadow-json"
          className="editor"
          value={shadowJson}
          onChange={(event) => setShadowJson(event.target.value)}
          spellCheck={false}
        />

        {feedback && <p className="feedback">{feedback}</p>}
        {error && <p className="error">{error}</p>}
      </section>
    </main>
  )
}

export default App
