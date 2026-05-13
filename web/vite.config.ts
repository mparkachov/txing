import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { nodePolyfills } from 'vite-plugin-node-polyfills'

const vmShimPath = fileURLToPath(new URL('./src/vm-shim.ts', import.meta.url))
const versionPath = fileURLToPath(new URL('../VERSION', import.meta.url))

const readTxingVersion = (): string => {
  try {
    return readFileSync(versionPath, 'utf-8').trim() || '0.8.0'
  } catch {
    return '0.8.0'
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
    alias: {
      vm: vmShimPath,
      'node:vm': vmShimPath,
    },
  },
})
