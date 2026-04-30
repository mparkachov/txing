import { fromCognitoIdentityPool } from '@aws-sdk/credential-providers'
import { appConfig } from './config'

type CognitoCredentialProvider = ReturnType<typeof fromCognitoIdentityPool>

let cachedCredentialProviderToken: string | null = null
let cachedCredentialProvider: CognitoCredentialProvider | null = null

export const buildCognitoLogins = (idToken: string): Record<string, string> => ({
  [`cognito-idp.${appConfig.awsRegion}.amazonaws.com/${appConfig.cognitoUserPoolId}`]: idToken,
})

export const createCredentialProvider = (idToken: string): CognitoCredentialProvider => {
  if (cachedCredentialProvider && cachedCredentialProviderToken === idToken) {
    return cachedCredentialProvider
  }

  const provider = fromCognitoIdentityPool({
    clientConfig: {
      region: appConfig.awsRegion,
    },
    identityPoolId: appConfig.cognitoIdentityPoolId,
    logins: buildCognitoLogins(idToken),
  })

  cachedCredentialProviderToken = idToken
  cachedCredentialProvider = provider
  return provider
}

export const clearCredentialProviderCache = (): void => {
  cachedCredentialProviderToken = null
  cachedCredentialProvider = null
}
