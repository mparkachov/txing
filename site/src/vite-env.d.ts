/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_OFFICE_SIGNIN_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
