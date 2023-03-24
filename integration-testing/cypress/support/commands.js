// ***********************************************
// This example commands.js shows you how to
// create various custom commands and overwrite
// existing commands.
//
// For more comprehensive examples of custom
// commands please read more here:
// https://on.cypress.io/custom-commands
// ***********************************************
//
//
// -- This is a parent command --
// Cypress.Commands.add('login', (email, password) => { ... })
//
//
// -- This is a child command --
// Cypress.Commands.add('drag', { prevSubject: 'element'}, (subject, options) => { ... })
//
//
// -- This is a dual command --
// Cypress.Commands.add('dismiss', { prevSubject: 'optional'}, (subject, options) => { ... })
//
//
// -- This will overwrite an existing command --
// Cypress.Commands.overwrite('visit', (originalFn, url, options) => { ... })

// https://www.cypress.io/blog/2020/02/12/working-with-iframes-in-cypress/
Cypress.Commands.add('contentiFrame', (iframe) => {
  // get the iframe > document > body
  // and retry until the body element is not empty
  cy.log('contentiFrame');

  return cy
    .get('iframe.appFrame', { log: false })
    .its('0.contentDocument.body')
    .should('not.be.empty')
    // wraps "body" DOM element to allow
    // chaining more Cypress commands, like ".find(...)"
    // https://on.cypress.io/wrap
    .then((body) => cy.wrap(body, { log: false }));
});

Cypress.Commands.add('connectLogin', (user) => {
  cy.request('POST', 'http://connect:3939/__login__', {
    username: 'admin',
    password: 'password',
  });
});

Cypress.Commands.add('addServer', () => {
    cy.get('button[data-jupyter-action="rsconnect_jupyter:publish"]')
    .click();
    cy.get('a[id="publish-to-connect"]').click({ force: true });
    cy.wait(1000);
    cy.get('input[id="rsc-server"]').clear().type('http://connect:3939');
    cy.get('input[id="rsc-api-key"]').clear().type(Cypress.env('api_key'));
    cy.get('input[id="rsc-servername"]').clear().type('http://connect:3939');
    cy.get('a[class="btn btn-primary"]').contains(' Add Server')
      .click();
    cy.wait(1000);
    cy.get('span[class="help-block"]').should('not.have.text',"Unable to verify");
});

Cypress.Commands.add('removeServer', () => {
    cy.get('button[data-jupyter-action="rsconnect_jupyter:publish"]')
    .click();
    cy.get('a[id="publish-to-connect"]').click({ force: true });
    cy.wait(1000);
    cy.get('div[id="rsc-select-server"]')
      .contains('http://connect:3939')
      .get('button[class="pull-right btn btn-danger btn-xs"]')
      .click();
});

// Cypress.Commands.add('setSessionStorage', (key, value) => {
//   cy.window().then((window) => {
//     window.sessionStorage.setItem(key, value)
//   })
// })