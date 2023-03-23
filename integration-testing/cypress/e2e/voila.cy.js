describe('Publishing Voila Notebook', () => {

  it('Publish button loads', () => {
    cy.visit('http://client:9999/tree/integration-testing/content/voila/index.ipynb');
    cy.get('button[data-jupyter-action="rsconnect_jupyter:publish"]').click();
    cy.get('a[id="publish-to-connect"]').should('be.visible')
  });
  
  it('Add Server Voila', () => {
    cy.visit('http://client:9999/tree/integration-testing/content/voila/index.ipynb');
    cy.addServer();
  });

  it('Publish Content', () => {
    cy.visit('http://client:9999/tree/integration-testing/content/voila/index.ipynb');
    cy.wait(1000);
    cy.get('button[data-jupyter-action="rsconnect_jupyter:publish"]').click();
    cy.get('a[id="publish-to-connect"]').click({ force: true });
    cy.wait(1000);
    cy.get('a[id="rsc-publish-voila"]').click();
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
    cy.get('div[class="content-table__display-name"]').first().contains('index').click();
    cy.contentiFrame().contains('Plot the gaussian density');
  });
  
  it('Remove Server', () => {
    cy.visit('http://client:9999/tree/integration-testing/content/voila/index.ipynb');
    cy.removeServer();
  });

});