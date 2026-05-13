import './style.css'

const defaultOfficeSignInUrl = 'https://office.txing.dev/?signin=1'

const normalizeSignInUrl = (value: string | undefined): string => {
  const candidate = value?.trim()
  if (!candidate) {
    return defaultOfficeSignInUrl
  }

  try {
    const url = new URL(candidate)
    return url.toString()
  } catch {
    return defaultOfficeSignInUrl
  }
}

const officeSignInUrl = normalizeSignInUrl(import.meta.env.VITE_OFFICE_SIGNIN_URL)

document.querySelectorAll<HTMLAnchorElement>('[data-office-signin]').forEach((link) => {
  link.href = officeSignInUrl
})
