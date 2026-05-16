import * as auth from 'aws-crt/dist.browser/browser/auth'
import * as iot from 'aws-crt/dist.browser/browser/iot'
import * as mqtt5 from 'aws-crt/dist.browser/browser/mqtt5'
import { LatestAsyncValueRunner } from './async-latest'
import { createCredentialProvider } from './aws-credentials'
import { isZeroTwist, type Twist } from './cmd-vel'
import { appConfig } from './config'
import { ensureIotPolicyAttached, getIdentityId } from './iot-policy-attach'
import { resolveIotDataEndpoint } from './iot-endpoint'
import {
  isMcpSessionNotInitializedError,
  isRecoverableMcpActiveControlError,
} from './mcp-errors'
import { getMcpActiveControlRenewBeforeMs } from './mcp-active-control'
import {
  parseMcpDescriptor,
  shouldAwaitInitialMcpDescriptor,
  selectPreferredMcpWebRtcTransport,
  type McpDescriptor,
  type McpTransportKind,
} from './mcp-descriptor'
import {
  buildMcpDescriptorTopic,
  buildMcpSessionC2sTopic,
  buildMcpSessionS2cTopic,
  buildMcpStatusTopic,
} from './mcp-topics'
import { buildShadowMqttClientId } from './shadow-client-id'
import { mergeShadowUpdate } from './shadow-merge'
import {
  buildSparkplugRedconCommandPacket,
  buildSparkplugTopics,
  type SparkplugTopics,
} from './sparkplug-protocol'
import type {
  RobotControlState,
  RobotMotionState,
  RobotState,
  RobotVideoState,
} from './shadow-api'
import {
  buildGetShadowPublishPacket,
  buildNamedShadowTopics,
  buildShadowSubscriptionPacket,
  createShadowClientToken,
  decodeShadowResponse,
  deriveMqttHostFromIotDataEndpoint,
  parseShadowPayload,
  type DecodedShadowResponse,
  type ShadowName,
  type ShadowOperation,
  type ShadowTopics,
} from './shadow-protocol'
import {
  startBoardMcpDataChannel,
  type McpDataChannelHandle,
} from './video-session'

const forbiddenRetryDelaysMs = [500, 1000, 2000]
const initialSnapshotTimeoutMs = 20_000
const mcpRequestTimeoutMs = 8_000
const mcpWebRtcOpenTimeoutMs = 20_000
const initialMcpDescriptorWaitTimeoutMs = 2_000
const primaryShadowName: ShadowName = 'sparkplug'

