import panel as pn

pn.extension()

def greet(name):
    return f"Hello, {name}!"

text_input = pn.widgets.TextInput(name="Enter your name", placeholder="Type here...")
button = pn.widgets.Button(name="Greet", button_type="primary")

output = pn.pane.Markdown("Click the button to see a greeting!")

def update_output(event):
    output.object = greet(text_input.value)

button.on_click(update_output)

app = pn.Column(
    "# Panel Greeting App",
    text_input,
    button,
    output
)

app.servable()
