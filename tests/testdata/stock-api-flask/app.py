# -*- coding: utf-8 -*-
import os
import numpy as np
import pandas as pd
from flask import Flask
from flask_restx import Api, Resource, fields

# Fetch prices from local CSV using pandas
prices = pd.read_csv(
    os.path.join(os.path.dirname(__file__), "prices.csv"),
    index_col=0,
    parse_dates=True,
)


# Configure the Flask app using RestX for swagger documentation
app = Flask(__name__)
app.config["SWAGGER_UI_DOC_EXPANSION"] = "list"
app.config["RESTX_MASK_SWAGGER"] = False
app.config["ERROR_INCLUDE_MESSAGE"] = False


api = Api(
    app,
    version="0.1.0",
    title="Stocks API",
    description="The Stocks API provides pricing and volatility data for a "
    "limited number of US equities from 2010-2018",
)
ns = api.namespace("stocks")

# Define stock and price models for marshalling and documenting response objects
tickers_model = ns.model(
    "Tickers",
    {
        "tickers": fields.List(
            fields.String(description="Ticker of the stock"),
            description="All available stock tickers",
        ),
    },
)

stock_model = ns.model(
    "Stock",
    {
        "ticker": fields.String(description="Ticker of the stock"),
        "price": fields.Float(description="Latest price of the stock"),
        "volatility": fields.Float(description="Latest volatility of the stock price"),
    },
)

price_model = ns.model(
    "Price",
    {
        "date": fields.Date,
        "high": fields.Float(description="High price for this date"),
        "low": fields.Float(description="Low price for this date"),
        "close": fields.Float(description="Closing price for this date"),
        "volume": fields.Integer(description="Daily volume for this date"),
        "adjusted": fields.Float(description="Split-adjusted price for this date"),
    },
)


class TickerNotFound(Exception):
    def __init__(self, ticker):
        self.ticker = ticker
        self.message = "Ticker `{}` not found".format(self.ticker)

    def __str__(self):
        return "TickerNotFound('{}')".format(self.ticker)


# Our simple API only has a few GET endpoints
@ns.route("/")
class StockList(Resource):
    """Shows a list of all available tickers"""

    @ns.marshal_with(tickers_model)
    def get(self):
        tickers = prices["ticker"].unique()
        return {"tickers": tickers}


@ns.route("/<string:ticker>")
@ns.response(404, "Ticker not found")
@ns.param("ticker", "The ticker for the stock")
class Stock(Resource):
    """Shows the latest price and volatility for the specified stock"""

    @ns.marshal_list_with(stock_model)
    def get(self, ticker):
        if ticker not in prices["ticker"].unique():
            raise TickerNotFound(ticker)

        ticker_prices = prices[prices["ticker"] == ticker]
        current_price = ticker_prices["close"].last("1d").round(2)
        current_volatility = np.log(
            ticker_prices["adjusted"] / ticker_prices["adjusted"].shift(1)
        ).var()

        return {
            "ticker": ticker,
            "price": current_price,
            "volatility": current_volatility,
        }


@ns.route("/<string:ticker>/history")
@ns.response(404, "Ticker not found")
@ns.param("ticker", "The ticker for the stock")
class StockHistory(Resource):
    """Shows the price history for the specified stock"""

    @ns.marshal_list_with(price_model)
    def get(self, ticker):
        if ticker not in prices["ticker"].unique():
            raise TickerNotFound(ticker)

        ticker_prices = prices[prices["ticker"] == ticker]
        ticker_prices["date"] = ticker_prices.index
        return ticker_prices.to_dict("records")


@api.errorhandler(TickerNotFound)
def handle_ticker_not_found(error):
    return {"message": error.message}, 404


if __name__ == "__main__":
    app.run(debug=True)
