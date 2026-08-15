import type { MavlinkDataChannelHandle } from './mavlink-control'

export type StartMavlinkDataChannelOptions = {
  channelName: string
  label: string
  onMessage: (message: string | Uint8Array) => void
  onStateChange: (state: 'connecting' | 'open' | 'closed' | 'error', message?: string) => void
  region: string
  resolveIdToken: () => Promise<string>
}

let runtimePromise: Promise<typeof import('./mavlink-session-runtime')> | null = null

const loadRuntime = (): Promise<typeof import('./mavlink-session-runtime')> => {
  if (!runtimePromise) {
    runtimePromise = import('./mavlink-session-runtime')
  }
  return runtimePromise
}

export const startMavlinkDataChannel = async (
  options: StartMavlinkDataChannelOptions,
): Promise<MavlinkDataChannelHandle> => {
  const { startMavlinkDataChannelRuntime } = await loadRuntime()
  return startMavlinkDataChannelRuntime(options)
}
