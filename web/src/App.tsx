import { useEffect, useEffectEvent, useMemo, useRef, useState } from 'react'
import {
  beginSignIn,
  clearAuthState,
  getAuthUser,
  refreshTokensIfNeeded,
  signOut,
  type AuthUser,
} from './auth'
import {
  extractReportedBoardPower,
  extractReportedBoardVideo,
  extractReportedBoardWifiOnline,
  extractReportedMcuBatteryMv,
  extractReportedMcuBleOnline,
  extractReportedMcuOnline,
  extractReportedMcuPower,
  extractReportedRedcon,
} from './app-model'
import { appConfig } from './config'
import DebugPanel from './DebugPanel'
import { createShadowSession, type ShadowConnectionState, type ShadowSession } from './shadow-api'
import TxingPanel from './TxingPanel'

type SessionStatus = 'loading' | 'authenticating' | 'signed_out' | 'signed_in'
type AppProps = {
  initialAuthError?: string
}
type TxingSwitchTarget = 'on' | 'off' | null
type ShadowSnapshotView = {
  json: string
  updatedAtMs: number
}

const formatJson = (value: unknown): string => JSON.stringify(value, null, 2)
const boardOfflineTimeoutMs = 45_000

const createShadowSnapshotView = (shadow: unknown): ShadowSnapshotView => ({
  json: formatJson(shadow),
  updatedAtMs: Date.now(),
})

