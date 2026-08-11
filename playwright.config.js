const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './e2e',
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: process.env.BARSAN_E2E_BASE_URL || 'http://127.0.0.1:18081',
    headless: true,
  },
  reporter: [['list']],
});
