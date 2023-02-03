describe('Jupyter Loads', () => {
  beforeEach(() => {
    cy.visit('http://' + (Cypress.env('host') + ':9999/notebooks/content/notebook/stock-report-jupyter.ipynb'))
  });

  it('Publish Button exists', () => {
    cy.get('button[data-jupyter-action="rsconnect_jupyter:publish"]').click();
    cy.get('a[id="publish-to-connect"]').should('be.visible')
  });

  it('Add Server', () => {
    cy.get('a[id="publish-to-connect"]').click({ force: true });
    cy.get('a[id="rsc-add-server"]').should('be.visible');
    cy.wait(500);
    cy.get('a[id="rsc-add-server"]').click({ force: true });
    cy.wait(5000);
    cy.get('input[id="rsc-server"]').click();
    cy.wait(10);
    cy.get('input[id="rsc-server"]').type('http://localhost:3939{enter}')
    cy.get('input[id="rsc-api-key"]').click();
    cy.wait(50);
    cy.get('input[id="rsc-api-key"]').type('21232f297a57a5a743894a0e4a801fc3{enter}');
    cy.get('input[id="rsc-servername"]').click();
    cy.wait(10);
    cy.get('input[id="rsc-servername"]').type('localhost{enter}');
    cy.wait(10);
    cy.get('a[class="btn btn-primary"]').contains(' Add Server').click();
    cy.wait(5000);
  });

  // it('Publish Content', () => {

  // }

  // it('Add Server', () => {
    
  // });

  // it('Dash Pages application is interactive', () => {
  //   cy.contentiFrame().find('h1[id="home_page"]')
  //     .should('have.text',"This is our Home page");
  //   // click on the Analytics page
  //   cy.contentiFrame().find('a[id="Analytics"]')
  //     .click();
  //   cy.contentiFrame().find('h1[id="analytics_page"]')
  //     .should('have.text',"This is our Analytics page");

  //   // click on the Archive page
  //   cy.contentiFrame().find('a[id="Archive"]')
  //     .click();
  //   cy.contentiFrame().find('h1[id="archive_page"]')
  //     .should('have.text',"This is our Archive page");

  //   // click back on Home page
  //   cy.contentiFrame().find('a[id="Home"]')
  //     .click();
  //   cy.contentiFrame().find('h1[id="home_page"]')
  //     .should('have.text',"This is our Home page");
  // });

  // it('Dash Pages has the right Content Type and Python Version', () => {
  //   cy.visit(Cypress.env('content_url')+'/info');
  //   cy.get('div[data-automation="settings-info-type"]').contains('Content Type: Dash application');
  //   cy.get('div[data-automation="settings-info-pyversion"]').contains(Cypress.env('pyversion'));
  // });
});