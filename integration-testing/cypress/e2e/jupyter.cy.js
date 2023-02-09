describe('Publishing Jupyter Notebook', () => {

  it('Publish button loads', () => {
    cy.visit('http://client:9999/tree/integration-testing/content/notebook/stock-report-jupyter.ipynb');
    cy.get('button[data-jupyter-action="rsconnect_jupyter:publish"]').click();
    cy.get('a[id="publish-to-connect"]').should('be.visible')
  });
  // wait is required after every action, cypress is too fast for jupyter
  // https://github.com/cypress-io/cypress/issues/249
  it('Add Server', () => {
    cy.visit('http://client:9999/tree/integration-testing/content/notebook/stock-report-jupyter.ipynb');
    cy.wait(1000);
    cy.get('a[id="publish-to-connect"]').click({ force: true });
    cy.wait(1000);
    cy.get('input[id="rsc-server"]').clear().type('http://connect:3939');
    cy.get('input[id="rsc-api-key"]').clear().type(Cypress.env('api_key'));
    cy.get('input[id="rsc-servername"]').clear().type('localhost');
    cy.get('a[class="btn btn-primary"]').contains(' Add Server').click();
    cy.wait(1000);
    cy.get('span[class="help-block"]').should('not.have.text',"Unable to verify");
  });
  it('Publish Content', () => {
    cy.visit('http://client:9999/tree/integration-testing/content/notebook/stock-report-jupyter.ipynb');
    cy.wait(1000);
    cy.get('a[id="publish-to-connect"]').click({ force: true });
    cy.wait(1000);
    cy.get('button[id="rsc-add-files"]').click();
    cy.wait(1000);
    cy.get('input[name="quandl-wiki-tsla.json.gz"]').click();
    cy.wait(1000);
    cy.get('button[id="add-files-dialog-accept"]').click();
    cy.wait(1000);
    cy.get('li[class="list-group-item"]').first().should('have.text'," quandl-wiki-tsla.json.gz");
    cy.wait(1000);
    cy.get('a[class="btn btn-primary"]').last().should('have.text',"Publish").click({ force: true });
    cy.wait(1000);
    cy.get('input[name="location"]').first().click();
    cy.wait(1000);
    cy.get('a[class="btn btn-primary"]').last().should('have.text',"Next").click();
    cy.wait(1000);
    cy.get('a[class="btn btn-primary"]').last().should('have.text',"Publish").click();
    cy.wait(1000);
    // allow for 5 minutes to deploy content
    cy.get('span[class="fa fa-link"]', { timeout: 300000 }).last().should('have.text'," Successfully published content").click();
  });
  it('Vist Content in Connect', () => {
    cy.connectLogin();
    cy.visit('http://connect:3939');
    cy.get('div[class="content-table__display-name"]').first().contains('stock-report-jupyter').click();
    cy.contentiFrame().contains('Stock Report: TSLA');
  });
});