import pandas as pd
import numpy as np
import pyprind
import seaborn as sns
import matplotlib.pyplot as plt

from .strategy import Strategy
from .datahandler import HistoricalOptionsData


class Backtest:
    """Processes signals from the Strategy object"""
    def __init__(self):
        self._strategy = None
        self._data = None
        self.inventory = pd.DataFrame()
        self.stop_if_broke = True

    @property
    def strategy(self):
        return self._strategy

    @strategy.setter
    def strategy(self, strat):
        assert isinstance(strat, Strategy)
        self._strategy = strat
        self.current_capital = strat.initial_capital

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, data):
        assert isinstance(data, HistoricalOptionsData)
        self._data = data

    def run(self, monthly=False):
        """Runs the backtest and returns a `pd.DataFrame` of the orders executed (`self.trade_log`)

        Args:
            monthly (bool, optional): Iterates through data monthly rather than daily. Defaults to False.

        Returns:
            pd.DataFrame: Log of the trades executed.
        """

        assert self._data is not None
        assert self._strategy is not None
        assert self._data.schema == self._strategy.schema

        index = pd.MultiIndex.from_product(
            [[l.name for l in self._strategy.legs],
             ['contract', 'underlying', 'expiration', 'type', 'strike', 'cost', 'order']])
        index_totals = pd.MultiIndex.from_product([['totals'], ['cost', 'qty', 'date']])
        self.inventory = pd.DataFrame(columns=index.append(index_totals))
        self.trade_log = pd.DataFrame()

        data_iterator = self._data.iter_months() if monthly else self._data.iter_dates()
        bar = pyprind.ProgBar(data_iterator.ngroups, bar_char='█')

        for date, options in data_iterator:
            entry_signals = self._strategy.filter_entries(options, self.inventory, date)
            exit_signals = self._strategy.filter_exits(options, self.inventory, date)

            self._execute_exit(exit_signals)
            self._execute_entry(entry_signals)

            bar.update()

        return self.trade_log

    def _execute_entry(self, entry_signals):
        """Executes entry orders and updates `self.inventory` and `self.trade_log`"""
        entry, total_price = self._process_entry_signals(entry_signals)

        if (not self.stop_if_broke) or (self.current_capital >= total_price):
            self.inventory = self.inventory.append(entry, ignore_index=True)
            self.trade_log = self.trade_log.append(entry, ignore_index=True)
            self.current_capital -= total_price

    def _execute_exit(self, exit_signals):
        """Executes exits and updates `self.inventory` and `self.trade_log`"""
        exits, exits_mask, total_costs = exit_signals

        self.trade_log = self.trade_log.append(exits, ignore_index=True)
        self.inventory.drop(self.inventory[exits_mask].index, inplace=True)
        self.current_capital -= sum(total_costs)

    def _process_entry_signals(self, entry_signals):
        """Returns a dictionary containing the orders to execute."""

        if not entry_signals.empty:
            # costs = entry_signals['totals']['cost']
            # return entry_signals.loc[costs.idxmin():costs.idxmin()], costs.min()
            entry = entry_signals.iloc[0]
            return entry, entry['totals']['cost'] * entry['totals']['qty']
        else:
            return entry_signals, 0

    def summary(self):
        """Returns a table with summary statistics about the trade log"""
        df = self.trade_log
        df.loc[:,
               ('totals',
                'capital')] = (-df['totals']['cost'] * df['totals']['qty']).cumsum() + self._strategy.initial_capital

        daily_df = df.groupby(('totals', 'date'))
        daily_capital = daily_df.apply(lambda row: row['totals']['capital'].tail(1))
        daily_returns = daily_capital.pct_change() * 100

        entries_mask = df.apply(lambda row: row['leg_1']['order'][2] == 'O', axis=1)
        entries = df.loc[entries_mask]
        exits = df.loc[~entries_mask]

        costs = np.array([])
        for contract in entries['leg_1']['contract']:
            entry = entries.loc[entries['leg_1']['contract'] == contract]
            exit_ = exits.loc[exits['leg_1']['contract'] == contract]
            try:
                # Here we assume we are entering only once per contract (i.e both entry and exit_ have only one row)
                costs = np.append(costs, (entry['totals']['cost'] * entry['totals']['qty']).values[0] +
                                  (exit_['totals']['cost'] * exit_['totals']['qty']).values[0])
            except IndexError:
                continue

        # trades = entries.merge(exits,
        #                        on=[(l.name, 'contract') for l in self._strategy.legs],
        #                        suffixes=['_entry', '_exit'])

        # costs = trades.apply(lambda row: row['totals_entry']['cost'] + row['totals_exit']['cost'], axis=1)

        wins = costs < 0
        losses = costs >= 0
        profit_factor = np.sum(wins) / np.sum(losses)
        total_trades = len(exits)
        win_number = np.sum(wins)
        loss_number = total_trades - win_number
        win_pct = win_number / total_trades
        largest_loss = np.max(costs)
        avg_profit = np.sum(-costs) / len(costs)
        avg_pl = np.mean(daily_returns)
        total_pl = (df['totals']['capital'].iloc[-1] / self._strategy.initial_capital) * 100

        data = [
            total_trades, win_number, loss_number, win_pct, largest_loss, profit_factor, avg_profit, avg_pl, total_pl
        ]
        stats = [
            'Total trades', 'Number of wins', 'Number of losses', 'Win %', 'Largest loss', 'Profit factor',
            'Average profit', 'Average P&L %', 'Total P&L %'
        ]
        strat = ['Strategy']
        summary = pd.DataFrame(data, stats, strat)

        daily_returns = daily_returns[1:].reset_index(level=1, drop=True)
        daily_returns_df = pd.DataFrame(data=daily_returns.groupby(daily_returns.index.year).apply(list).array,
                                        index=daily_returns.index.year.unique(),
                                        columns=[
                                            'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                                            'September', 'October', 'November', 'December'
                                        ])

        sns.heatmap(daily_returns_df, linewidth=0.5, annot=True, fmt='f', cmap='YlGnBu', cbar=False)
        plt.title('Monthly returns heatmap (in percentage)')
        plt.show()

        return summary

    def __repr__(self):
        return "Backtest(capital={}, strategy={})".format(self.current_capital, self._strategy)
