import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: path.resolve(rootDir, 'plugin.ts'),
      formats: ['es'],
      fileName: 'plugin',
    },
    rollupOptions: {
      external: [
        'react',
        'react-dom',
        'react/jsx-runtime',
        /^@\//,  // Framework UI imports resolved at build-time by the root vite config
      ],
    },
    outDir: 'dist',
    emptyDirFirst: true,
  },
  resolve: {
    alias: {
      '@lumina/plugins': path.resolve(rootDir, '../../../src/web/plugins/types'),
    },
  },
})
