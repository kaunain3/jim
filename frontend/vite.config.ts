import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config

function apiProxy(target: string) {
  return {
    target,
    changeOrigin: true,
    
    bypass(req: any) {
      const accept = req.headers?.accept || '';
      if (accept.includes('text/html')) {
        return req.url; 
      }
    },
  };
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    open: true,
    proxy: {
      '/papers': apiProxy('http://localhost:8000'),
      '/ask': apiProxy('http://localhost:8000'),
      '/discover': apiProxy('http://localhost:8000'),
      '/jobs': apiProxy('http://localhost:8000'),
      '/health': apiProxy('http://localhost:8000'),
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});