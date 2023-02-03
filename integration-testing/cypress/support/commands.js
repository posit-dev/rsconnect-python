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
	cy.request('POST', '/__login__', {
		username: 'admin',
		password: 'password',
	})
});

// Cypress.Commands.add('infoTab', () => {
//   cy.get('a[class="tab info"]').should('be.visible');
//   cy.wait(500);
//   cy.get('a[class="tab info"]').click();
//   cy.wait(500);
// });