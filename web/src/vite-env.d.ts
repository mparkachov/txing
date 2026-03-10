/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AWS_REGION?: string
  readonly VITE_COGNITO_CLIENT_ID?: string
  readonly VITE_COGNITO_DOMAIN?: string
  readonly VITE_COGNITO_IDENTITY_POOL_ID?: string
  readonly VITE_COGNITO_USER_POOL_ID?: string
  readonly VITE_COGNITO_SCOPE?: string
  readonly VITE_ADMIN_EMAIL?: string
  readonly VITE_IOT_DATA_ENDPOINT?: string
  readonly VITE_IOT_POLICY_NAME?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
