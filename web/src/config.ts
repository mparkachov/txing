const requireEnv = (name: string): string | null => {
  const value = import.meta.env[name]
  if (typeof value !== 'string' || value.trim() === '') {
    return null
  }

  return value.trim()
}

const toUrl = (value: string | null, fallback: string): string => {
  if (!value) {
    return fallback
  }

  return value.endsWith('/') ? value.slice(0, -1) : value
}

const getRuntimeAppUrl = (): string => {
  if (typeof window === 'undefined') {
    return 'http://localhost/'
  }

  return new URL(import.meta.env.BASE_URL ?? '/', window.location.href).toString()
}

const buildConfig = () => {
  const cognitoDomain = toUrl(requireEnv('VITE_COGNITO_DOMAIN'), '')
  const adminEmail = requireEnv('VITE_ADMIN_EMAIL')?.toLowerCase() ?? ''
  const appUrl = getRuntimeAppUrl()
  const awsRegion = requireEnv('VITE_AWS_REGION') ?? ''
  const cognitoUserPoolId = requireEnv('VITE_COGNITO_USER_POOL_ID') ?? ''
  const cognitoIdentityPoolId = requireEnv('VITE_COGNITO_IDENTITY_POOL_ID') ?? ''
  const iotPolicyName = requireEnv('VITE_IOT_POLICY_NAME') ?? ''
  const thingName = requireEnv('VITE_DEVICE_THING_NAME') ?? 'unit-local'
  const sparkplugGroupId = requireEnv('VITE_SPARKPLUG_GROUP_ID') ?? 'town'
  const sparkplugEdgeNodeId = requireEnv('VITE_SPARKPLUG_EDGE_NODE_ID') ?? 'rig'

  const errors: string[] = []

  if (!awsRegion) {
    errors.push('Missing VITE_AWS_REGION')
  }
  if (!cognitoDomain) {
    errors.push('Missing VITE_COGNITO_DOMAIN')
  }
  if (!requireEnv('VITE_COGNITO_CLIENT_ID')) {
    errors.push('Missing VITE_COGNITO_CLIENT_ID')
  }
  if (!cognitoUserPoolId) {
    errors.push('Missing VITE_COGNITO_USER_POOL_ID')
  }
  if (!cognitoIdentityPoolId) {
    errors.push('Missing VITE_COGNITO_IDENTITY_POOL_ID')
  }
  if (!iotPolicyName) {
    errors.push('Missing VITE_IOT_POLICY_NAME')
  }
  if (!adminEmail) {
    errors.push('Missing VITE_ADMIN_EMAIL')
  }

  return {
    errors,
    awsRegion,
    cognitoIdentityPoolId,
    thingName,
    sparkplugGroupId,
    sparkplugEdgeNodeId,
    adminEmail,
    cognitoDomain,
    cognitoClientId: requireEnv('VITE_COGNITO_CLIENT_ID') ?? '',
    cognitoScope: requireEnv('VITE_COGNITO_SCOPE') ?? 'openid email profile',
    cognitoUserPoolId,
    iotPolicyName,
    appUrl,
  }
}

export const appConfig = buildConfig()
