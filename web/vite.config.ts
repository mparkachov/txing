import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { nodePolyfills } from 'vite-plugin-node-polyfills'

const vmShimPath = fileURLToPath(new URL('./src/vm-shim.ts', import.meta.url))
const versionPath = fileURLToPath(new URL('../VERSION', import.meta.url))
const reactPath = fileURLToPath(new URL('./node_modules/react/index.js', import.meta.url))
const reactJsxRuntimePath = fileURLToPath(
  new URL('./node_modules/react/jsx-runtime.js', import.meta.url),
)
const reactJsxDevRuntimePath = fileURLToPath(
  new URL('./node_modules/react/jsx-dev-runtime.js', import.meta.url),
)
const reactDomPath = fileURLToPath(new URL('./node_modules/react-dom/index.js', import.meta.url))
const reactDomClientPath = fileURLToPath(
  new URL('./node_modules/react-dom/client.js', import.meta.url),
)

const readTxingVersion = (): string => {
  try {
    return readFileSync(versionPath, 'utf-8').trim() || '0.9.111'
  } catch {
    return '0.9.111'
  }
}

// https://vite.dev/config/
export default defineConfig({
  base: '/',
  define: {
    __TXING_VERSION__: JSON.stringify(readTxingVersion()),
  },
  plugins: [
    react(),
    nodePolyfills({
      globals: {
        Buffer: true,
        global: true,
        process: true,
      },
      overrides: {
        vm: vmShimPath,
      },
      protocolImports: true,
    }),
  ],
  build: {
    chunkSizeWarningLimit: 1300,
  },
  resolve: {
    alias: [
      { find: 'react/jsx-runtime', replacement: reactJsxRuntimePath },
      { find: 'react/jsx-dev-runtime', replacement: reactJsxDevRuntimePath },
      { find: 'react-dom/client', replacement: reactDomClientPath },
      { find: 'react-dom', replacement: reactDomPath },
      { find: 'react', replacement: reactPath },
      { find: 'vm', replacement: vmShimPath },
      { find: 'node:vm', replacement: vmShimPath },
    ],
    dedupe: ['react', 'react-dom'],
  },
})
