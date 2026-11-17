import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
export default defineConfig({plugins:[vue(),tailwindcss()],server:{port:5173,host:'127.0.0.1',proxy:{'/api':{target:`http://127.0.0.1:${process.env.UNKNOWN_API_PORT||'8000'}`,changeOrigin:true}}},build:{chunkSizeWarningLimit:1000,rollupOptions:{output:{manualChunks:{echarts:['echarts']}}}}})
