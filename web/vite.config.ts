import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { nodePolyfills } from 'vite-plugin-node-polyfills'

const vmShimPath = fileURLToPath(new URL('./src/vm-shim.ts', import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  base: '/',
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
