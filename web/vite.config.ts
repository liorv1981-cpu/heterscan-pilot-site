import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => ({
  base: process.env.VITE_BASE_PATH || loadEnv(mode, process.cwd()).VITE_BASE_PATH || '/',
  plugins: [react()],
  server: { port: 4173, host: '127.0.0.1' },
  preview: { port: 4173, host: '127.0.0.1' },
}))
