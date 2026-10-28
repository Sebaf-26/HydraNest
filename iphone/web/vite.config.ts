import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  // HydraNest: relative asset paths, so the same build also serves under
  // HydraNest's /iphone/app/ (routing is by hash).
  base: './',
  plugins: [tailwindcss(), svelte()],
  server: {
    host: '127.0.0.1',
    port: 8080,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8081',
      '/healthz': 'http://127.0.0.1:8081',
    },
  },
});
