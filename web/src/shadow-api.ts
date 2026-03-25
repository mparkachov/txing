import {
  GetIdCommand,
  CognitoIdentityClient,
} from '@aws-sdk/client-cognito-identity'
import { AttachPolicyCommand, IoTClient } from '@aws-sdk/client-iot'
import * as auth from 'aws-crt/dist.browser/browser/auth'
import * as iot from 'aws-crt/dist.browser/browser/iot'
import * as mqtt5 from 'aws-crt/dist.browser/browser/mqtt5'
import { buildCognitoLogins, createCredentialProvider } from './aws-credentials'
import { appConfig } from './config'
import {
  buildGetShadowPublishPacket,
  buildShadowSubscriptionPacket,
  buildShadowTopics,
  buildUpdateShadowPublishPacket,
  createShadowClientToken,
  decodeShadowResponse,
  deriveMqttHostFromIotDataEndpoint,
  type DecodedShadowResponse,
  type ShadowOperation,
  type ShadowTopics,
} from './shadow-protocol'

const forbiddenRetryDelaysMs = [500, 1000, 2000]
const initialSnapshotTimeoutMs = 20_000

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
export type ShadowSessionOptions = {
  thingName: string
  iotDataEndpoint: string
  awsRegion: string
  resolveIdToken: ResolveIdToken
  onShadowDocument: (shadow: unknown, operation: ShadowOperation) => void
  onConnectionStateChange: (state: ShadowConnectionState) => void
  onError: (message: string) => void
}
export type ShadowSession = {
  start: () => Promise<unknown>
  requestSnapshot: () => Promise<unknown>
  updateShadow: (shadowDocument: unknown) => Promise<unknown>
  waitForSnapshot: (
    predicate: (shadow: unknown) => boolean,
    timeoutMs: number,
  ) => Promise<unknown>
  isConnected: () => boolean
  close: () => void
}

let attachedIdentityId: string | null = null
let pendingAttachment: Promise<void> | null = null

const cognitoIdentityClient = new CognitoIdentityClient({
  region: appConfig.awsRegion,
})

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

const getIdentityId = async (idToken: string): Promise<string> => {
  const response = await cognitoIdentityClient.send(
    new GetIdCommand({
      IdentityPoolId: appConfig.cognitoIdentityPoolId,
      Logins: buildCognitoLogins(idToken),
    }),
  )

  if (!response.IdentityId) {
    throw new Error('Cognito identity ID was not returned')
  }

  return response.IdentityId
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

class BrowserCredentialProvider extends auth.CredentialsProvider {
  private credentials: auth.AWSCredentials | undefined
  private readonly resolveIdToken: ResolveIdToken

  constructor(resolveIdToken: ResolveIdToken) {
    super()
    this.resolveIdToken = resolveIdToken
  }

  override getCredentials(): auth.AWSCredentials | undefined {
    return this.credentials
  }

  override async refreshCredentials(): Promise<void> {
    const idToken = await this.resolveIdToken()
    const provider = createCredentialProvider(idToken)
    const credentials = await provider()

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
  private readonly mqttHost: string
  private readonly credentialsProvider: BrowserCredentialProvider
  private client: mqtt5.Mqtt5Client | null = null
  private closed = false
  private connectionState: ShadowConnectionState = 'idle'
  private startPromise: Promise<unknown> | null = null
  private latestShadow: unknown = null
  private readonly pendingRequests = new Map<string, PendingRequest>()
  private readonly snapshotWaiters = new Set<SnapshotWaiter>()
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
    this.setConnectionState('error')
    this.options.onError(`Shadow connection failed: ${getErrorMessage(event.error)}`)
    this.rejectPendingRequests(new Error('Shadow connection failed before response'))
    this.rejectSnapshotWaiters(new Error('Shadow connection failed before response'))
  }
  private readonly handleDisconnection = (event: mqtt5.DisconnectionEvent): void => {
    if (this.closed) {
      return
    }
    this.setConnectionState('error')
    this.options.onError(`Shadow connection lost: ${getErrorMessage(event.error)}`)
    this.rejectPendingRequests(new Error('Shadow connection lost before response'))
    this.rejectSnapshotWaiters(new Error('Shadow connection lost before response'))
  }
  private readonly handleMessageReceived = (event: mqtt5.MessageReceivedEvent): void => {
    if (this.closed) {
      return
    }

    const topic = event.message.topicName ?? ''
    const decoded = decodeShadowResponse(topic, event.message.payload, this.topics)
    if (decoded.kind === 'ignored') {
      return
    }

    if (decoded.kind === 'getAccepted' || decoded.kind === 'updateAccepted') {
      this.latestShadow = decoded.payload
      this.options.onShadowDocument(decoded.payload, decoded.operation ?? 'get')
      this.resolveSnapshotWaiters(decoded.payload)
      if (decoded.clientToken) {
        this.resolvePendingRequest(decoded.clientToken, decoded.payload)
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
    this.mqttHost = deriveMqttHostFromIotDataEndpoint(options.iotDataEndpoint)
    this.credentialsProvider = new BrowserCredentialProvider(options.resolveIdToken)
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
    this.closed = true
    this.setConnectionState('idle')
    this.rejectPendingRequests(new Error('Shadow session closed'))
    this.rejectSnapshotWaiters(new Error('Shadow session closed'))

    if (!this.client) {
      return
    }

    this.client.removeListener('attemptingConnect', this.handleAttemptingConnect)
    this.client.removeListener('connectionSuccess', this.handleConnectionSuccess)
    this.client.removeListener('connectionFailure', this.handleConnectionFailure)
    this.client.removeListener('disconnection', this.handleDisconnection)
    this.client.removeListener('messageReceived', this.handleMessageReceived)
    this.client.stop()
    this.client.close()
    this.client = null
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

    const clientId = await getIdentityId(idToken)
    const builder = iot.AwsIotMqtt5ClientConfigBuilder.newWebsocketMqttBuilderWithSigv4Auth(
      this.mqttHost,
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

    this.client = client
    this.setConnectionState('connecting')
    client.start()

    try {
      return await this.waitForSnapshot(() => true, initialSnapshotTimeoutMs)
    } finally {
      this.startPromise = null
    }
  }

  private async subscribeAndRefresh(): Promise<void> {
    const client = this.client
    if (!client) {
      return
    }

    try {
      await client.subscribe(buildShadowSubscriptionPacket(this.topics) as mqtt5.SubscribePacket)
      if (this.closed || client !== this.client) {
        return
      }
      this.setConnectionState('connected')
      await this.requestSnapshot()
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

export const createShadowSession = (options: ShadowSessionOptions): ShadowSession =>
  new AwsIotShadowSession(options)
