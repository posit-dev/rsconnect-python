import pandas as pd

from bokeh.plotting import figure, curdoc
from bokeh.models import (
    ColumnDataSource,
    DataTable,
    TableColumn,
    NumberFormatter,
    MultiChoice,
    Div,
)
from bokeh.layouts import column
from bokeh.palettes import viridis


DEFAULT_COUNTRIES = [
    "Australia",
    "China",
    "France",
    "Germany",
    "Japan",
    "United States",
]

data = pd.read_csv("./data.csv")
grouped = data.groupby("Entity")
countries = data["Entity"].unique().tolist()
colors = dict(zip(countries, viridis(len(countries))))

source = ColumnDataSource(dict(countries=[], years=[], percents=[]))


# Markup header
#
header = Div(
    text="""
    <h1>Top 5% Income Share</h1>
    <p>Share of income received by the richest 5% of the population as sourced by 
        <a href="https://ourworldindata.org/grapher/top-5-income-share">https://ourworldindata.org/grapher/top-5-income-share</a>.
    </p>
"""  # noqa
)


# Country multi-select input
#
countries_selector = MultiChoice(value=DEFAULT_COUNTRIES, options=countries)


# Line plot of selected countries
#
plot = figure(title="Top 5% income share", x_axis_label="Year", y_axis_label="Percent")

plot.multi_line(
    xs="years",
    ys="percents",
    legend_field="countries",
    line_color="color",
    source=source,
)


# Data table of selected countries
#
table = DataTable(
    source=source,
    columns=[
        TableColumn(field="countries", title="Country"),
        TableColumn(field="span", title="Years"),
        TableColumn(
            field="mean",
            title="Percent (mean)",
            formatter=NumberFormatter(format="0.00"),
        ),
    ],
)


def update():
    selected_countries = countries_selector.value
    countries = [name for name, _ in grouped if name in selected_countries]
    years = [list(df["Year"]) for name, df in grouped if name in selected_countries]
    percents = [
        list(df["Percent"]) for name, df in grouped if name in selected_countries
    ]
    span = [
        "%s - %s" % (df["Year"].min(), df["Year"].max())
        for name, df in grouped
        if name in selected_countries
    ]
    mean = [df["Percent"].mean() for name, df in grouped if name in selected_countries]
    color = [colors[name] for name, df in grouped if name in selected_countries]
    source.data = dict(
        countries=countries,
        years=years,
        percents=percents,
        span=span,
        mean=mean,
        color=color,
    )


countries_selector.on_change("value", lambda attr, old, new: update())

update()

curdoc().add_root(column(header, countries_selector, plot, table))
curdoc().title = "Top 5% Income Share"
