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
const shadowPollIntervalMs = 1000
const boardOfflineTimeoutMs = 45000

const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const extractReportedMcu = (shadow: unknown): Record<string, unknown> | null => {
  if (!isRecord(shadow)) {
    return null
  }
  const state = shadow.state
  if (!isRecord(state)) {
    return null
  }
  const reported = state.reported
  if (!isRecord(reported)) {
    return null
  }
  const mcu = reported.mcu
  return isRecord(mcu) ? mcu : null
}

const extractReportedBoard = (shadow: unknown): Record<string, unknown> | null => {
  if (!isRecord(shadow)) {
    return null
  }
  const state = shadow.state
  if (!isRecord(state)) {
    return null
  }
  const reported = state.reported
  if (!isRecord(reported)) {
    return null
  }
  const board = reported.board
  return isRecord(board) ? board : null
}

const extractReportedBoardPower = (shadow: unknown): boolean | null => {
  const board = extractReportedBoard(shadow)
  if (!board) {
    return null
  }
  return typeof board.power === 'boolean' ? board.power : null
}

const extractReportedMcuPower = (shadow: unknown): boolean | null => {
  const mcu = extractReportedMcu(shadow)
  if (!mcu) {
    return null
  }
  return typeof mcu.power === 'boolean' ? mcu.power : null
}

const extractReportedMcuOnline = (shadow: unknown): boolean | null => {
  const mcu = extractReportedMcu(shadow)
  if (!mcu) {
    return null
  }
  if (typeof mcu.online === 'boolean') {
    return mcu.online
  }
  const ble = mcu.ble
  if (!isRecord(ble)) {
    return null
  }
  return typeof ble.online === 'boolean' ? ble.online : null
}

const extractReportedBoardWifiOnline = (shadow: unknown): boolean | null => {
  const board = extractReportedBoard(shadow)
  if (!board) {
    return null
  }
  const wifi = board.wifi
  return isRecord(wifi) && typeof wifi.online === 'boolean' ? wifi.online : null
}

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

  const shadowDocument = useMemo<unknown>(() => {
    try {
      return JSON.parse(shadowJson)
    } catch {
      return null
    }
  }, [shadowJson])

  const reportedMcuPower = useMemo(
    () => extractReportedMcuPower(shadowDocument),
    [shadowDocument],
  )
  const reportedMcuOnline = useMemo(
    () => extractReportedMcuOnline(shadowDocument),
    [shadowDocument],
  )
  const reportedBoardPower = useMemo(
    () => extractReportedBoardPower(shadowDocument),
    [shadowDocument],
  )
  const reportedBoardOnline = useMemo(
    () => extractReportedBoardWifiOnline(shadowDocument),
    [shadowDocument],
  )
  const canWake = reportedMcuPower === false && reportedMcuOnline === true
  const canSleep = reportedMcuPower === true || reportedBoardPower === true || reportedBoardOnline === true

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
        setIsLoadingShadow(true)
        try {
          const shadowResponse = await getThingShadow(restoredTokens.idToken)
          setShadowJson(formatJson(shadowResponse))
          setFeedback(`Shadow loaded at ${new Date().toLocaleTimeString()}`)
        } catch (caughtError) {
          setError(caughtError instanceof Error ? caughtError.message : 'Unable to load shadow')
        } finally {
          setIsLoadingShadow(false)
        }
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

  const loadShadowWithToken = async (
    token: string,
    feedbackMessage = `Shadow loaded at ${new Date().toLocaleTimeString()}`,
  ): Promise<void> => {
    const response = await getThingShadow(token)
    setShadowJson(formatJson(response))
    setFeedback(feedbackMessage)
  }

  const loadShadow = async (): Promise<void> => {
    setIsLoadingShadow(true)
    setError('')
    setFeedback('')

    try {
      const token = await withApiToken()
      await loadShadowWithToken(token)
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to load shadow')
    } finally {
      setIsLoadingShadow(false)
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
      await updateThingShadow(token, payload)
      await loadShadowWithToken(
        token,
        `desired.mcu.power -> ${power} at ${new Date().toLocaleTimeString()}`,
      )
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to update desired power')
    } finally {
      setIsUpdatingShadow(false)
    }
  }

  const requestSleep = async (): Promise<void> => {
    setIsUpdatingShadow(true)
    setError('')
    setFeedback('')

    try {
      const token = await withApiToken()
      await updateThingShadow(token, {
        state: {
          desired: {
            board: {
              power: false,
            },
          },
        },
      })

      setFeedback('Waiting for reported.board.power=false...')

      let boardOfflineShadow: unknown | null = null
      const deadline = Date.now() + boardOfflineTimeoutMs
      while (Date.now() < deadline) {
        const shadowResponse = await getThingShadow(token)
        setShadowJson(formatJson(shadowResponse))
        boardOfflineShadow = shadowResponse
        if (extractReportedBoardPower(shadowResponse) === false) {
          break
        }
        await delay(shadowPollIntervalMs)
      }

      if (extractReportedBoardPower(boardOfflineShadow) !== false) {
        throw new Error('Timed out waiting for reported.board.power=false before sleeping MCU')
      }

      await updateThingShadow(token, {
        state: {
          desired: {
            board: {
              power: null,
            },
          },
        },
      })

      await updateThingShadow(token, {
        state: {
          desired: {
            mcu: {
              power: false,
            },
          },
        },
      })
      await loadShadowWithToken(
        token,
        `Sleep requested at ${new Date().toLocaleTimeString()}`,
      )
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to request sleep')
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
          <button
            type="button"
            onClick={() => void loadShadow()}
            disabled={isLoadingShadow || isUpdatingShadow}
          >
            {isLoadingShadow ? 'Loading...' : 'Load Shadow'}
          </button>
          <button
            type="button"
            onClick={() => void updateDesiredPower(true)}
            disabled={isLoadingShadow || isUpdatingShadow || !canWake}
          >
            Wake
          </button>
          <button
            type="button"
            onClick={() => void requestSleep()}
            disabled={isLoadingShadow || isUpdatingShadow || !canSleep}
          >
            Sleep
          </button>
        </div>

        <label htmlFor="shadow-json" className="editor-label">
          Current shadow JSON
        </label>
        <textarea
          id="shadow-json"
          className="editor"
          value={shadowJson}
          readOnly
          spellCheck={false}
        />

        {feedback && <p className="feedback">{feedback}</p>}
        {error && <p className="error">{error}</p>}
      </section>
    </main>
  )
}

export default App
