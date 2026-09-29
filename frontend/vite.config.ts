import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * Stable vendor chunks. The charting stack (Recharts and the d3/lodash helpers it pulls in) is the largest
 * dependency by far; keeping it in its own chunk means application code changes do not invalidate it in the
 * browser cache, and the main application chunk stays small. React and the router are separated for the same
 * reason. Everything else (axios, lucide-react icons, app code) stays in the entry chunk and its lazy routes.
 * Dependencies are matched by exact package directory so a chunk never absorbs an unrelated package.
 */
const CHART_PACKAGES = ['recharts', 'recharts-scale', 'victory-vendor', 'react-smooth', 'react-transition-group', 'decimal.js-light', 'eventemitter3', 'fast-equals', 'tiny-invariant', 'lodash', 'clsx', 'prop-types', 'react-is'];
const REACT_PACKAGES = ['react', 'react-dom', 'scheduler', 'react-router', 'react-router-dom', 'cookie', 'set-cookie-parser'];
// Node's process object; declared here so the config type-checks without installing @types/node.
declare const process: { env: Record<string, string | undefined> };

// Where the dev server proxies /api and /ws. Override with VITE_BACKEND_URL when the API is not on port 8000.
const BACKEND_URL = process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';
const packageOf = (id: string) => {
  const match = /node_modules\/((?:@[^/]+\/)?[^/]+)\//.exec(id.replace(/\\/g, '/'));
  return match ? match[1] : null;
};

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const name = packageOf(id);
          if (!name) return undefined;
          if (name.indexOf('d3-') === 0 || CHART_PACKAGES.indexOf(name) !== -1) return 'charts';
          if (REACT_PACKAGES.indexOf(name) !== -1) return 'react';
          return undefined;
        },
      },
    },
  },
  server: { port: 5173, proxy: { '/api': BACKEND_URL, '/ws': { target: BACKEND_URL.replace(/^http/, 'ws'), ws: true } } },
});
