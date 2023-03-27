// {
//   "testFiles": "**/*.spec.js",
//   "defaultCommandTimeout": 10000,
//   "responseTimeout": 60000,
//   "integrationFolder": "./cypress/integration/",
//   "viewportHeight": 800
// }

const { defineConfig } = require('cypress')

module.exports = defineConfig({
  defaultCommandTimeout: 10000,
  responseTimeout: 60000,
  component: {
    viewportHeight: 800
  },
  e2e: {
    defaultCommandTimeout: 10000,
    specPattern: "cypress/e2e/**/*.cy.js",
  },
  "retries": 2
})
