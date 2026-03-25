import { fromCognitoIdentityPool } from '@aws-sdk/credential-providers'
import { appConfig } from './config'

export const buildCognitoLogins = (idToken: string): Record<string, string> => ({
  [`cognito-idp.${appConfig.awsRegion}.amazonaws.com/${appConfig.cognitoUserPoolId}`]: idToken,
})

export const createCredentialProvider = (idToken: string) =>
  fromCognitoIdentityPool({
    clientConfig: {
      region: appConfig.awsRegion,
    },
    identityPoolId: appConfig.cognitoIdentityPoolId,
    logins: buildCognitoLogins(idToken),
  })
