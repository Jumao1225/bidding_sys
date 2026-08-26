/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { type Plugin } from 'vite'

const require = createRequire(import.meta.url)
const pdfjs_dist_path = path.dirname(require.resolve('pdfjs-dist/package.json'))

const pdf_static_asset_directories = [
  { public_path: '/cmaps/', source_dir: path.join(pdfjs_dist_path, 'cmaps') },
  { public_path: '/standard_fonts/', source_dir: path.join(pdfjs_dist_path, 'standard_fonts') },
]

/**
 * 在开发服务器和生产构建中提供 PDF.js 所需的 CMap 与标准字体资源。
 */
function pdf_static_assets_plugin(): Plugin {
  const emit_directory = (plugin_context: { emitFile: (asset: { type: 'asset'; fileName: string; source: Buffer }) => void }, source_dir: string, output_dir: string): void => {
    for (const entry of fs.readdirSync(source_dir, { withFileTypes: true })) {
      const source_path = path.join(source_dir, entry.name)
      const output_path = `${output_dir}/${entry.name}`
      if (entry.isDirectory()) {
        emit_directory(plugin_context, source_path, output_path)
        continue
      }
      plugin_context.emitFile({
        type: 'asset',
        fileName: output_path,
        source: fs.readFileSync(source_path),
      })
    }
  }

  return {
    name: 'pdf-static-assets',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const request_path = decodeURIComponent((request.url || '').split('?')[0])
        const asset_directory = pdf_static_asset_directories.find(({ public_path }) => request_path.startsWith(public_path))
        if (!asset_directory) {
          next()
          return
        }

        const relative_path = request_path.slice(asset_directory.public_path.length)
        const source_path = path.resolve(asset_directory.source_dir, relative_path)
        if (
          !relative_path
          || path.relative(asset_directory.source_dir, source_path).startsWith('..')
          || !fs.existsSync(source_path)
          || !fs.statSync(source_path).isFile()
        ) {
          next()
          return
        }

        response.setHeader('Content-Type', 'application/octet-stream')
        fs.createReadStream(source_path).on('error', next).pipe(response)
      })
    },
    generateBundle() {
      for (const asset_directory of pdf_static_asset_directories) {
        emit_directory(this, asset_directory.source_dir, asset_directory.public_path.slice(1, -1))
      }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  envDir: '../',
  plugins: [react(), pdf_static_assets_plugin()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/uploads': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    }
  }
})