function App({ initialAuthError = '' }: AppProps) {
  const [status, setStatus] = useState<SessionStatus>('loading')
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [shadowJson, setShadowJson] = useState<string>('{}')
  const [lastShadowUpdateAtMs, setLastShadowUpdateAtMs] = useState<number | null>(null)
  const [isLoadingShadow, setIsLoadingShadow] = useState(false)
  const [isUpdatingShadow, setIsUpdatingShadow] = useState(false)
  const [isDebugEnabled, setIsDebugEnabled] = useState(false)
  const [isBoardVideoExpanded, setIsBoardVideoExpanded] = useState(false)
  const [txingSwitchTarget, setTxingSwitchTarget] = useState<TxingSwitchTarget>(null)
  const [feedback, setFeedback] = useState<string>('')
  const [error, setError] = useState<string>(initialAuthError)
  const [shadowConnectionState, setShadowConnectionState] =
    useState<ShadowConnectionState>('idle')
  const shadowSessionRef = useRef<ShadowSession | null>(null)

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
  const reportedMcuBleOnline = useMemo(
    () => extractReportedMcuBleOnline(shadowDocument),
    [shadowDocument],
  )
  const reportedMcuBatteryMv = useMemo(
    () => extractReportedMcuBatteryMv(shadowDocument),
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
  const reportedBoardVideo = useMemo(
    () => extractReportedBoardVideo(shadowDocument),
    [shadowDocument],
  )
  const reportedRedcon = useMemo(
    () => extractReportedRedcon(shadowDocument),
    [shadowDocument],
  )

  const boardOnline = reportedBoardOnline === true
  const canWake = reportedMcuPower === false && reportedMcuOnline === true
  const canSleep = reportedMcuPower === true || reportedBoardPower === true || reportedBoardOnline === true
  const isShadowConnected = shadowConnectionState === 'connected'
  const txingSwitchChecked =
    txingSwitchTarget === 'on' ? true : txingSwitchTarget === 'off' ? false : boardOnline
  const isTxingSwitchPending = txingSwitchTarget !== null
  const canToggleTxingSwitch = (txingSwitchChecked ? canSleep : canWake) && isShadowConnected
  const canLoadShadow = !isLoadingShadow && isShadowConnected
  const isTxingSwitchDisabled =
    isLoadingShadow || isUpdatingShadow || isTxingSwitchPending || !canToggleTxingSwitch
  const boardVideoReady =
    reportedBoardVideo.transport === 'aws-webrtc' &&
    reportedBoardVideo.ready &&
    reportedBoardVideo.status === 'ready' &&
    reportedBoardVideo.channelName !== null
  const boardVideoReachable =
    txingSwitchTarget !== 'off' && boardOnline && reportedBoardPower !== false
  const canUseBoardVideo = boardVideoReachable && boardVideoReady

  const applyShadowSnapshot = useEffectEvent((shadow: unknown, feedbackMessage?: string): void => {
    const snapshotView = createShadowSnapshotView(shadow)
    setShadowJson(snapshotView.json)
    setLastShadowUpdateAtMs(snapshotView.updatedAtMs)
    if (feedbackMessage) {
      setFeedback(feedbackMessage)
    }
  })

  const resolveSessionIdToken = useEffectEvent(async (): Promise<string> => {
    const refreshedTokens = await refreshTokensIfNeeded()
    if (!refreshedTokens) {
      clearAuthState()
      setAuthUser(null)
      setStatus('signed_out')
      throw new Error('Session expired. Sign in again.')
    }

    setAuthUser(getAuthUser(refreshedTokens))
    return refreshedTokens.idToken
  })

  const getShadowSession = (): ShadowSession => {
    const shadowSession = shadowSessionRef.current
    if (!shadowSession || !isShadowConnected) {
      throw new Error('Shadow connection is not ready')
    }
    return shadowSession
  }

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

        setAuthUser(getAuthUser(restoredTokens))
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

  useEffect(() => {
    if (status !== 'signed_in' || adminEmailMismatch) {
      shadowSessionRef.current?.close()
      shadowSessionRef.current = null
      setShadowConnectionState('idle')
      setIsLoadingShadow(false)
      return
    }

    let cancelled = false
    const shadowSession = createShadowSession({
      thingName: appConfig.thingName,
      iotDataEndpoint: appConfig.iotDataEndpoint,
      awsRegion: appConfig.awsRegion,
      resolveIdToken: resolveSessionIdToken,
      onShadowDocument: (shadow) => {
        if (cancelled) {
          return
        }
        applyShadowSnapshot(shadow)
        setIsLoadingShadow(false)
        setError('')
      },
      onConnectionStateChange: (nextState) => {
        if (!cancelled) {
          setShadowConnectionState(nextState)
        }
      },
      onError: (message) => {
        if (!cancelled) {
          setError(message)
        }
      },
    })

    shadowSessionRef.current = shadowSession
    setIsLoadingShadow(true)
    setShadowConnectionState('connecting')
    setError('')
    setFeedback('')

    void shadowSession.start().catch((caughtError) => {
      if (cancelled) {
        return
      }
      setIsLoadingShadow(false)
      setError(
        caughtError instanceof Error ? caughtError.message : 'Unable to open Thing Shadow session',
      )
    })

    return () => {
      cancelled = true
      if (shadowSessionRef.current === shadowSession) {
        shadowSessionRef.current = null
      }
      shadowSession.close()
    }
  }, [adminEmailMismatch, status])

  useEffect(() => {
    if (txingSwitchTarget === 'on' && boardOnline) {
      setTxingSwitchTarget(null)
      return
    }
    if (txingSwitchTarget === 'off' && reportedBoardOnline === false) {
      setTxingSwitchTarget(null)
    }
  }, [boardOnline, reportedBoardOnline, txingSwitchTarget])

  useEffect(() => {
    if (!canUseBoardVideo && isBoardVideoExpanded) {
      setIsBoardVideoExpanded(false)
    }
  }, [canUseBoardVideo, isBoardVideoExpanded])

  const loadShadow = async (): Promise<void> => {
    setIsLoadingShadow(true)
    setError('')
    setFeedback('')

    try {
      const shadowSession = getShadowSession()
      const shadowResponse = await shadowSession.requestSnapshot()
      applyShadowSnapshot(shadowResponse)
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to load shadow')
    } finally {
      setIsLoadingShadow(false)
    }
  }

  const updateDesiredPower = async (power: boolean): Promise<boolean> => {
    setIsUpdatingShadow(true)
    setError('')
    setFeedback('')

    try {
      const shadowSession = getShadowSession()
      const shadowResponse = await shadowSession.updateShadow({
        state: {
          desired: {
            mcu: {
              power,
            },
          },
        },
      })
      applyShadowSnapshot(
        shadowResponse,
        `desired.mcu.power -> ${power} at ${new Date().toLocaleTimeString()}`,
      )
      return true
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to update desired power')
      return false
    } finally {
      setIsUpdatingShadow(false)
    }
  }

  const requestSleep = async (): Promise<boolean> => {
    setIsUpdatingShadow(true)
    setError('')
    setFeedback('')

    try {
      const shadowSession = getShadowSession()
      await shadowSession.updateShadow({
        state: {
          desired: {
            board: {
              power: false,
            },
          },
        },
      })

      setFeedback('Waiting for reported.board.power=false...')

      await shadowSession.waitForSnapshot(
        (shadow) => extractReportedBoardPower(shadow) === false,
        boardOfflineTimeoutMs,
      )

      const boardPowerClearedShadow = await shadowSession.updateShadow({
        state: {
          desired: {
            board: {
              power: null,
            },
          },
        },
      })
      applyShadowSnapshot(boardPowerClearedShadow)

      const mcuPowerUpdatedShadow = await shadowSession.updateShadow({
        state: {
          desired: {
            mcu: {
              power: false,
            },
          },
        },
      })
      applyShadowSnapshot(
        mcuPowerUpdatedShadow,
        `Sleep requested at ${new Date().toLocaleTimeString()}`,
      )
      return true
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to request sleep')
      return false
    } finally {
      setIsUpdatingShadow(false)
    }
  }

  const handleTxingSwitchChange = async (checked: boolean): Promise<void> => {
    if (isTxingSwitchPending) {
      return
    }

    if (checked) {
      if (!canWake) {
        return
      }
      setTxingSwitchTarget('on')
      const woke = await updateDesiredPower(true)
      if (!woke) {
        setTxingSwitchTarget(null)
      }
      return
    }

    if (!canSleep) {
      return
    }

    setTxingSwitchTarget('off')
    const slept = await requestSleep()
    if (!slept) {
      setTxingSwitchTarget(null)
    }
  }

  const handleSignOff = (): void => {
    shadowSessionRef.current?.close()
    shadowSessionRef.current = null
    setShadowConnectionState('idle')
    signOut()
  }

  const handleOpenBoardVideo = (): void => {
    if (!canUseBoardVideo) {
      return
    }
    setIsBoardVideoExpanded((currentValue) => !currentValue)
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
      <main className="page page-signed-in">
        <section className="status-hero status-hero-auth" aria-label="Txing sign in">
          <div className="shadow-diagram">
            <div className="status-node status-node-txing">
              <div className="status-txing-header status-auth-header">
                <div
                  className="status-txing-header-side status-txing-header-side-start status-auth-spacer"
                  aria-hidden="true"
                />
                <div className="status-name status-txing-name status-auth-name">Txing</div>
                <div className="status-txing-header-side status-txing-header-side-end">
                  <button type="button" onClick={() => void beginSignIn()} className="primary">
                    Sign in
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>
        {error && <p className="error status-inline-error">{error}</p>}
      </main>
    )
  }

  return (
    <main className="page page-signed-in">
      <TxingPanel
        authUser={authUser}
        canLoadShadow={canLoadShadow}
        canUseBoardVideo={canUseBoardVideo}
        isBoardVideoExpanded={isBoardVideoExpanded}
        isDebugEnabled={isDebugEnabled}
        isTxingSwitchDisabled={isTxingSwitchDisabled}
        isTxingSwitchPending={isTxingSwitchPending}
        lastShadowUpdateAtMs={lastShadowUpdateAtMs}
        reportedBoardOnline={reportedBoardOnline}
        reportedBoardPower={reportedBoardPower}
        reportedMcuBatteryMv={reportedMcuBatteryMv}
        reportedMcuBleOnline={reportedMcuBleOnline}
        reportedMcuPower={reportedMcuPower}
        reportedRedcon={reportedRedcon}
        txingSwitchChecked={txingSwitchChecked}
        videoChannelName={reportedBoardVideo.channelName}
        resolveIdToken={resolveSessionIdToken}
        onLoadShadow={() => {
          void loadShadow()
        }}
        onSignOff={handleSignOff}
        onToggleBoardVideo={handleOpenBoardVideo}
        onToggleDebug={() => {
          setIsDebugEnabled((currentValue) => !currentValue)
        }}
        onTxingSwitchChange={(checked) => {
          void handleTxingSwitchChange(checked)
        }}
      />

      {reportedBoardVideo.lastError && !error ? (
        <p className="error status-inline-error">{reportedBoardVideo.lastError}</p>
      ) : null}
      {error && <p className="error status-inline-error">{error}</p>}

      {isDebugEnabled && (
        <DebugPanel
          feedback={feedback}
          reportedBoardPower={reportedBoardPower}
          reportedMcuPower={reportedMcuPower}
          shadowJson={shadowJson}
        />
      )}
    </main>
  )
}

export default App
