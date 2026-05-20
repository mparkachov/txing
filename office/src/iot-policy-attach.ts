import {
  GetIdCommand,
  CognitoIdentityClient,
} from '@aws-sdk/client-cognito-identity'
import { AttachPolicyCommand, IoTClient } from '@aws-sdk/client-iot'
import { buildCognitoLogins, createCredentialProvider } from './aws-credentials'
import { appConfig } from './config'

let attachedIdentityId: string | null = null
let pendingAttachment: Promise<void> | null = null
let cachedIdentityIdToken: string | null = null
let cachedIdentityId: string | null = null
let pendingIdentityId: Promise<string> | null = null
let cognitoIdentityClient: CognitoIdentityClient | null = null

const getCognitoIdentityClient = (): CognitoIdentityClient => {
  if (!cognitoIdentityClient) {
    cognitoIdentityClient = new CognitoIdentityClient({
      region: appConfig.awsRegion,
    })
  }
  return cognitoIdentityClient
}

export const getIdentityId = async (idToken: string): Promise<string> => {
  if (cachedIdentityIdToken === idToken && cachedIdentityId) {
    return cachedIdentityId
  }

  if (cachedIdentityIdToken === idToken && pendingIdentityId) {
    return pendingIdentityId
  }

  const identityRequest = getCognitoIdentityClient()
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

export const ensureIotPolicyAttached = async (idToken: string): Promise<boolean> => {
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
