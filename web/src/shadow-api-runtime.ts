import {
  GetIdCommand,
  CognitoIdentityClient,
} from '@aws-sdk/client-cognito-identity'
import { AttachPolicyCommand, IoTClient } from '@aws-sdk/client-iot'
import * as auth from 'aws-crt/dist.browser/browser/auth'
import * as iot from 'aws-crt/dist.browser/browser/iot'
import * as mqtt5 from 'aws-crt/dist.browser/browser/mqtt5'
import { LatestAsyncValueRunner } from './async-latest'
import { buildCognitoLogins, createCredentialProvider } from './aws-credentials'
import { isZeroTwist, type Twist } from './cmd-vel'
import { appConfig } from './config'
import { resolveIotDataEndpoint } from './iot-endpoint'
import {
  isMcpSessionNotInitializedError,
  isRecoverableMcpLeaseError,
} from './mcp-errors'
import { getMcpLeaseRenewBeforeMs } from './mcp-lease'
import {
  parseMcpDescriptor,
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
  decodeSparkplugPayload,
  type SparkplugMetric,
  type SparkplugTopics,
} from './sparkplug-protocol'
import {
  extractSparkplugDeviceBatteryMv,
  extractSparkplugDeviceRedconUpdate,
  type SparkplugRedconSource,
} from './sparkplug-device-redcon'
import type {
  RobotControlState,
  RobotMotionState,
  RobotState,
  RobotVideoState,
} from './shadow-api'
import {
  buildGetShadowPublishPacket,
  buildShadowSubscriptionPacket,
  buildShadowTopics,
  buildUpdateShadowPublishPacket,
  createShadowClientToken,
  decodeShadowResponse,
  deriveMqttHostFromIotDataEndpoint,
  parseShadowPayload,
  type DecodedShadowResponse,
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
const mcpWebRtcOpenTimeoutMs = 5_000

export type ShadowConnectionState = 'idle' | 'connecting' | 'connected' | 'error'
type ResolveIdToken = () => Promise<string>
type PendingRequest = {
  operation: ShadowOperation
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
  transport: string | null
  mcpProtocolVersion: string | null
  descriptorTopic: string | null
  leaseRequired: boolean | null
  leaseTtlMs: number | null
  serverVersion: string | null
}
type McpLeaseState = {
  leaseToken: string
  expiresAtMs: number
  leaseTtlMs: number
}
type McpMotionCommandResult = {
  leaseExpiresAtMs: number | null
  motion: RobotMotionState
}
export type ShadowSessionOptions = {
  thingName: string
  awsRegion: string
  sparkplugGroupId: string
  sparkplugEdgeNodeId: string
  resolveIdToken: ResolveIdToken
  onShadowDocument: (shadow: unknown, operation: ShadowOperation) => void
  onSparkplugBatteryMvChange: (batteryMv: number) => void
  onSparkplugRedconChange: (redcon: number, source: SparkplugRedconSource) => void
  onRobotStateChange: (state: RobotState | null) => void
  onConnectionStateChange: (state: ShadowConnectionState) => void
  onError: (message: string) => void
}
export type ShadowSession = {
  start: () => Promise<unknown>
  requestSnapshot: () => Promise<unknown>
  updateShadow: (shadowDocument: unknown) => Promise<unknown>
  publishRedconCommand: (redcon: number) => Promise<void>
  publishCmdVel: (twist: Twist) => Promise<void>
  requestRobotState: () => Promise<RobotState>
  waitForSnapshot: (
    predicate: (shadow: unknown) => boolean,
    timeoutMs: number,
  ) => Promise<unknown>
  isConnected: () => boolean
  close: () => void
}

let attachedIdentityId: string | null = null
let pendingAttachment: Promise<void> | null = null
let cachedIdentityIdToken: string | null = null
let cachedIdentityId: string | null = null
let pendingIdentityId: Promise<string> | null = null

const cognitoIdentityClient = new CognitoIdentityClient({
  region: appConfig.awsRegion,
})

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

const getIdentityId = async (idToken: string): Promise<string> => {
  if (cachedIdentityIdToken === idToken && cachedIdentityId) {
    return cachedIdentityId
  }

  if (cachedIdentityIdToken === idToken && pendingIdentityId) {
    return pendingIdentityId
  }

  const identityRequest = cognitoIdentityClient
    .send(
      new GetIdCommand({
        IdentityPoolId: appConfig.cognitoIdentityPoolId,
        Logins: buildCognitoLogins(idToken),
      }),
    )
    .then((response) => {
      if (!response.IdentityId) {
        throw new Error('Cognito identity ID was not returned')
      }

      cachedIdentityIdToken = idToken
      cachedIdentityId = response.IdentityId
      return response.IdentityId
    })
    .finally(() => {
      if (cachedIdentityIdToken === idToken) {
        pendingIdentityId = null
      }
    })

  cachedIdentityIdToken = idToken
  pendingIdentityId = identityRequest
  return identityRequest
}

const ensureIotPolicyAttached = async (idToken: string): Promise<boolean> => {
  const identityId = await getIdentityId(idToken)

  if (attachedIdentityId === identityId) {
    return false
  }

  if (!pendingAttachment) {
    pendingAttachment = (async () => {
      const iotClient = new IoTClient({
        region: appConfig.awsRegion,
        credentials: createCredentialProvider(idToken),
      })

      await iotClient.send(
        new AttachPolicyCommand({
          policyName: appConfig.iotPolicyName,
          target: identityId,
        }),
      )

      attachedIdentityId = identityId
    })()
      .catch((caughtError) => {
        if (
          caughtError instanceof Error &&
          (caughtError.name === 'ResourceAlreadyExistsException' ||
            caughtError.message.toLowerCase().includes('already'))
        ) {
          attachedIdentityId = identityId
          return
        }

        throw caughtError
      })
      .finally(() => {
        pendingAttachment = null
      })
  }

  await pendingAttachment
  return true
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

const normalizePayloadToBytes = (payload: unknown): Uint8Array => {
  if (payload instanceof Uint8Array) {
    return payload
  }
  if (payload instanceof ArrayBuffer) {
    return new Uint8Array(payload)
  }
  if (ArrayBuffer.isView(payload)) {
    return new Uint8Array(payload.buffer, payload.byteOffset, payload.byteLength)
  }
  if (typeof payload === 'string') {
    return new TextEncoder().encode(payload)
  }
  return new Uint8Array()
}

const normalizeMcpDiscoverySummary = (thingName: string): McpDiscoverySummary => ({
  available: null,
  transport: null,
  mcpProtocolVersion: null,
  descriptorTopic: buildMcpDescriptorTopic(thingName),
  leaseRequired: null,
  leaseTtlMs: null,
  serverVersion: null,
})

const createMcpSessionId = (): string =>
  typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `session-${Date.now()}-${Math.random().toString(16).slice(2)}`

const metricToBoolean = (metric: SparkplugMetric | undefined): boolean | null => {
  if (!metric) {
    return null
  }
  if (typeof metric.boolValue === 'boolean') {
    return metric.boolValue
  }
  if (typeof metric.intValue === 'number') {
    return metric.intValue !== 0
  }
  if (typeof metric.longValue === 'number') {
    return metric.longValue !== 0
  }
  return null
}

const metricToNumber = (metric: SparkplugMetric | undefined): number | null => {
  if (!metric) {
    return null
  }
  if (typeof metric.intValue === 'number') {
    return metric.intValue
  }
  if (typeof metric.longValue === 'number') {
    return metric.longValue
  }
  return null
}

const metricToString = (metric: SparkplugMetric | undefined): string | null => {
  if (!metric) {
    return null
  }
  if (typeof metric.stringValue === 'string' && metric.stringValue.trim()) {
    return metric.stringValue
  }
  return null
}

const containsMcpLeaseToken = (value: unknown, depth = 0): boolean => {
  if (depth > 4 || !isRecord(value)) {
    return false
  }
  if (typeof value.leaseToken === 'string' && value.leaseToken.trim()) {
    return true
  }
  return Object.values(value).some((child) => containsMcpLeaseToken(child, depth + 1))
}

const parseMcpLeaseState = (value: unknown): McpLeaseState | null => {
  if (!isRecord(value)) {
    return null
  }
  const leaseToken = value.leaseToken
  const leaseTtlMs = value.leaseTtlMs
  if (typeof leaseToken !== 'string' || !leaseToken) {
    return null
  }
  if (
    typeof leaseTtlMs !== 'number' ||
    !Number.isFinite(leaseTtlMs) ||
    leaseTtlMs <= 0
  ) {
    return null
  }
  // Use local wall clock for renewal deadlines to avoid board/browser clock skew.
  // Server still enforces the real lease validity; this only drives client renew timing.
  const localExpiresAtMs = Date.now() + Math.round(leaseTtlMs)
  return {
    leaseToken,
    expiresAtMs: localExpiresAtMs,
    leaseTtlMs,
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
  leaseRequired: true,
  leaseTtlMs: null,
  leaseHeldByCaller: false,
  leaseOwnerSessionId: null,
  leaseExpiresAtMs: null,
  ...overrides,
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
  if (
    typeof value.leaseRequired !== 'boolean' ||
    typeof value.leaseHeldByCaller !== 'boolean'
  ) {
    return null
  }
  const leaseTtlMs =
    typeof value.leaseTtlMs === 'number' && Number.isFinite(value.leaseTtlMs) && value.leaseTtlMs > 0
      ? Math.round(value.leaseTtlMs)
      : null
  const leaseExpiresAtMs =
    typeof value.leaseExpiresAtMs === 'number' &&
    Number.isFinite(value.leaseExpiresAtMs) &&
    value.leaseExpiresAtMs >= 0
      ? Math.round(value.leaseExpiresAtMs)
      : null
  const leaseOwnerSessionId =
    typeof value.leaseOwnerSessionId === 'string' && value.leaseOwnerSessionId.trim()
      ? value.leaseOwnerSessionId
      : null
  return {
    leaseRequired: value.leaseRequired,
    leaseTtlMs,
    leaseHeldByCaller: value.leaseHeldByCaller,
    leaseOwnerSessionId,
    leaseExpiresAtMs,
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
  const leaseExpiresAtMs =
    typeof value.leaseExpiresAtMs === 'number' &&
    Number.isFinite(value.leaseExpiresAtMs) &&
    value.leaseExpiresAtMs >= 0
      ? Math.round(value.leaseExpiresAtMs)
      : null
  return {
    leaseExpiresAtMs,
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
  private readonly topics: ShadowTopics
  private readonly sparkplugTopics: SparkplugTopics
  private readonly mcpDescriptorTopic: string
  private readonly mcpStatusTopic: string
  private readonly credentialsProvider: BrowserCredentialProvider
  private client: mqtt5.Mqtt5Client | null = null
  private closed = false
  private connectionState: ShadowConnectionState = 'idle'
  private startPromise: Promise<unknown> | null = null
  private latestShadow: unknown = null
  private sparkplugCommandSeq = 0
  private suppressConnectionErrors = false
  private readonly pendingRequests = new Map<string, PendingRequest>()
  private readonly snapshotWaiters = new Set<SnapshotWaiter>()
  private readonly pendingMcpRequests = new Map<number, PendingMcpRequest>()
  private mcpRequestSeq = 0
  private mcpDiscovery: McpDiscoverySummary
  private mcpDescriptor: McpDescriptor | null = null
  private mcpLease: McpLeaseState | null = null
  private latestRobotState: RobotState | null = null
  private mcpSessionId: string | null = null
  private mcpSessionSubscribed = false
  private mcpInitialized = false
  private activeMcpTransport: McpTransportKind | null = null
  private mcpWebRtcHandle: McpDataChannelHandle | null = null
  private mcpWebRtcUnavailable = false
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
    const decoded = decodeShadowResponse(topic, event.message.payload, this.topics)
    if (decoded.kind === 'ignored') {
      this.handleNonShadowMessage(topic, event.message.payload)
      return
    }

    if (decoded.kind === 'getAccepted' || decoded.kind === 'updateAccepted') {
      const nextShadow =
        decoded.kind === 'updateAccepted'
          ? mergeShadowUpdate(this.latestShadow, decoded.payload)
          : decoded.payload
      this.latestShadow = nextShadow
      this.options.onShadowDocument(nextShadow, decoded.operation ?? 'get')
      this.resolveSnapshotWaiters(nextShadow)
      if (decoded.clientToken) {
        this.resolvePendingRequest(decoded.clientToken, nextShadow)
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
    this.topics = buildShadowTopics(options.thingName)
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

    if (this.latestShadow !== null) {
      return this.latestShadow
    }

    if (!this.startPromise) {
      this.startPromise = this.open()
    }

    return this.startPromise
  }

  async requestSnapshot(): Promise<unknown> {
    const clientToken = createShadowClientToken('get')
    const packet = buildGetShadowPublishPacket(this.topics, clientToken)
    return this.publishRequest('get', clientToken, packet)
  }

  async updateShadow(shadowDocument: unknown): Promise<unknown> {
    const clientToken = createShadowClientToken('update')
    const packet = buildUpdateShadowPublishPacket(this.topics, shadowDocument, clientToken)
    return this.publishRequest('update', clientToken, packet)
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
    await client.publish(packet as mqtt5.PublishPacket)
  }

  async publishCmdVel(twist: Twist): Promise<void> {
    return this.cmdVelPublisher.push(twist)
  }

  async requestRobotState(): Promise<RobotState> {
    if (this.pendingMcpRequests.size > 0 && this.latestRobotState) {
      return this.latestRobotState
    }
    await this.ensureMcpSessionReady()
    const robotState = parseRobotState(await this.callMcpTool('robot.get_state', {}))
    if (!robotState) {
      throw new Error('MCP robot.get_state returned an invalid payload')
    }
    this.setLatestRobotState(robotState)
    return robotState
  }

  async waitForSnapshot(
    predicate: (shadow: unknown) => boolean,
    timeoutMs: number,
  ): Promise<unknown> {
    if (this.latestShadow !== null && predicate(this.latestShadow)) {
      return this.latestShadow
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
      return await this.waitForSnapshot(() => true, initialSnapshotTimeoutMs)
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
      await client.subscribe(buildShadowSubscriptionPacket(this.topics) as mqtt5.SubscribePacket)
      await client.subscribe(
        {
          subscriptions: [
            { topicFilter: this.sparkplugTopics.dbirth, qos: 1 },
            { topicFilter: this.sparkplugTopics.ddata, qos: 1 },
            { topicFilter: this.sparkplugTopics.ddeath, qos: 1 },
            { topicFilter: this.mcpDescriptorTopic, qos: 1 },
            { topicFilter: this.mcpStatusTopic, qos: 1 },
          ],
        } as mqtt5.SubscribePacket,
      )
      if (this.closed || client !== this.client) {
        return
      }
      this.setConnectionState('connected')
      await this.requestSnapshot()
      void this.warmUpMcpSession()
    } catch (caughtError) {
      this.setConnectionState('error')
      this.options.onError(`Unable to subscribe to shadow topics: ${getErrorMessage(caughtError)}`)
      this.rejectSnapshotWaiters(
        new Error(`Unable to subscribe to shadow topics: ${getErrorMessage(caughtError)}`),
      )
    }
  }

  private async publishRequest(
    operation: ShadowOperation,
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
        resolve,
        reject,
      })

      void client.publish(packet).catch((caughtError) => {
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

  private handleNonShadowMessage(topic: string, payload: unknown): void {
    this.handleSparkplugDeviceRedcon(topic, payload)

    if (this.handleSparkplugMcpDiscovery(topic, payload)) {
      return
    }

    if (topic === this.mcpDescriptorTopic) {
      const parsed = parseShadowPayload(payload)
      const descriptor = parseMcpDescriptor(parsed)
      if (descriptor) {
        this.mcpDescriptor = descriptor
      }
      if (isRecord(parsed) && typeof parsed.descriptorTopic === 'string' && parsed.descriptorTopic.trim()) {
        this.mcpDiscovery.descriptorTopic = parsed.descriptorTopic
      }
      return
    }

    if (topic === this.mcpStatusTopic) {
      const parsed = parseShadowPayload(payload)
      if (isRecord(parsed) && typeof parsed.available === 'boolean') {
        this.mcpDiscovery.available = parsed.available
      }
      return
    }

    if (this.mcpSessionId && topic === buildMcpSessionS2cTopic(this.options.thingName, this.mcpSessionId)) {
      this.handleMcpSessionMessage(payload)
    }
  }

  private handleSparkplugDeviceRedcon(topic: string, payload: unknown): void {
    const batteryMv = extractSparkplugDeviceBatteryMv(
      topic,
      normalizePayloadToBytes(payload),
      this.sparkplugTopics,
    )
    if (batteryMv !== null) {
      this.options.onSparkplugBatteryMvChange(batteryMv)
    }

    const nextRedcon = extractSparkplugDeviceRedconUpdate(
      topic,
      normalizePayloadToBytes(payload),
      this.sparkplugTopics,
    )
    if (!nextRedcon) {
      return
    }
    this.options.onSparkplugRedconChange(nextRedcon.redcon, nextRedcon.source)
  }

  private handleSparkplugMcpDiscovery(topic: string, payload: unknown): boolean {
    if (topic !== this.sparkplugTopics.dbirth && topic !== this.sparkplugTopics.ddata) {
      return false
    }

    let decoded
    try {
      decoded = decodeSparkplugPayload(normalizePayloadToBytes(payload))
    } catch {
      return true
    }

    const metricsByName = new Map<string, SparkplugMetric>()
    for (const metric of decoded.metrics) {
      metricsByName.set(metric.name, metric)
    }
    if (!metricsByName.has('services/mcp/available')) {
      return true
    }

    this.mcpDiscovery.available = metricToBoolean(metricsByName.get('services/mcp/available'))
    this.mcpDiscovery.transport = metricToString(metricsByName.get('services/mcp/transport'))
    this.mcpDiscovery.mcpProtocolVersion = metricToString(
      metricsByName.get('services/mcp/mcpProtocolVersion'),
    )
    this.mcpDiscovery.descriptorTopic =
      metricToString(metricsByName.get('services/mcp/descriptorTopic')) ?? this.mcpDescriptorTopic
    this.mcpDiscovery.leaseRequired = metricToBoolean(metricsByName.get('services/mcp/leaseRequired'))
    this.mcpDiscovery.leaseTtlMs = metricToNumber(metricsByName.get('services/mcp/leaseTtlMs'))
    this.mcpDiscovery.serverVersion = metricToString(metricsByName.get('services/mcp/serverVersion'))
    return true
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

  private buildLocalRobotControlState(
    leaseExpiresAtMs: number | null,
    leaseHeldByCaller: boolean,
  ): RobotControlState {
    const leaseTtlMs = this.mcpDescriptor?.leaseTtlMs ?? this.mcpDiscovery.leaseTtlMs ?? null
    return createDefaultRobotControlState({
      leaseTtlMs,
      leaseHeldByCaller,
      leaseOwnerSessionId: leaseHeldByCaller ? this.mcpSessionId : null,
      leaseExpiresAtMs,
    })
  }

  private updateRobotStateFromMotionResult(
    motionResult: McpMotionCommandResult,
    leaseHeldByCaller: boolean,
  ): void {
    const currentVideo = this.latestRobotState?.video ?? createDefaultRobotVideoState()
    this.setLatestRobotState({
      control: this.buildLocalRobotControlState(motionResult.leaseExpiresAtMs, leaseHeldByCaller),
      motion: motionResult.motion,
      video: currentVideo,
    })
  }

  private async publishCmdVelViaMcp(twist: Twist): Promise<void> {
    await this.ensureMcpSessionReady()
    if (isZeroTwist(twist)) {
      if (!this.mcpLease) {
        return
      }
      const leaseToken = this.mcpLease.leaseToken
      try {
        const motionResult = parseMcpMotionCommandResult(
          await this.callMcpTool('cmd_vel.stop', {
            leaseToken,
          }),
        )
        if (!motionResult) {
          throw new Error('MCP cmd_vel.stop returned an invalid payload')
        }
        this.updateRobotStateFromMotionResult(motionResult, true)
      } catch (caughtError) {
        if (
          !isMcpSessionNotInitializedError(caughtError) &&
          !isRecoverableMcpLeaseError(caughtError)
        ) {
          throw caughtError
        }
        if (isMcpSessionNotInitializedError(caughtError)) {
          this.mcpInitialized = false
        }
        this.mcpLease = null
        return
      }
      await this.releaseMcpControlBestEffort()
      if (this.latestRobotState) {
        this.setLatestRobotState({
          ...this.latestRobotState,
          control: this.buildLocalRobotControlState(null, false),
        })
      }
      return
    }

    const lease = await this.ensureMcpLease()
    const motionResult = await this.publishCmdVelWithLeaseRetry({
      lease,
      twist,
    })
    this.updateRobotStateFromMotionResult(motionResult, true)
  }

  private async ensureMcpSessionReady(): Promise<void> {
    if (this.mcpDiscovery.available === false) {
      throw new Error('MCP service is currently unavailable')
    }
    if (this.mcpInitialized) {
      return
    }

    await this.ensureMcpTransportReady()
    const initializeResult = await this.publishMcpRequest('initialize', {
      protocolVersion: this.mcpDiscovery.mcpProtocolVersion ?? '2025-11-25',
      capabilities: {},
      clientInfo: {
        name: 'txing-web',
        version: '0.2.0',
      },
    })
    if (!isRecord(initializeResult)) {
      throw new Error('MCP initialize returned an invalid result payload')
    }
    await this.publishMcpNotification('notifications/initialized', {})
    this.mcpInitialized = true
  }

  private async ensureMcpTransportReady(): Promise<void> {
    if (this.activeMcpTransport && this.mcpSessionId) {
      return
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
        this.activeMcpTransport = 'webrtc-datachannel'
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
    this.activeMcpTransport = 'mqtt-jsonrpc'
  }

  private async ensureMcpLease(): Promise<McpLeaseState> {
    const nowMs = Date.now()
    const knownLeaseTtlMs = this.mcpDescriptor?.leaseTtlMs ?? this.mcpDiscovery.leaseTtlMs ?? 5_000
    if (this.mcpLease) {
      const activeLeaseTtlMs = this.mcpLease.leaseTtlMs || knownLeaseTtlMs
      const renewBeforeMs = getMcpLeaseRenewBeforeMs(activeLeaseTtlMs)
      if (nowMs < this.mcpLease.expiresAtMs - renewBeforeMs) {
        return this.mcpLease
      }
    }

    return this.acquireMcpLease()
  }

  private async warmUpMcpSession(): Promise<void> {
    try {
      await this.ensureMcpSessionReady()
    } catch {
      return
    }
  }

  private async releaseMcpControlBestEffort(): Promise<void> {
    const lease = this.mcpLease
    this.mcpLease = null
    if (!lease) {
      return
    }
    try {
      await this.callMcpTool('control.release_lease', {
        leaseToken: lease.leaseToken,
      })
    } catch {
      return
    }
  }

  private async acquireMcpLease(): Promise<McpLeaseState> {
    let acquiredResult: unknown
    try {
      acquiredResult = await this.callMcpTool('control.acquire_lease', {})
    } catch (caughtError) {
      if (!isMcpSessionNotInitializedError(caughtError)) {
        throw caughtError
      }
      this.mcpInitialized = false
      await this.ensureMcpSessionReady()
      acquiredResult = await this.callMcpTool('control.acquire_lease', {})
    }
    const acquired = parseMcpLeaseState(acquiredResult)
    if (!acquired) {
      throw new Error('MCP control.acquire_lease returned an invalid payload')
    }
    this.mcpLease = acquired
    return acquired
  }

  private async callCmdVelPublish(
    leaseToken: string,
    twist: Twist,
  ): Promise<McpMotionCommandResult> {
    const motionResult = parseMcpMotionCommandResult(
      await this.callMcpTool('cmd_vel.publish', {
        leaseToken,
        twist,
      }),
    )
    if (!motionResult) {
      throw new Error('MCP cmd_vel.publish returned an invalid payload')
    }
    return motionResult
  }

  private async publishCmdVelWithLeaseRetry({
    lease,
    twist,
  }: {
    lease: McpLeaseState
    twist: Twist
  }): Promise<McpMotionCommandResult> {
    try {
      return await this.callCmdVelPublish(lease.leaseToken, twist)
    } catch (caughtError) {
      if (
        !isRecoverableMcpLeaseError(caughtError) &&
        !isMcpSessionNotInitializedError(caughtError)
      ) {
        throw caughtError
      }
      if (isMcpSessionNotInitializedError(caughtError)) {
        this.mcpInitialized = false
      }
      this.mcpLease = null
      const refreshedLease = await this.acquireMcpLease()
      return this.callCmdVelPublish(refreshedLease.leaseToken, twist)
    }
  }

  private async publishCmdVelNow(twist: Twist): Promise<void> {
    if (!this.client || !this.isConnected()) {
      throw new Error('Shadow connection is not ready')
    }
    await this.publishCmdVelViaMcp(twist)
  }

  private sendMcpStopAndReleaseBestEffort(): void {
    const lease = this.mcpLease
    if (!lease) {
      return
    }
    this.publishMcpToolCallBestEffort('cmd_vel.stop', {
      leaseToken: lease.leaseToken,
    })
    this.publishMcpToolCallBestEffort('control.release_lease', {
      leaseToken: lease.leaseToken,
    })
    this.mcpLease = null
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

  private async callMcpTool(name: string, argumentsPayload: Record<string, unknown>): Promise<unknown> {
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
        const canRetryOverMqtt = !this.mcpLease && !containsMcpLeaseToken(params)
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
    this.mcpLease = null
    this.mcpInitialized = false
    this.mcpSessionSubscribed = false
    this.mcpSessionId = null
    this.activeMcpTransport = null
    this.setLatestRobotState(null)
    this.cmdVelPublisher.clear()
  }

  private resetMcpConnectionState(): void {
    this.closeMcpWebRtcHandle()
    this.mcpLease = null
    this.mcpInitialized = false
    this.mcpSessionSubscribed = false
    this.mcpSessionId = null
    this.activeMcpTransport = null
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
