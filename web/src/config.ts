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
  const url = new URL(window.location.href)
  url.search = ''
  url.hash = ''

  if (url.pathname.endsWith('/index.html')) {
    url.pathname = url.pathname.slice(0, -'index.html'.length)
  } else if (!url.pathname.endsWith('/')) {
    const lastSegment = url.pathname.split('/').pop() ?? ''
    if (!lastSegment.includes('.')) {
      url.pathname = `${url.pathname}/`
    }
  }

  return url.toString()
}

const buildConfig = () => {
  const cognitoDomain = toUrl(requireEnv('VITE_COGNITO_DOMAIN'), '')
  const iotDataEndpoint = toUrl(requireEnv('VITE_IOT_DATA_ENDPOINT'), '')
  const adminEmail = requireEnv('VITE_ADMIN_EMAIL')?.toLowerCase() ?? ''
  const appUrl = getRuntimeAppUrl()
  const awsRegion = requireEnv('VITE_AWS_REGION') ?? ''
  const cognitoUserPoolId = requireEnv('VITE_COGNITO_USER_POOL_ID') ?? ''
  const cognitoIdentityPoolId = requireEnv('VITE_COGNITO_IDENTITY_POOL_ID') ?? ''
  const iotPolicyName = requireEnv('VITE_IOT_POLICY_NAME') ?? ''

  const errors: string[] = []

  if (!awsRegion) {
    errors.push('Missing VITE_AWS_REGION')
  }
  if (!iotDataEndpoint) {
    errors.push('Missing VITE_IOT_DATA_ENDPOINT')
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
    thingName: 'txing',
    adminEmail,
    cognitoDomain,
    cognitoClientId: requireEnv('VITE_COGNITO_CLIENT_ID') ?? '',
    cognitoScope: requireEnv('VITE_COGNITO_SCOPE') ?? 'openid email profile',
    cognitoUserPoolId,
    iotPolicyName,
    iotDataEndpoint,
    appUrl,
  }
}

export const appConfig = buildConfig()
