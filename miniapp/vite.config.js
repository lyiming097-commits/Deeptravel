import { defineConfig } from 'vite'
import uniModule from '@dcloudio/vite-plugin-uni'

// Some npm mirrors expose the CommonJS plugin as { default }, while others
// expose the function directly. Supporting both keeps CLI and HBuilderX
// builds deterministic.
const uni = typeof uniModule === 'function' ? uniModule : uniModule.default

export default defineConfig({
  plugins: [uni()],
})
