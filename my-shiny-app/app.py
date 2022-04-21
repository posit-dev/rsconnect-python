from shiny import *

app_ui = ui.page_fluid(
    ui.input_slider("n", "N", 0, 100, 20),
    ui.output_text_verbatim("txt", placeholder=True),
)

def server(input, output, session):
    @output()
    @render_text()
    def txt():
        return f"n*2 is {input.n() * 2}"

app = App(app_ui, server)