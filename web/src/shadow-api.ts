import type { Twist } from './cmd-vel'

export type ShadowConnectionState = 'idle' | 'connecting' | 'connected' | 'error'
type ResolveIdToken = () => Promise<string>

export type ShadowSessionOptions = {
  thingName: string
  awsRegion: string
  sparkplugGroupId: string
  sparkplugEdgeNodeId: string
  resolveIdToken: ResolveIdToken
  onShadowDocument: (shadow: unknown, operation: 'get' | 'update') => void
  onConnectionStateChange: (state: ShadowConnectionState) => void
  onError: (message: string) => void
}

export type ShadowSession = {
  start: () => Promise<unknown>
  requestSnapshot: () => Promise<unknown>
  updateShadow: (shadowDocument: unknown) => Promise<unknown>
  publishRedconCommand: (redcon: number) => Promise<void>
  publishCmdVel: (twist: Twist) => Promise<void>
  waitForSnapshot: (
    predicate: (shadow: unknown) => boolean,
    timeoutMs: number,
  ) => Promise<unknown>
  isConnected: () => boolean
  isMcpConnected: () => boolean
  close: () => void
}

type ShadowApiRuntimeModule = typeof import('./shadow-api-runtime')

let shadowApiRuntimePromise: Promise<ShadowApiRuntimeModule> | null = null

const loadShadowApiRuntime = (): Promise<ShadowApiRuntimeModule> => {
  if (!shadowApiRuntimePromise) {
    shadowApiRuntimePromise = import('./shadow-api-runtime')
  }

  return shadowApiRuntimePromise
}

class LazyShadowSession implements ShadowSession {
  private readonly options: ShadowSessionOptions
  private session: ShadowSession | null = null
  private sessionPromise: Promise<ShadowSession> | null = null
  private closed = false

  constructor(options: ShadowSessionOptions) {
    this.options = options
  }

  async start(): Promise<unknown> {
    const session = await this.getSession()
    return session.start()
  }

  async requestSnapshot(): Promise<unknown> {
    const session = await this.getSession()
    return session.requestSnapshot()
  }

  async updateShadow(shadowDocument: unknown): Promise<unknown> {
    const session = await this.getSession()
    return session.updateShadow(shadowDocument)
  }

  async publishRedconCommand(redcon: number): Promise<void> {
    const session = await this.getSession()
    await session.publishRedconCommand(redcon)
  }

  async publishCmdVel(twist: Twist): Promise<void> {
    const session = await this.getSession()
    await session.publishCmdVel(twist)
  }

  async waitForSnapshot(
    predicate: (shadow: unknown) => boolean,
    timeoutMs: number,
  ): Promise<unknown> {
    const session = await this.getSession()
    return session.waitForSnapshot(predicate, timeoutMs)
  }

  isConnected(): boolean {
    return this.session?.isConnected() ?? false
  }

  isMcpConnected(): boolean {
    return this.session?.isMcpConnected() ?? false
  }

  close(): void {
    if (this.closed) {
      return
    }

    this.closed = true

    if (this.session) {
      this.session.close()
      return
    }

    void this.sessionPromise?.then((session) => {
      session.close()
    }).catch(() => undefined)
  }

  private async getSession(): Promise<ShadowSession> {
    if (this.closed) {
      throw new Error('Shadow session has already been closed')
    }

    if (this.session) {
      return this.session
    }

    if (!this.sessionPromise) {
      this.sessionPromise = loadShadowApiRuntime()
        .then(({ createShadowSessionRuntime }) => {
          const session = createShadowSessionRuntime(this.options)
          this.session = session

          if (this.closed) {
            session.close()
            throw new Error('Shadow session has already been closed')
          }

          return session
        })
        .catch((error) => {
          if (!this.session) {
            this.sessionPromise = null
          }
          throw error
        })
    }

    return this.sessionPromise
  }
}

export const createShadowSession = (options: ShadowSessionOptions): ShadowSession =>
  new LazyShadowSession(options)
