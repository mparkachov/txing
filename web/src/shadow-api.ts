import {
  GetIdCommand,
  CognitoIdentityClient,
} from '@aws-sdk/client-cognito-identity'
import {
  GetThingShadowCommand,
  IoTDataPlaneClient,
  UpdateThingShadowCommand,
} from '@aws-sdk/client-iot-data-plane'
import { AttachPolicyCommand, IoTClient } from '@aws-sdk/client-iot'
import { fromCognitoIdentityPool } from '@aws-sdk/credential-providers'
import { appConfig } from './config'

const decoder = new TextDecoder()
const encoder = new TextEncoder()
const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))
const forbiddenRetryDelaysMs = [500, 1000, 2000]

let attachedIdentityId: string | null = null
let pendingAttachment: Promise<void> | null = null

const cognitoIdentityClient = new CognitoIdentityClient({
  region: appConfig.awsRegion,
})

const getLogins = (idToken: string): Record<string, string> => ({
  [`cognito-idp.${appConfig.awsRegion}.amazonaws.com/${appConfig.cognitoUserPoolId}`]: idToken,
})

const createCredentialProvider = (idToken: string) =>
  fromCognitoIdentityPool({
    clientConfig: {
      region: appConfig.awsRegion,
    },
    identityPoolId: appConfig.cognitoIdentityPoolId,
    logins: getLogins(idToken),
  })

const createIotDataClient = (idToken: string): IoTDataPlaneClient => {
  const credentials = createCredentialProvider(idToken)

  return new IoTDataPlaneClient({
    region: appConfig.awsRegion,
    endpoint: appConfig.iotDataEndpoint,
    credentials,
  })
}

const getIdentityId = async (idToken: string): Promise<string> => {
  const response = await cognitoIdentityClient.send(
    new GetIdCommand({
      IdentityPoolId: appConfig.cognitoIdentityPoolId,
      Logins: getLogins(idToken),
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

const parsePayload = (payload?: Uint8Array): unknown => {
  if (!payload || payload.length === 0) {
    return {}
  }

  const text = decoder.decode(payload)
  if (!text) {
    return {}
  }

  try {
    return JSON.parse(text)
  } catch {
    return { raw: text }
  }
}

const getErrorMessage = (error: unknown): string => {
  if (error instanceof Error) {
    if (error.name && error.message) {
      return `${error.name}: ${error.message}`
    }
    return error.message
  }

  return 'Thing Shadow request failed'
}

const isForbiddenError = (error: unknown): boolean =>
  error instanceof Error && error.name === 'ForbiddenException'

const runShadowCommand = async <T>(
  send: () => Promise<T>,
  retryForbidden: boolean,
): Promise<T> => {
  try {
    return await send()
  } catch (caughtError) {
    if (!retryForbidden || !isForbiddenError(caughtError)) {
      throw caughtError
    }
  }

  for (const delayMs of forbiddenRetryDelaysMs) {
    await sleep(delayMs)

    try {
      return await send()
    } catch (caughtError) {
      if (!isForbiddenError(caughtError)) {
        throw caughtError
      }
    }
  }

  return send()
}

export const getThingShadow = async (idToken: string): Promise<unknown> => {
  const client = createIotDataClient(idToken)

  try {
    const policyWasAttached = await ensureIotPolicyAttached(idToken)
    const response = await runShadowCommand(
      () =>
        client.send(
          new GetThingShadowCommand({
            thingName: appConfig.thingName,
          }),
        ),
      policyWasAttached,
    )

    return parsePayload(response.payload)
  } catch (caughtError) {
    throw new Error(getErrorMessage(caughtError))
  }
}

export const updateThingShadow = async (idToken: string, shadowDocument: unknown): Promise<unknown> => {
  const client = createIotDataClient(idToken)

  try {
    const policyWasAttached = await ensureIotPolicyAttached(idToken)
    const payload = encoder.encode(JSON.stringify(shadowDocument))
    const response = await runShadowCommand(
      () =>
        client.send(
          new UpdateThingShadowCommand({
            thingName: appConfig.thingName,
            payload,
          }),
        ),
      policyWasAttached,
    )

    return parsePayload(response.payload)
  } catch (caughtError) {
    throw new Error(getErrorMessage(caughtError))
  }
}