export type ShadowConnectionState = 'idle' | 'connecting' | 'connected' | 'error'
type ResolveIdToken = () => Promise<string>
type PendingRequest = {
  operation: ShadowOperation
  shadowName: ShadowName
  resolve: (shadow: unknown) => void
  reject: (error: Error) => void
}
type SnapshotWaiter = {
  predicate: (shadow: unknown) => boolean
  resolve: (shadow: unknown) => void
  reject: (error: Error) => void
  timeoutId: number
}
type PendingMcpRequest = {
  resolve: (result: unknown) => void
  reject: (error: Error) => void
  timeoutId: number
}
type McpDiscoverySummary = {
  available: boolean | null
  observedAtMs: number | null
  transport: string | null
  mcpProtocolVersion: string | null
  descriptorTopic: string | null
  activeTtlMs: number | null
  serverVersion: string | null
}
type McpActiveControlState = {
  epoch: number
  expiresAtMs: number
  activeTtlMs: number
}
type McpMotionCommandResult = {
  activeExpiresAtMs: number | null
  activeEpoch: number | null
  motion: RobotMotionState
}
export type ShadowSessionOptions = {
  thingName: string
  awsRegion: string
  sparkplugGroupId: string
  sparkplugEdgeNodeId: string
  capabilities: readonly ShadowName[]
  resolveIdToken: ResolveIdToken
  onShadowDocument: (shadow: unknown, operation: ShadowOperation) => void
  onRobotStateChange: (state: RobotState | null) => void
  onMcpTransportChange: (transport: McpTransportKind | null) => void
  onConnectionStateChange: (state: ShadowConnectionState) => void
  onError: (message: string) => void
}
export type ShadowSession = {
  start: () => Promise<unknown>
  requestSnapshot: () => Promise<unknown>
  publishRedconCommand: (redcon: number) => Promise<void>
  publishCmdVel: (twist: Twist) => Promise<void>
  callMcpTool: (name: string, args?: Record<string, unknown>) => Promise<unknown>
  requestRobotState: () => Promise<RobotState>
  waitForSnapshot: (
    predicate: (shadow: unknown) => boolean,
    timeoutMs: number,
  ) => Promise<unknown>
  isConnected: () => boolean
  close: () => void
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

const formatMqtt5ReasonCode = (
  enumType: Record<string, string | number>,
  reasonCode: number,
): string => {
  const enumLabel = enumType[reasonCode]
  return typeof enumLabel === 'string' ? `${enumLabel} (${reasonCode})` : `${reasonCode}`
}

const ensureSuccessfulSuback = (
  suback: mqtt5.SubackPacket,
  subscriptions: readonly { topicFilter: string }[],
  context: string,
): void => {
  const failures = subscriptions.flatMap((subscription, index) => {
    const reasonCode = suback.reasonCodes[index]
    if (
      typeof reasonCode === 'number' &&
      mqtt5.isSuccessfulSubackReasonCode(reasonCode)
    ) {
      return []
    }
    const reasonSuffix =
      typeof reasonCode === 'number'
        ? formatMqtt5ReasonCode(mqtt5.SubackReasonCode, reasonCode)
        : 'missing reason code'
    return [`${subscription.topicFilter} (${reasonSuffix})`]
  })

  if (failures.length === 0) {
    return
  }

  const reasonStringSuffix =
    typeof suback.reasonString === 'string' && suback.reasonString.trim()
      ? `: ${suback.reasonString.trim()}`
      : ''
  throw new Error(`${context} subscribe rejected for ${failures.join(', ')}${reasonStringSuffix}`)
}

const ensureSuccessfulPuback = (
  result: mqtt5.PublishCompletionResult,
  topicName: string,
  context: string,
): void => {
  if (!result) {
    return
  }

  if (mqtt5.isSuccessfulPubackReasonCode(result.reasonCode)) {
    return
  }

  const reasonStringSuffix =
    typeof result.reasonString === 'string' && result.reasonString.trim()
      ? `: ${result.reasonString.trim()}`
      : ''
  throw new Error(
    `${context} publish rejected for ${topicName} (${formatMqtt5ReasonCode(
      mqtt5.PubackReasonCode,
      result.reasonCode,
    )})${reasonStringSuffix}`,
  )
}

const getErrorMessage = (error: unknown, fallback = 'Thing Shadow request failed'): string => {
  if (error instanceof Error) {
    if (error.name && error.message) {
      return `${error.name}: ${error.message}`
    }
    return error.message
  }

  return fallback
}

const isForbiddenError = (error: unknown): boolean =>
  error instanceof Error &&
  (error.name === 'ForbiddenException' || error.message.toLowerCase().includes('not authorized'))

const isNotAuthorizedConnectError = (error: unknown): boolean =>
  error instanceof Error && error.message.toLowerCase().includes('not authorized')

const runWithForbiddenRetry = async <T>(
  operation: () => Promise<T>,
  retryForbidden: boolean,
): Promise<T> => {
  try {
    return await operation()
  } catch (caughtError) {
    if (!retryForbidden || !isForbiddenError(caughtError)) {
      throw caughtError
    }
  }

  for (const delayMs of forbiddenRetryDelaysMs) {
    await sleep(delayMs)

    try {
      return await operation()
    } catch (caughtError) {
      if (!isForbiddenError(caughtError)) {
        throw caughtError
      }
    }
  }

  return operation()
}

const getShadowRejectedMessage = (
  decodedResponse: DecodedShadowResponse,
): string => {
  if (isRecord(decodedResponse.payload) && typeof decodedResponse.payload.message === 'string') {
    return decodedResponse.payload.message
  }
  return `Thing Shadow ${decodedResponse.operation ?? 'request'} was rejected`
}

const normalizeMcpDiscoverySummary = (thingName: string): McpDiscoverySummary => ({
  available: null,
  observedAtMs: null,
  transport: null,
  mcpProtocolVersion: null,
  descriptorTopic: buildMcpDescriptorTopic(thingName),
  activeTtlMs: null,
  serverVersion: null,
})

const createMcpSessionId = (): string =>
  typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `session-${Date.now()}-${Math.random().toString(16).slice(2)}`

const containsMcpActiveEpoch = (value: unknown, depth = 0): boolean => {
  if (depth > 4 || !isRecord(value)) {
    return false
  }
  if (typeof value.epoch === 'number' && Number.isFinite(value.epoch)) {
    return true
  }
  return Object.values(value).some((child) => containsMcpActiveEpoch(child, depth + 1))
}

const parseMcpActiveControlState = (
  value: unknown,
  fallbackActiveTtlMs: number,
): McpActiveControlState | null => {
  if (!isRecord(value)) {
    return null
  }
  const activeControl = isRecord(value.activeControl) ? value.activeControl : value
  const epoch = activeControl.epoch
  if (typeof epoch !== 'number' || !Number.isInteger(epoch) || epoch <= 0) {
    return null
  }
  const activeTtlMs =
    typeof value.activeTtlMs === 'number' && Number.isFinite(value.activeTtlMs) && value.activeTtlMs > 0
      ? Math.round(value.activeTtlMs)
      : fallbackActiveTtlMs
  // Use local wall clock for renewal deadlines to avoid board/browser clock skew.
  // Server still enforces the real active-control validity; this only drives client renew timing.
  const localExpiresAtMs = Date.now() + Math.round(activeTtlMs)
  return {
    epoch,
    expiresAtMs: localExpiresAtMs,
    activeTtlMs,
  }
}

const createDefaultRobotVideoState = (): RobotVideoState => ({
  available: false,
  ready: false,
  status: 'unavailable',
  viewerConnected: false,
  lastError: null,
})

const createDefaultRobotControlState = (
  overrides: Partial<RobotControlState> = {},
): RobotControlState => ({
  activeRequired: true,
  activeTtlMs: null,
  activeHeldByCaller: false,
  activeOwnerSessionId: null,
  activeExpiresAtMs: null,
  activeEpoch: null,
  ...overrides,
})

const createStoppedRobotMotionState = (
  previousMotion: RobotMotionState | null = null,
): RobotMotionState => ({
  leftSpeed: 0,
  rightSpeed: 0,
  sequence:
    typeof previousMotion?.sequence === 'number' && Number.isInteger(previousMotion.sequence)
      ? previousMotion.sequence + 1
      : 0,
})

const parseSignedPercent = (value: unknown): number | null =>
  typeof value === 'number' && Number.isInteger(value) && value >= -100 && value <= 100
    ? value
    : null

const parseOptionalInteger = (value: unknown): number | null =>
  typeof value === 'number' && Number.isInteger(value) ? value : null

const parseRobotMotionState = (value: unknown): RobotMotionState | null => {
  if (!isRecord(value)) {
    return null
  }
  const leftSpeed = parseSignedPercent(value.leftSpeed)
  const rightSpeed = parseSignedPercent(value.rightSpeed)
  const sequence = parseOptionalInteger(value.sequence)
  if (leftSpeed === null || rightSpeed === null || sequence === null) {
    return null
  }
  return {
    leftSpeed,
    rightSpeed,
    sequence,
  }
}

const parseRobotVideoStatus = (
  value: unknown,
): RobotVideoState['status'] =>
  value === 'starting' || value === 'ready' || value === 'error' || value === 'unavailable'
    ? value
    : null

const parseRobotVideoState = (value: unknown): RobotVideoState | null => {
  if (!isRecord(value)) {
    return null
  }
  const status = parseRobotVideoStatus(value.status)
  if (
    typeof value.available !== 'boolean' ||
    typeof value.ready !== 'boolean' ||
    typeof value.viewerConnected !== 'boolean' ||
    status === null
  ) {
    return null
  }
  return {
    available: value.available,
    ready: value.ready,
    status,
    viewerConnected: value.viewerConnected,
    lastError: typeof value.lastError === 'string' && value.lastError.trim() ? value.lastError : null,
  }
}

const parseRobotControlState = (value: unknown): RobotControlState | null => {
  if (!isRecord(value)) {
    return null
  }
  if (typeof value.activeRequired !== 'boolean' || typeof value.activeHeldByCaller !== 'boolean') {
    return null
  }
  const activeTtlMs =
    typeof value.activeTtlMs === 'number' && Number.isFinite(value.activeTtlMs) && value.activeTtlMs > 0
      ? Math.round(value.activeTtlMs)
      : null
  const activeExpiresAtMs =
    typeof value.activeExpiresAtMs === 'number' &&
    Number.isFinite(value.activeExpiresAtMs) &&
    value.activeExpiresAtMs >= 0
      ? Math.round(value.activeExpiresAtMs)
      : null
  const activeOwnerSessionId =
    typeof value.activeOwnerSessionId === 'string' && value.activeOwnerSessionId.trim()
      ? value.activeOwnerSessionId
      : null
  const activeEpoch =
    typeof value.activeEpoch === 'number' && Number.isInteger(value.activeEpoch) && value.activeEpoch > 0
      ? value.activeEpoch
      : null
  return {
    activeRequired: value.activeRequired,
    activeTtlMs,
    activeHeldByCaller: value.activeHeldByCaller,
    activeOwnerSessionId,
    activeExpiresAtMs,
    activeEpoch,
  }
}

const parseRobotState = (value: unknown): RobotState | null => {
  if (!isRecord(value)) {
    return null
  }
  const control = parseRobotControlState(value.control)
  const motion = parseRobotMotionState(value.motion)
  const video = parseRobotVideoState(value.video)
  if (!control || !motion || !video) {
    return null
  }
  return {
    control,
    motion,
    video,
  }
}

const parseMcpMotionCommandResult = (value: unknown): McpMotionCommandResult | null => {
  if (!isRecord(value)) {
    return null
  }
  const motion = parseRobotMotionState(value.motion)
  if (!motion) {
    return null
  }
  const activeExpiresAtMs =
    typeof value.activeExpiresAtMs === 'number' &&
    Number.isFinite(value.activeExpiresAtMs) &&
    value.activeExpiresAtMs >= 0
      ? Math.round(value.activeExpiresAtMs)
      : null
  const activeControl = isRecord(value.activeControl) ? value.activeControl : null
  const activeEpoch =
    typeof activeControl?.epoch === 'number' && Number.isInteger(activeControl.epoch) && activeControl.epoch > 0
      ? activeControl.epoch
      : null
  return {
    activeExpiresAtMs,
    activeEpoch,
    motion,
  }
}

class BrowserCredentialProvider extends auth.CredentialsProvider {
  private credentials: auth.AWSCredentials | undefined
  private readonly resolveIdToken: ResolveIdToken
  private provider: ReturnType<typeof createCredentialProvider> | null = null
  private providerIdToken: string | null = null
  private refreshPromise: Promise<void> | null = null

  constructor(resolveIdToken: ResolveIdToken) {
    super()
    this.resolveIdToken = resolveIdToken
  }

  override getCredentials(): auth.AWSCredentials | undefined {
    return this.credentials
  }

  override async refreshCredentials(): Promise<void> {
    if (!this.refreshPromise) {
      this.refreshPromise = this.loadCredentials().finally(() => {
        this.refreshPromise = null
      })
    }

    await this.refreshPromise
  }

  private async loadCredentials(): Promise<void> {
    const idToken = await this.resolveIdToken()
    if (!this.provider || this.providerIdToken !== idToken) {
      this.provider = createCredentialProvider(idToken)
      this.providerIdToken = idToken
    }

    const credentials = await this.provider()
    if (!credentials.accessKeyId || !credentials.secretAccessKey) {
      throw new Error('Cognito identity pool did not return AWS credentials')
    }

    this.credentials = {
      aws_access_id: credentials.accessKeyId,
      aws_secret_key: credentials.secretAccessKey,
      aws_sts_token: credentials.sessionToken,
      aws_region: appConfig.awsRegion,
    }
  }
}

class AwsIotShadowSession implements ShadowSession {
  private readonly options: ShadowSessionOptions
  private readonly topics: Partial<Record<ShadowName, ShadowTopics>>
  private readonly requiredShadowNames: readonly ShadowName[]
  private readonly sparkplugTopics: SparkplugTopics
  private readonly mcpDescriptorTopic: string
  private readonly mcpStatusTopic: string
  private readonly credentialsProvider: BrowserCredentialProvider
  private client: mqtt5.Mqtt5Client | null = null
  private closed = false
  private connectionState: ShadowConnectionState = 'idle'
  private startPromise: Promise<unknown> | null = null
  private latestShadows: Partial<Record<ShadowName, unknown>> = {}
  private sparkplugCommandSeq = 0
  private suppressConnectionErrors = false
  private readonly pendingRequests = new Map<string, PendingRequest>()
  private readonly snapshotWaiters = new Set<SnapshotWaiter>()
  private readonly pendingMcpRequests = new Map<number, PendingMcpRequest>()
  private mcpRequestSeq = 0
  private mcpDiscovery: McpDiscoverySummary
  private mcpDescriptor: McpDescriptor | null = null
  private mcpActiveControl: McpActiveControlState | null = null
  private latestRobotState: RobotState | null = null
  private mcpSessionId: string | null = null
  private mcpSessionSubscribed = false
  private mcpInitialized = false
  private activeMcpTransport: McpTransportKind | null = null
  private mcpWebRtcHandle: McpDataChannelHandle | null = null
  private mcpSessionReadyPromise: Promise<void> | null = null
  private mcpWebRtcUnavailable = false
  private readonly mcpDescriptorWaiters = new Set<(descriptor: McpDescriptor | null) => void>()
  private readonly cmdVelPublisher: LatestAsyncValueRunner<Twist>
  private readonly handleAttemptingConnect = (): void => {
    if (this.closed) {
      return
    }
    this.setConnectionState('connecting')
  }
  private readonly handleConnectionSuccess = (): void => {
    if (this.closed) {
      return
    }
    void this.subscribeAndRefresh()
  }
  private readonly handleConnectionFailure = (event: mqtt5.ConnectionFailureEvent): void => {
    if (this.closed) {
      return
    }
    const detail = getErrorMessage(event.error)
    if (!this.suppressConnectionErrors) {
      this.setConnectionState('error')
      this.options.onError(`Shadow connection failed: ${detail}`)
    }
    this.rejectPendingRequests(new Error(`Shadow connection failed before response: ${detail}`))
    this.rejectSnapshotWaiters(new Error(`Shadow connection failed before response: ${detail}`))
    this.rejectPendingMcpRequests(new Error(`MCP request failed before response: ${detail}`))
    this.resetMcpConnectionState()
  }
  private readonly handleDisconnection = (event: mqtt5.DisconnectionEvent): void => {
    if (this.closed) {
      return
    }
    const detail = getErrorMessage(event.error)
    if (!this.suppressConnectionErrors) {
      this.setConnectionState('error')
      this.options.onError(`Shadow connection lost: ${detail}`)
    }
    this.rejectPendingRequests(new Error(`Shadow connection lost before response: ${detail}`))
    this.rejectSnapshotWaiters(new Error(`Shadow connection lost before response: ${detail}`))
    this.rejectPendingMcpRequests(new Error(`MCP request failed before response: ${detail}`))
    this.resetMcpConnectionState()
  }
  private readonly handleMessageReceived = (event: mqtt5.MessageReceivedEvent): void => {
    if (this.closed) {
      return
    }

    const topic = event.message.topicName ?? ''
    const decoded = this.decodeAnyShadowResponse(topic, event.message.payload)
    if (decoded.kind === 'ignored') {
      this.handleNonShadowMessage(topic, event.message.payload)
      return
    }

    if (decoded.kind === 'getAccepted' || decoded.kind === 'updateAccepted') {
      if (decoded.shadowName === null) {
        return
      }
      const currentShadow = this.latestShadows[decoded.shadowName]
      this.latestShadows[decoded.shadowName] =
        decoded.kind === 'updateAccepted'
          ? mergeShadowUpdate(currentShadow, decoded.payload)
          : decoded.payload
      if (decoded.shadowName === 'mcp') {
        this.refreshMcpDiscoveryFromMcpShadow()
      }
      const assembledShadow = this.assembleShadowSnapshot()
      this.options.onShadowDocument(assembledShadow, decoded.operation ?? 'get')
      this.resolveSnapshotWaiters(assembledShadow)
      if (decoded.clientToken) {
        this.resolvePendingRequest(decoded.clientToken, assembledShadow)
      }
      return
    }

    const error = new Error(getShadowRejectedMessage(decoded))
    if (decoded.clientToken) {
      this.rejectPendingRequest(decoded.clientToken, error)
    }
    this.options.onError(error.message)
  }

  constructor(options: ShadowSessionOptions) {
    this.options = options
    this.requiredShadowNames = options.capabilities
    this.topics = buildNamedShadowTopics(options.thingName, this.requiredShadowNames)
    if (!this.topics.sparkplug) {
      throw new Error('Thing capabilities must include sparkplug')
    }
    this.sparkplugTopics = buildSparkplugTopics(
      options.sparkplugGroupId,
      options.sparkplugEdgeNodeId,
      options.thingName,
    )
    this.mcpDescriptorTopic = buildMcpDescriptorTopic(options.thingName)
    this.mcpStatusTopic = buildMcpStatusTopic(options.thingName)
    this.mcpDiscovery = normalizeMcpDiscoverySummary(options.thingName)
    this.credentialsProvider = new BrowserCredentialProvider(options.resolveIdToken)
    this.cmdVelPublisher = new LatestAsyncValueRunner(async (twist) => this.publishCmdVelNow(twist))
  }

  async start(): Promise<unknown> {
    if (this.closed) {
      throw new Error('Shadow session has already been closed')
    }

    const assembledShadow = this.assembleShadowSnapshot()
    if (assembledShadow !== null) {
      return assembledShadow
    }

    if (!this.startPromise) {
      this.startPromise = this.open()
    }

    return this.startPromise
  }

  async requestSnapshot(): Promise<unknown> {
    const snapshots = await Promise.all(
      Object.values(this.topics).map((topics) => {
        if (!topics) {
          throw new Error('Missing named shadow topics')
        }
        const clientToken = createShadowClientToken('get')
        const packet = buildGetShadowPublishPacket(topics, clientToken)
        return this.publishRequest('get', topics.shadowName, clientToken, packet)
      }),
    )
    return snapshots[snapshots.length - 1] ?? this.assembleShadowSnapshot()
  }

  private async publishInitialSnapshotRequests(): Promise<void> {
    const client = this.client
    if (!client || !this.isConnected()) {
      throw new Error('Shadow connection is not ready')
    }

    await Promise.all(
      Object.values(this.topics).map(async (topics) => {
        if (!topics) {
          throw new Error('Missing named shadow topics')
        }
        const packet = buildGetShadowPublishPacket(
          topics,
          createShadowClientToken('get'),
        )
        const result = await client.publish(packet as mqtt5.PublishPacket)
        ensureSuccessfulPuback(
          result,
          packet.topicName,
          `Initial shadow get for ${topics.shadowName}`,
        )
      }),
    )
  }

  async publishRedconCommand(redcon: number): Promise<void> {
    const client = this.client
    if (!client || !this.isConnected()) {
      throw new Error('Shadow connection is not ready')
    }

    const packet = buildSparkplugRedconCommandPacket(
      this.sparkplugTopics,
      redcon,
      this.sparkplugCommandSeq,
    )
    this.sparkplugCommandSeq = (this.sparkplugCommandSeq + 1) % 256
    const result = await client.publish(packet as mqtt5.PublishPacket)
    ensureSuccessfulPuback(result, packet.topicName, 'Sparkplug DCMD.redcon')
  }

  async publishCmdVel(twist: Twist): Promise<void> {
    return this.cmdVelPublisher.push(twist)
  }

  async callMcpTool(
    name: string,
    argumentsPayload: Record<string, unknown> = {},
  ): Promise<unknown> {
    await this.ensureMcpSessionReady()
    return this.callMcpToolInternal(name, argumentsPayload)
  }

  async requestRobotState(): Promise<RobotState> {
    if (this.pendingMcpRequests.size > 0 && this.latestRobotState) {
      return this.latestRobotState
    }
    await this.ensureMcpSessionReady()
    const robotState = await this.fetchRobotStateWithSessionRetry()
    this.setLatestRobotState(robotState)
    return robotState
  }

  private async fetchRobotStateWithSessionRetry(): Promise<RobotState> {
    try {
      return this.parseRobotStateResult(await this.callMcpToolInternal('robot.get_state', {}))
    } catch (caughtError) {
      if (!isMcpSessionNotInitializedError(caughtError)) {
        throw caughtError
      }
      this.mcpInitialized = false
      this.mcpSessionReadyPromise = null
      await this.ensureMcpSessionReady()
      return this.parseRobotStateResult(await this.callMcpToolInternal('robot.get_state', {}))
    }
  }

  private parseRobotStateResult(result: unknown): RobotState {
    const robotState = parseRobotState(result)
    if (!robotState) {
      throw new Error('MCP robot.get_state returned an invalid payload')
    }
    return robotState
  }

  async waitForSnapshot(
    predicate: (shadow: unknown) => boolean,
    timeoutMs: number,
  ): Promise<unknown> {
    const assembledShadow = this.assembleShadowSnapshot()
    if (assembledShadow !== null && predicate(assembledShadow)) {
      return assembledShadow
    }

    return new Promise<unknown>((resolve, reject) => {
      const waiter: SnapshotWaiter = {
        predicate,
        resolve: (shadow) => {
          window.clearTimeout(waiter.timeoutId)
          this.snapshotWaiters.delete(waiter)
          resolve(shadow)
        },
        reject: (error) => {
          window.clearTimeout(waiter.timeoutId)
          this.snapshotWaiters.delete(waiter)
          reject(error)
        },
        timeoutId: window.setTimeout(() => {
          reject(new Error(`Timed out waiting for shadow update after ${timeoutMs}ms`))
          this.snapshotWaiters.delete(waiter)
        }, timeoutMs),
      }

      this.snapshotWaiters.add(waiter)
    })
  }

  isConnected(): boolean {
    return this.connectionState === 'connected' && this.client?.isConnected() === true
  }

  close(): void {
    this.cmdVelPublisher.close()
    this.sendMcpStopAndReleaseBestEffort()
    this.closed = true
    this.setConnectionState('idle')
    this.setLatestRobotState(null)
    this.rejectPendingRequests(new Error('Shadow session closed'))
    this.rejectSnapshotWaiters(new Error('Shadow session closed'))
    this.rejectPendingMcpRequests(new Error('MCP session closed'))
    this.resetMcpConnectionState()
    this.disposeClient(this.client)
  }

  private async open(): Promise<unknown> {
    const idToken = await this.options.resolveIdToken()
    const policyWasAttached = await ensureIotPolicyAttached(idToken)
    await runWithForbiddenRetry(
      async () => {
        await this.credentialsProvider.refreshCredentials()
      },
      policyWasAttached,
    )

    const identityId = await getIdentityId(idToken)
    const iotDataEndpoint = await resolveIotDataEndpoint({
      region: this.options.awsRegion,
      idToken,
    })
    const mqttHost = deriveMqttHostFromIotDataEndpoint(iotDataEndpoint)
    try {
      try {
        return await this.openWithClientId(
          mqttHost,
          buildShadowMqttClientId(identityId),
          true,
        )
      } catch (caughtError) {
        if (!isNotAuthorizedConnectError(caughtError)) {
          throw caughtError
        }
        return await this.openWithClientId(mqttHost, identityId, false)
      }
    } finally {
      this.startPromise = null
    }
  }

  private async openWithClientId(
    mqttHost: string,
    clientId: string,
    suppressErrors: boolean,
  ): Promise<unknown> {
    const client = this.createClient(mqttHost, clientId)
    this.client = client
    this.resetMcpConnectionState()
    this.suppressConnectionErrors = suppressErrors
    this.setConnectionState('connecting')
    client.start()

    try {
      return await this.waitForSnapshot(() => this.hasPrimaryShadowSnapshot(), initialSnapshotTimeoutMs)
    } catch (caughtError) {
      this.disposeClient(client)
      throw caughtError
    } finally {
      this.suppressConnectionErrors = false
    }
  }

  private createClient(mqttHost: string, clientId: string): mqtt5.Mqtt5Client {
    const builder = iot.AwsIotMqtt5ClientConfigBuilder.newWebsocketMqttBuilderWithSigv4Auth(
      mqttHost,
      {
        region: this.options.awsRegion,
        credentialsProvider: this.credentialsProvider,
      },
    )
    builder.withConnectProperties({
      clientId,
      keepAliveIntervalSeconds: 1200,
    })
    builder.withSessionBehavior(mqtt5.ClientSessionBehavior.Clean)
    builder.withMinReconnectDelayMs(1_000)
    builder.withMaxReconnectDelayMs(10_000)

    const client = new mqtt5.Mqtt5Client(builder.build())
    client.on('attemptingConnect', this.handleAttemptingConnect)
    client.on('connectionSuccess', this.handleConnectionSuccess)
    client.on('connectionFailure', this.handleConnectionFailure)
    client.on('disconnection', this.handleDisconnection)
    client.on('messageReceived', this.handleMessageReceived)
    return client
  }

  private disposeClient(client: mqtt5.Mqtt5Client | null): void {
    if (!client) {
      return
    }
    client.removeListener('attemptingConnect', this.handleAttemptingConnect)
    client.removeListener('connectionSuccess', this.handleConnectionSuccess)
    client.removeListener('connectionFailure', this.handleConnectionFailure)
    client.removeListener('disconnection', this.handleDisconnection)
    client.removeListener('messageReceived', this.handleMessageReceived)
    client.stop()
    client.close()
    if (this.client === client) {
      this.client = null
    }
  }

  private async subscribeAndRefresh(): Promise<void> {
    const client = this.client
    if (!client) {
      return
    }

    try {
      const shadowSubscriptionPacket = buildShadowSubscriptionPacket(
        this.topics,
      ) as mqtt5.SubscribePacket
      const shadowSuback = await client.subscribe(shadowSubscriptionPacket)
      ensureSuccessfulSuback(
        shadowSuback,
        shadowSubscriptionPacket.subscriptions,
        'Thing shadow',
      )
      const mcpDiscoverySubscriptionPacket = {
        subscriptions: [
          { topicFilter: this.mcpDescriptorTopic, qos: 1 as const },
          { topicFilter: this.mcpStatusTopic, qos: 1 as const },
        ],
      } as mqtt5.SubscribePacket
      const mcpDiscoverySuback = await client.subscribe(mcpDiscoverySubscriptionPacket)
      ensureSuccessfulSuback(
        mcpDiscoverySuback,
        mcpDiscoverySubscriptionPacket.subscriptions,
        'MCP discovery',
      )
      if (this.closed || client !== this.client) {
        return
      }
      this.setConnectionState('connected')
      void this.publishInitialSnapshotRequests().catch((caughtError) => {
        if (this.closed || client !== this.client) {
          return
        }
        this.options.onError(
          `Unable to request initial shadow snapshots: ${getErrorMessage(caughtError)}`,
        )
      })
      void this.warmUpMcpSession()
    } catch (caughtError) {
      this.setConnectionState('error')
      this.options.onError(`Unable to subscribe to shadow topics: ${getErrorMessage(caughtError)}`)
      this.rejectSnapshotWaiters(
        new Error(`Unable to subscribe to shadow topics: ${getErrorMessage(caughtError)}`),
      )
    }
  }

  private decodeAnyShadowResponse(topic: string, payload: unknown): DecodedShadowResponse {
    for (const topics of Object.values(this.topics)) {
      if (!topics) {
        continue
      }
      const decoded = decodeShadowResponse(topic, payload, topics)
      if (decoded.kind !== 'ignored') {
        return decoded
      }
    }
    return {
      kind: 'ignored',
      operation: null,
      shadowName: null,
      payload: parseShadowPayload(payload),
      clientToken: null,
    }
  }

  private assembleShadowSnapshot(): unknown | null {
    const hasAnyShadow = Object.keys(this.latestShadows).length > 0
    if (!hasAnyShadow) {
      return null
    }

    const sparkplugShadow = this.latestShadows.sparkplug
    return {
      ...(isRecord(sparkplugShadow) && isRecord(sparkplugShadow.state)
        ? { state: sparkplugShadow.state }
        : {}),
      namedShadows: {
        ...this.latestShadows,
      },
    }
  }

  private hasPrimaryShadowSnapshot(): boolean {
    return this.latestShadows[primaryShadowName] !== undefined
  }

  private async publishRequest(
    operation: ShadowOperation,
    shadowName: ShadowName,
    clientToken: string,
    packet: mqtt5.PublishPacket,
  ): Promise<unknown> {
    const client = this.client
    if (!client || !this.isConnected()) {
      throw new Error('Shadow connection is not ready')
    }

    return new Promise<unknown>((resolve, reject) => {
      this.pendingRequests.set(clientToken, {
        operation,
        shadowName,
        resolve,
        reject,
      })

      void client
        .publish(packet)
        .then((result) => {
          try {
            ensureSuccessfulPuback(
              result,
              packet.topicName,
              `Shadow ${operation}`,
            )
          } catch (caughtError) {
            this.rejectPendingRequest(
              clientToken,
              caughtError instanceof Error
                ? caughtError
                : new Error(`Shadow ${operation} publish was rejected`),
            )
          }
        })
        .catch((caughtError) => {
          this.rejectPendingRequest(
            clientToken,
            new Error(`Unable to publish shadow ${operation}: ${getErrorMessage(caughtError)}`),
          )
        })
    })
  }

  private resolvePendingRequest(clientToken: string, shadow: unknown): void {
    const pendingRequest = this.pendingRequests.get(clientToken)
    if (!pendingRequest) {
      return
    }
    this.pendingRequests.delete(clientToken)
    pendingRequest.resolve(shadow)
  }

  private rejectPendingRequest(clientToken: string, error: Error): void {
    const pendingRequest = this.pendingRequests.get(clientToken)
    if (!pendingRequest) {
      return
    }
    this.pendingRequests.delete(clientToken)
    pendingRequest.reject(error)
  }

  private rejectPendingRequests(error: Error): void {
    for (const clientToken of [...this.pendingRequests.keys()]) {
      this.rejectPendingRequest(clientToken, error)
    }
  }

  private updateMcpAvailability(available: boolean, observedAtMs: unknown): void {
    const nextObservedAtMs =
      typeof observedAtMs === 'number' && Number.isFinite(observedAtMs)
        ? Math.round(observedAtMs)
        : null
    if (nextObservedAtMs === null && this.mcpDiscovery.observedAtMs !== null) {
      return
    }
    if (
      nextObservedAtMs !== null &&
      this.mcpDiscovery.observedAtMs !== null &&
      nextObservedAtMs < this.mcpDiscovery.observedAtMs
    ) {
      return
    }
    this.mcpDiscovery.available = available
    if (nextObservedAtMs !== null) {
      this.mcpDiscovery.observedAtMs = nextObservedAtMs
    }
  }

  private hasMcpDescriptorHint(): boolean {
    return (
      this.mcpDescriptor !== null ||
      this.mcpDiscovery.mcpProtocolVersion !== null ||
      this.mcpDiscovery.activeTtlMs !== null
    )
  }

  private handleNonShadowMessage(topic: string, payload: unknown): void {
    if (topic === this.mcpDescriptorTopic) {
      const parsed = parseShadowPayload(payload)
      const descriptor = parseMcpDescriptor(parsed)
      if (descriptor) {
        this.mcpDescriptor = descriptor
        this.resolveMcpDescriptorWaiters()
      }
      if (isRecord(parsed) && typeof parsed.descriptorTopic === 'string' && parsed.descriptorTopic.trim()) {
        this.mcpDiscovery.descriptorTopic = parsed.descriptorTopic
      }
      return
    }

    if (topic === this.mcpStatusTopic) {
      const parsed = parseShadowPayload(payload)
      if (isRecord(parsed) && typeof parsed.available === 'boolean') {
        this.updateMcpAvailability(parsed.available, parsed.observedAtMs ?? parsed.updatedAtMs)
      }
      return
    }

    if (this.mcpSessionId && topic === buildMcpSessionS2cTopic(this.options.thingName, this.mcpSessionId)) {
      this.handleMcpSessionMessage(payload)
    }
  }

  private refreshMcpDiscoveryFromMcpShadow(): void {
    const mcpShadow = this.latestShadows.mcp
    if (!isRecord(mcpShadow) || !isRecord(mcpShadow.state)) {
      return
    }
    const reported = mcpShadow.state.reported
    if (!isRecord(reported)) {
      return
    }
    const descriptor = isRecord(reported.descriptor) ? reported.descriptor : null
    const status = isRecord(reported.status) ? reported.status : null

    if (typeof status?.available === 'boolean') {
      this.updateMcpAvailability(status.available, status.observedAtMs ?? status.updatedAtMs)
    }
    const parsedDescriptor = parseMcpDescriptor(descriptor)
    if (parsedDescriptor) {
      this.mcpDescriptor = parsedDescriptor
      this.resolveMcpDescriptorWaiters()
    }
    this.mcpDiscovery.transport =
      typeof descriptor?.transport === 'string' && descriptor.transport.trim()
        ? descriptor.transport
        : null
    this.mcpDiscovery.mcpProtocolVersion =
      typeof descriptor?.mcpProtocolVersion === 'string' && descriptor.mcpProtocolVersion.trim()
        ? descriptor.mcpProtocolVersion
        : typeof descriptor?.protocolVersion === 'string' && descriptor.protocolVersion.trim()
          ? descriptor.protocolVersion
        : null
    this.mcpDiscovery.descriptorTopic =
      typeof descriptor?.descriptorTopic === 'string' && descriptor.descriptorTopic.trim()
        ? descriptor.descriptorTopic
        : this.mcpDescriptorTopic
    const control = isRecord(descriptor?.control) ? descriptor.control : null
    this.mcpDiscovery.activeTtlMs =
      typeof control?.activeTtlMs === 'number' && Number.isFinite(control.activeTtlMs)
        ? Math.round(control.activeTtlMs)
        : null
    this.mcpDiscovery.serverVersion =
      typeof descriptor?.serverVersion === 'string' && descriptor.serverVersion.trim()
        ? descriptor.serverVersion
        : null
  }

  private handleMcpSessionMessage(payload: unknown): void {
    const parsed = parseShadowPayload(payload)
    if (!isRecord(parsed)) {
      return
    }
    if (typeof parsed.id !== 'number') {
      return
    }
    const pending = this.pendingMcpRequests.get(parsed.id)
    if (!pending) {
      return
    }
    this.pendingMcpRequests.delete(parsed.id)
    window.clearTimeout(pending.timeoutId)
    if (isRecord(parsed.error)) {
      const message =
        typeof parsed.error.message === 'string'
          ? parsed.error.message
          : `MCP request failed with code ${String(parsed.error.code ?? 'unknown')}`
      pending.reject(new Error(message))
      return
    }
    pending.resolve(parsed.result)
  }

  private setLatestRobotState(nextState: RobotState | null): void {
    this.latestRobotState = nextState
    this.options.onRobotStateChange(nextState)
  }

  private setActiveMcpTransport(nextTransport: McpTransportKind | null): void {
    if (this.activeMcpTransport === nextTransport) {
      return
    }
    this.activeMcpTransport = nextTransport
    this.options.onMcpTransportChange(nextTransport)
  }

  private buildLocalRobotControlState(
    activeExpiresAtMs: number | null,
    activeHeldByCaller: boolean,
    activeEpoch: number | null,
  ): RobotControlState {
    const activeTtlMs = this.mcpDescriptor?.activeTtlMs ?? this.mcpDiscovery.activeTtlMs ?? null
    return createDefaultRobotControlState({
      activeTtlMs,
      activeHeldByCaller,
      activeOwnerSessionId: activeHeldByCaller ? this.mcpSessionId : null,
      activeExpiresAtMs,
      activeEpoch,
    })
  }

  private updateRobotStateFromMotionResult(
    motionResult: McpMotionCommandResult,
    activeHeldByCaller: boolean,
  ): void {
    const currentVideo = this.latestRobotState?.video ?? createDefaultRobotVideoState()
    this.setLatestRobotState({
      control: this.buildLocalRobotControlState(
        motionResult.activeExpiresAtMs,
        activeHeldByCaller,
        motionResult.activeEpoch,
      ),
      motion: motionResult.motion,
      video: currentVideo,
    })
  }

  private updateRobotStateToLocalStop(): void {
    const currentVideo = this.latestRobotState?.video ?? createDefaultRobotVideoState()
    this.setLatestRobotState({
      control: this.buildLocalRobotControlState(null, false, null),
      motion: createStoppedRobotMotionState(this.latestRobotState?.motion ?? null),
      video: currentVideo,
    })
  }

  private async publishCmdVelViaMcp(twist: Twist): Promise<void> {
    await this.ensureMcpSessionReady()
    if (isZeroTwist(twist)) {
      if (!this.mcpActiveControl) {
        this.updateRobotStateToLocalStop()
        return
      }
      const epoch = this.mcpActiveControl.epoch
      try {
        const motionResult = parseMcpMotionCommandResult(
          await this.callMcpToolInternal('cmd_vel.stop', {
            epoch,
          }),
        )
        if (!motionResult) {
          throw new Error('MCP cmd_vel.stop returned an invalid payload')
        }
        this.updateRobotStateFromMotionResult(motionResult, true)
      } catch (caughtError) {
        if (
          !isMcpSessionNotInitializedError(caughtError) &&
          !isRecoverableMcpActiveControlError(caughtError)
        ) {
          throw caughtError
        }
        if (isMcpSessionNotInitializedError(caughtError)) {
          this.mcpInitialized = false
        }
        this.mcpActiveControl = null
        this.updateRobotStateToLocalStop()
        return
      }
      await this.releaseMcpControlBestEffort()
      if (this.latestRobotState) {
        this.setLatestRobotState({
          ...this.latestRobotState,
          control: this.buildLocalRobotControlState(null, false, null),
        })
      }
      return
    }

    const active = await this.ensureMcpActiveControl()
    const motionResult = await this.publishCmdVelWithActiveRetry({
      active,
      twist,
    })
    this.updateRobotStateFromMotionResult(motionResult, true)
  }

  private async ensureMcpSessionReady(): Promise<void> {
    if (this.mcpDiscovery.available === false && !this.hasMcpDescriptorHint()) {
      await this.waitForMcpDescriptor(initialMcpDescriptorWaitTimeoutMs)
    }
    if (this.mcpInitialized) {
      return
    }

    if (!this.mcpSessionReadyPromise) {
      const readyPromise = this.initializeMcpSession()
      this.mcpSessionReadyPromise = readyPromise
      void readyPromise.finally(() => {
        if (this.mcpSessionReadyPromise === readyPromise) {
          this.mcpSessionReadyPromise = null
        }
      }).catch(() => undefined)
    }

    await this.mcpSessionReadyPromise
  }

  private async initializeMcpSession(): Promise<void> {
    await this.ensureMcpTransportReady()
    const initializeResult = await this.publishMcpRequest('initialize', {
      protocolVersion: this.mcpDiscovery.mcpProtocolVersion ?? '2026-05-16',
      capabilities: {},
      clientInfo: {
        name: 'txing-web',
        version: appConfig.txingVersion,
      },
    })
    if (!isRecord(initializeResult)) {
      throw new Error('MCP initialize returned an invalid result payload')
    }
    await this.confirmMcpSessionInitialized()
    this.mcpInitialized = true
  }

  private async confirmMcpSessionInitialized(): Promise<void> {
    try {
      await this.publishMcpRequest('tools/list', {})
    } catch (caughtError) {
      if (!isMcpSessionNotInitializedError(caughtError)) {
        throw caughtError
      }
      if (this.activeMcpTransport !== 'mqtt-jsonrpc') {
        throw caughtError
      }
      await this.publishMcpNotification('notifications/initialized', {})
      await this.publishMcpRequest('tools/list', {})
    }
  }

  private async ensureMcpTransportReady(): Promise<void> {
    if (this.activeMcpTransport && this.mcpSessionId) {
      return
    }

    if (shouldAwaitInitialMcpDescriptor(this.mcpDescriptor, this.mcpDiscovery.available)) {
      await this.waitForMcpDescriptor(initialMcpDescriptorWaitTimeoutMs)
    }

    const webRtcTransport = this.mcpWebRtcUnavailable
      ? null
      : selectPreferredMcpWebRtcTransport(this.mcpDescriptor)
    if (webRtcTransport) {
      try {
        const handle = await startBoardMcpDataChannel({
          channelName: webRtcTransport.channelName,
          region: webRtcTransport.region,
          label: webRtcTransport.label,
          resolveIdToken: this.options.resolveIdToken,
          openTimeoutMs: mcpWebRtcOpenTimeoutMs,
        })
        if (this.closed) {
          handle.close()
          throw new Error('Shadow session closed')
        }
        this.mcpWebRtcHandle = handle
        this.mcpSessionId = handle.sessionId
        this.setActiveMcpTransport('webrtc-datachannel')
        return
      } catch {
        this.mcpWebRtcUnavailable = true
        this.closeMcpWebRtcHandle()
      }
    }

    await this.ensureMqttMcpSessionSubscription()
  }

  private async ensureMqttMcpSessionSubscription(): Promise<void> {
    const client = this.client
    if (!client || !this.isConnected()) {
      throw new Error('Shadow connection is not ready')
    }
    if (!this.mcpSessionId) {
      this.mcpSessionId = createMcpSessionId()
    }
    if (this.mcpSessionSubscribed) {
      return
    }
    await client.subscribe(
      {
        subscriptions: [
          {
            topicFilter: buildMcpSessionS2cTopic(this.options.thingName, this.mcpSessionId),
            qos: 1,
          },
        ],
      } as mqtt5.SubscribePacket,
    )
    this.mcpSessionSubscribed = true
    this.setActiveMcpTransport('mqtt-jsonrpc')
  }

  private async ensureMcpActiveControl(): Promise<McpActiveControlState> {
    const nowMs = Date.now()
    const knownActiveTtlMs = this.mcpDescriptor?.activeTtlMs ?? this.mcpDiscovery.activeTtlMs ?? 5_000
    if (this.mcpActiveControl) {
      const activeTtlMs = this.mcpActiveControl.activeTtlMs || knownActiveTtlMs
      const renewBeforeMs = getMcpActiveControlRenewBeforeMs(activeTtlMs)
      if (nowMs < this.mcpActiveControl.expiresAtMs - renewBeforeMs) {
        return this.mcpActiveControl
      }
      const renewed = await this.renewMcpActiveControl(this.mcpActiveControl.epoch)
      this.mcpActiveControl = renewed
      return renewed
    }

    return this.activateMcpControl()
  }

  private async warmUpMcpSession(): Promise<void> {
    if (shouldAwaitInitialMcpDescriptor(this.mcpDescriptor, this.mcpDiscovery.available)) {
      return
    }
    try {
      await this.ensureMcpSessionReady()
    } catch {
      return
    }
  }

  private resolveMcpDescriptorWaiters(): void {
    for (const waiter of [...this.mcpDescriptorWaiters]) {
      this.mcpDescriptorWaiters.delete(waiter)
      waiter(this.mcpDescriptor)
    }
  }

  private async waitForMcpDescriptor(timeoutMs: number): Promise<McpDescriptor | null> {
    if (this.mcpDescriptor) {
      return this.mcpDescriptor
    }

    return new Promise<McpDescriptor | null>((resolve) => {
      let timeoutId: number | null = null
      const resolveWithCurrentDescriptor = (): void => {
        if (timeoutId !== null) {
          window.clearTimeout(timeoutId)
        }
        this.mcpDescriptorWaiters.delete(resolveWithCurrentDescriptor)
        resolve(this.mcpDescriptor)
      }

      if (timeoutMs > 0) {
        timeoutId = window.setTimeout(resolveWithCurrentDescriptor, timeoutMs)
      }
      this.mcpDescriptorWaiters.add(resolveWithCurrentDescriptor)
    })
  }

  private async releaseMcpControlBestEffort(): Promise<void> {
    const active = this.mcpActiveControl
    this.mcpActiveControl = null
    if (!active) {
      return
    }
    try {
      await this.callMcpToolInternal('control.release_active', {
        epoch: active.epoch,
      })
    } catch {
      return
    }
  }

  private async activateMcpControl(): Promise<McpActiveControlState> {
    let acquiredResult: unknown
    try {
      acquiredResult = await this.callMcpToolInternal('control.activate', {
        actor: 'txing-web',
      })
    } catch (caughtError) {
      if (!isMcpSessionNotInitializedError(caughtError)) {
        throw caughtError
      }
      this.mcpInitialized = false
      await this.ensureMcpSessionReady()
      acquiredResult = await this.callMcpToolInternal('control.activate', {
        actor: 'txing-web',
      })
    }
    const knownActiveTtlMs = this.mcpDescriptor?.activeTtlMs ?? this.mcpDiscovery.activeTtlMs ?? 5_000
    const acquired = parseMcpActiveControlState(acquiredResult, knownActiveTtlMs)
    if (!acquired) {
      throw new Error('MCP control.activate returned an invalid payload')
    }
    this.mcpActiveControl = acquired
    return acquired
  }

  private async renewMcpActiveControl(epoch: number): Promise<McpActiveControlState> {
    const knownActiveTtlMs = this.mcpDescriptor?.activeTtlMs ?? this.mcpDiscovery.activeTtlMs ?? 5_000
    const renewed = parseMcpActiveControlState(
      await this.callMcpToolInternal('control.renew_active', { epoch }),
      knownActiveTtlMs,
    )
    if (!renewed) {
      throw new Error('MCP control.renew_active returned an invalid payload')
    }
    return renewed
  }

  private async callCmdVelPublish(epoch: number, twist: Twist): Promise<McpMotionCommandResult> {
    const motionResult = parseMcpMotionCommandResult(
      await this.callMcpToolInternal('cmd_vel.publish', {
        epoch,
        twist,
      }),
    )
    if (!motionResult) {
      throw new Error('MCP cmd_vel.publish returned an invalid payload')
    }
    return motionResult
  }

  private async publishCmdVelWithActiveRetry({
    active,
    twist,
  }: {
    active: McpActiveControlState
    twist: Twist
  }): Promise<McpMotionCommandResult> {
    try {
      return await this.callCmdVelPublish(active.epoch, twist)
    } catch (caughtError) {
      if (
        !isRecoverableMcpActiveControlError(caughtError) &&
        !isMcpSessionNotInitializedError(caughtError)
      ) {
        throw caughtError
      }
      if (isMcpSessionNotInitializedError(caughtError)) {
        this.mcpInitialized = false
      }
      this.mcpActiveControl = null
      const refreshedActive = await this.activateMcpControl()
      return this.callCmdVelPublish(refreshedActive.epoch, twist)
    }
  }

  private async publishCmdVelNow(twist: Twist): Promise<void> {
    if (!this.client || !this.isConnected()) {
      throw new Error('Shadow connection is not ready')
    }
    await this.publishCmdVelViaMcp(twist)
  }

  private sendMcpStopAndReleaseBestEffort(): void {
    const active = this.mcpActiveControl
    if (!active) {
      return
    }
    this.publishMcpToolCallBestEffort('cmd_vel.stop', {
      epoch: active.epoch,
    })
    this.publishMcpToolCallBestEffort('control.release_active', {
      epoch: active.epoch,
    })
    this.mcpActiveControl = null
  }

  private publishMcpToolCallBestEffort(
    name: string,
    argumentsPayload: Record<string, unknown>,
  ): void {
    const sessionId = this.mcpSessionId
    if (!sessionId) {
      return
    }
    const requestId = this.mcpRequestSeq
    this.mcpRequestSeq = (this.mcpRequestSeq + 1) % 1_000_000_000
    const message = {
      jsonrpc: '2.0',
      id: requestId,
      method: 'tools/call',
      params: {
        name,
        arguments: argumentsPayload,
      },
    }

    if (this.activeMcpTransport === 'webrtc-datachannel' && this.mcpWebRtcHandle) {
      void this.mcpWebRtcHandle.notify(message).catch(() => undefined)
      return
    }

    const client = this.client
    if (!client || !this.isConnected()) {
      return
    }
    void client
      .publish(
        {
          topicName: buildMcpSessionC2sTopic(this.options.thingName, sessionId),
          qos: 1,
          payload: new TextEncoder().encode(JSON.stringify(message)),
        } as mqtt5.PublishPacket,
      )
      .catch(() => undefined)
  }

  private async callMcpToolInternal(
    name: string,
    argumentsPayload: Record<string, unknown>,
  ): Promise<unknown> {
    const result = await this.publishMcpRequest('tools/call', {
      name,
      arguments: argumentsPayload,
    })
    if (!isRecord(result)) {
      throw new Error(`MCP tools/call for ${name} returned an invalid result payload`)
    }
    if (result.isError === true) {
      throw new Error(`MCP tools/call for ${name} returned isError=true`)
    }
    if (isRecord(result.structuredContent)) {
      return result.structuredContent
    }
    if (Array.isArray(result.content) && result.content.length > 0 && isRecord(result.content[0])) {
      const firstContent = result.content[0]
      if (isRecord(firstContent.json)) {
        return firstContent.json
      }
    }
    return {}
  }

  private async publishMcpNotification(method: string, params: Record<string, unknown>): Promise<void> {
    if (!this.mcpSessionId) {
      throw new Error('MCP session is not ready')
    }
    const message = {
      jsonrpc: '2.0',
      method,
      params,
    }

    if (this.activeMcpTransport === 'webrtc-datachannel' && this.mcpWebRtcHandle) {
      await this.mcpWebRtcHandle.notify(message)
      return
    }

    const client = this.client
    if (!client || !this.isConnected()) {
      throw new Error('MCP session is not ready')
    }
    await client.publish({
      topicName: buildMcpSessionC2sTopic(this.options.thingName, this.mcpSessionId),
      qos: 1,
      payload: new TextEncoder().encode(JSON.stringify(message)),
    } as mqtt5.PublishPacket)
  }

  private async publishMcpRequest(
    method: string,
    params: Record<string, unknown>,
  ): Promise<unknown> {
    if (!this.mcpSessionId) {
      throw new Error('MCP session is not ready')
    }
    const requestId = this.mcpRequestSeq
    this.mcpRequestSeq = (this.mcpRequestSeq + 1) % 1_000_000_000
    const message = {
      jsonrpc: '2.0',
      id: requestId,
      method,
      params,
    }

    if (this.activeMcpTransport === 'webrtc-datachannel' && this.mcpWebRtcHandle) {
      try {
        return await this.mcpWebRtcHandle.request(message, mcpRequestTimeoutMs)
      } catch (caughtError) {
        const canRetryOverMqtt = !this.mcpActiveControl && !containsMcpActiveEpoch(params)
        this.handleMcpWebRtcFailure()
        if (!canRetryOverMqtt) {
          throw caughtError instanceof Error
            ? caughtError
            : new Error(getErrorMessage(caughtError, `MCP WebRTC request ${method} failed`))
        }
        await this.ensureMqttMcpSessionSubscription()
        if (method !== 'initialize') {
          await this.ensureMcpSessionReady()
        }
        return this.publishMcpRequest(method, params)
      }
    }

    return this.publishMcpRequestOverMqtt(message, method)
  }

  private async publishMcpRequestOverMqtt(
    message: Record<string, unknown> & { id: number },
    method: string,
  ): Promise<unknown> {
    const client = this.client
    if (!client || !this.isConnected() || !this.mcpSessionId) {
      throw new Error('MCP session is not ready')
    }
    const packet = {
      topicName: buildMcpSessionC2sTopic(this.options.thingName, this.mcpSessionId),
      qos: 1,
      payload: new TextEncoder().encode(JSON.stringify(message)),
    } as mqtt5.PublishPacket

    return new Promise<unknown>((resolve, reject) => {
      const timeoutId = window.setTimeout(() => {
        this.pendingMcpRequests.delete(message.id)
        reject(new Error(`Timed out waiting for MCP response to ${method}`))
      }, mcpRequestTimeoutMs)

      this.pendingMcpRequests.set(message.id, {
        resolve,
        reject,
        timeoutId,
      })

      void client.publish(packet).catch((caughtError) => {
        const pending = this.pendingMcpRequests.get(message.id)
        if (!pending) {
          return
        }
        this.pendingMcpRequests.delete(message.id)
        window.clearTimeout(pending.timeoutId)
        pending.reject(new Error(`Unable to publish MCP request ${method}: ${getErrorMessage(caughtError)}`))
      })
    })
  }

  private rejectPendingMcpRequests(error: Error): void {
    for (const [requestId, pending] of [...this.pendingMcpRequests.entries()]) {
      this.pendingMcpRequests.delete(requestId)
      window.clearTimeout(pending.timeoutId)
      pending.reject(error)
    }
  }

  private closeMcpWebRtcHandle(): void {
    if (!this.mcpWebRtcHandle) {
      return
    }
    const handle = this.mcpWebRtcHandle
    this.mcpWebRtcHandle = null
    try {
      handle.close()
    } catch {
      return
    }
  }

  private handleMcpWebRtcFailure(): void {
    this.mcpWebRtcUnavailable = true
    this.closeMcpWebRtcHandle()
    this.mcpActiveControl = null
    this.mcpInitialized = false
    this.mcpSessionReadyPromise = null
    this.mcpSessionSubscribed = false
    this.mcpSessionId = null
    this.setActiveMcpTransport(null)
    this.setLatestRobotState(null)
    this.cmdVelPublisher.clear()
  }

  private resetMcpConnectionState(): void {
    this.closeMcpWebRtcHandle()
    this.mcpSessionReadyPromise = null
    this.mcpActiveControl = null
    this.mcpInitialized = false
    this.mcpSessionSubscribed = false
    this.mcpSessionId = null
    this.setActiveMcpTransport(null)
    this.mcpWebRtcUnavailable = false
    this.mcpRequestSeq = 0
    this.setLatestRobotState(null)
    this.cmdVelPublisher.clear()
  }

  private resolveSnapshotWaiters(shadow: unknown): void {
    for (const waiter of [...this.snapshotWaiters]) {
      if (waiter.predicate(shadow)) {
        waiter.resolve(shadow)
      }
    }
  }

  private rejectSnapshotWaiters(error: Error): void {
    for (const waiter of [...this.snapshotWaiters]) {
      waiter.reject(error)
    }
  }

  private setConnectionState(state: ShadowConnectionState): void {
    this.connectionState = state
    this.options.onConnectionStateChange(state)
  }
}

export const createShadowSessionRuntime = (options: ShadowSessionOptions): ShadowSession =>
  new AwsIotShadowSession(options)
