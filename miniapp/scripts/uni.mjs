// The repository keeps the small-program source at miniapp/ for a compact
// standalone package. uni's CLI defaults to miniapp/src/, so set its input
// directory explicitly before loading the CLI entry point.
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

process.env.UNI_INPUT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '../src')
await import('@dcloudio/vite-plugin-uni/bin/uni.js')
