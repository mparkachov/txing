import { appConfig, getRuntimeAppUrl } from './config'

export type AuthTokens = {
  accessToken: string
  idToken: string
  refreshToken?: string
  expiresAt: number
}

export type AuthUser = {
  email?: string
  name?: string
  sub?: string
}

const TOKEN_KEY = 'txing.auth.tokens'
const STATE_KEY = 'txing.auth.state'
const VERIFIER_KEY = 'txing.auth.pkce_verifier'
const EXPIRY_SKEW_MS = 30_000

type TokenEndpointResponse = {
  access_token: string
  id_token: string
  refresh_token?: string
  expires_in: number
  token_type: string
}

type TokenEndpointErrorResponse = {
  error?: string
  error_description?: string
}

const base64UrlEncode = (bytes: Uint8Array): string => {
  let binary = ''
  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }

  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

const randomString = (length: number): string => {
  const bytes = new Uint8Array(length)
  crypto.getRandomValues(bytes)
  return base64UrlEncode(bytes)
}

const sha256Base64Url = async (input: string): Promise<string> => {
  const encoder = new TextEncoder()
  const digest = await crypto.subtle.digest('SHA-256', encoder.encode(input))
  return base64UrlEncode(new Uint8Array(digest))
}

const decodeJwtPayload = (token: string): Record<string, unknown> => {
  const parts = token.split('.')
  if (parts.length < 2) {
    return {}
  }

  const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
  const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4)

  try {
    return JSON.parse(atob(padded))
  } catch {
    return {}
  }
}

const toStoredTokens = (tokenResponse: TokenEndpointResponse, previous?: AuthTokens): AuthTokens => ({
  accessToken: tokenResponse.access_token,
  idToken: tokenResponse.id_token,
  refreshToken: tokenResponse.refresh_token ?? previous?.refreshToken,
  expiresAt: Date.now() + tokenResponse.expires_in * 1000,
})

const storeTokens = (tokens: AuthTokens): void => {
  sessionStorage.setItem(TOKEN_KEY, JSON.stringify(tokens))
}

export const clearAuthState = (): void => {
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(STATE_KEY)
  sessionStorage.removeItem(VERIFIER_KEY)
}

export const getStoredTokens = (): AuthTokens | null => {
  const raw = sessionStorage.getItem(TOKEN_KEY)
  if (!raw) {
    return null
  }

  try {
    const parsed = JSON.parse(raw) as AuthTokens
    if (!parsed.accessToken || !parsed.idToken || !parsed.expiresAt) {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

const tokenRequest = async (body: URLSearchParams): Promise<TokenEndpointResponse> => {
  const response = await fetch(`${appConfig.cognitoDomain}/oauth2/token`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body,
  })

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    const errorPayload =
      payload && typeof payload === 'object' ? (payload as TokenEndpointErrorResponse) : undefined
    const errorCode = errorPayload?.error?.trim()
    const errorDescription = errorPayload?.error_description?.trim()

    if (errorCode && errorDescription) {
      throw new Error(`Token endpoint failed (${response.status}): ${errorCode}: ${errorDescription}`)
    }
    if (errorCode) {
      throw new Error(`Token endpoint failed (${response.status}): ${errorCode}`)
    }

    throw new Error(`Token endpoint failed (${response.status})`)
  }

  if (!payload || typeof payload !== 'object') {
    throw new Error(`Token endpoint returned an invalid response (${response.status})`)
  }

  return payload as TokenEndpointResponse
}

export const isAuthCallbackUrl = (url: string): boolean => {
  const params = new URL(url).searchParams
  return params.has('code') || params.has('error')
}

export const processAuthCallbackIfPresent = async (): Promise<void> => {
  const callbackUrl = window.location.href
  if (!isAuthCallbackUrl(callbackUrl)) {
    return
  }

  // Remove one-time auth parameters before React mounts so dev StrictMode
  // cannot trigger a second code exchange with the same authorization code.
  window.history.replaceState({}, document.title, getRuntimeAppUrl())
  await handleAuthCallback(callbackUrl)
}

export const beginSignIn = async (): Promise<void> => {
  const verifier = randomString(64)
  const challenge = await sha256Base64Url(verifier)
  const state = randomString(24)

  sessionStorage.setItem(VERIFIER_KEY, verifier)
  sessionStorage.setItem(STATE_KEY, state)

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: appConfig.cognitoClientId,
    redirect_uri: getRuntimeAppUrl(),
    scope: appConfig.cognitoScope,
    code_challenge_method: 'S256',
    code_challenge: challenge,
    state,
  })

  window.location.assign(`${appConfig.cognitoDomain}/oauth2/authorize?${params.toString()}`)
}

export const handleAuthCallback = async (url: string): Promise<AuthTokens> => {
  const callbackUrl = new URL(url)
  const code = callbackUrl.searchParams.get('code')
  const returnedState = callbackUrl.searchParams.get('state')
  const error = callbackUrl.searchParams.get('error')
  const verifier = sessionStorage.getItem(VERIFIER_KEY)
  const expectedState = sessionStorage.getItem(STATE_KEY)

  if (error) {
    throw new Error(`Authentication failed: ${error}`)
  }
  if (!code) {
    throw new Error('Authentication code was not provided')
  }
  if (!verifier || !expectedState || returnedState !== expectedState) {
    throw new Error('Authentication state validation failed')
  }

  const tokenPayload = await tokenRequest(
    new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: appConfig.cognitoClientId,
      code,
      redirect_uri: getRuntimeAppUrl(),
      code_verifier: verifier,
    }),
  )

  const tokens = toStoredTokens(tokenPayload)
  storeTokens(tokens)

  sessionStorage.removeItem(STATE_KEY)
  sessionStorage.removeItem(VERIFIER_KEY)

  return tokens
}

export const refreshTokensIfNeeded = async (): Promise<AuthTokens | null> => {
  const current = getStoredTokens()
  if (!current) {
    return null
  }

  if (Date.now() + EXPIRY_SKEW_MS < current.expiresAt) {
    return current
  }

  if (!current.refreshToken) {
    clearAuthState()
    return null
  }

  let tokenPayload: TokenEndpointResponse
  try {
    tokenPayload = await tokenRequest(
      new URLSearchParams({
        grant_type: 'refresh_token',
        client_id: appConfig.cognitoClientId,
        refresh_token: current.refreshToken,
      }),
    )
  } catch {
    clearAuthState()
    return null
  }

  const refreshed = toStoredTokens(tokenPayload, current)
  storeTokens(refreshed)
  return refreshed
}

export const getAuthUser = (tokens: AuthTokens): AuthUser => {
  const claims = decodeJwtPayload(tokens.idToken)

  return {
    email: typeof claims.email === 'string' ? claims.email : undefined,
    name: typeof claims.name === 'string' ? claims.name : undefined,
    sub: typeof claims.sub === 'string' ? claims.sub : undefined,
  }
}

export const signOut = (): void => {
  clearAuthState()
  const params = new URLSearchParams({
    client_id: appConfig.cognitoClientId,
    logout_uri: getRuntimeAppUrl(),
  })
  window.location.assign(`${appConfig.cognitoDomain}/logout?${params.toString()}`)
}
